from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import pytest
from wsn_sim.calibration import BenignTrace, aggregate_benign, benign_metrics, linear_quantile, replay_trace, run_calibration, select_candidate, validate_protocol, verify_freeze
from wsn_sim.config import DetectorConfig
from wsn_sim.review import packet_demo, review_attacker, review_detector

@pytest.fixture
def calibration_protocol(project_root):
    protocol = json.loads((project_root / 'configs/calibration_protocol.json').read_text(encoding='utf-8'))
    protocol['duration_s'] = 4
    protocol['structural_grid'] = [{'window_size_s': 1, 'min_observations': 1, 'beta_trust': 0.8, 'consecutive_bad_windows': 1, 'forwarding_timeout_s': 0.02}]
    protocol['min_valid_windows_per_channel'] = 1
    protocol['seed_partitions']['calibration_fit'] = [71001]
    protocol['seed_partitions']['benign_validation'] = [72001]
    return protocol

@pytest.mark.parametrize('partition', ['calibration_fit', 'benign_validation', 'attack_validation_reserved', 'evaluation_reserved'])
def test_seed_partition_overlap_is_rejected_before_any_simulation(calibration_protocol, partition):
    bad = deepcopy(calibration_protocol)
    bad['seed_partitions'][partition].append(bad['seed_partitions']['calibration_fit'][0])
    with pytest.raises(ValueError, match='overlap or repeat'):
        validate_protocol(bad)

@pytest.mark.parametrize('values,expected', [([], None), ([1], 1), ([0, 1], 0.05), ([0] * 5 + [1] * 95, 0.95)])
def test_q05_linear_interpolation_has_hand_computed_reference(values, expected):
    result = linear_quantile(values, 0.05)
    assert result is None if expected is None else result == pytest.approx(expected)

def test_benign_bursts_are_counterexample_to_quantile_fpr_guarantee_and_K_claim():
    report = review_detector()
    assert report['checks_passed']
    assert report['Q0.05'] == pytest.approx(0.95)
    for case in report['quantile_does_not_bound_EWMA_FPR']:
        assert case['metrics']['window_fpr'] == 0.16
        assert case['metrics']['fpr'] == 1
        assert case['metrics']['ever_isolated_nodes'] == 1

def test_nearest_sink_choice_is_geometric_and_channel_censored_drop_denominator_is_transit_RX(config):
    report, simulation = review_attacker(config)
    assert report['checks_passed']
    assert report['nearest_of_all_sinks_then_id']['actual']['attacker_ids'] == ['a', 'b']
    assert report['coupled_probabilities_nested']
    censoring = report['channel_censoring']
    assert 0 < censoring['successful_transit_RX_opportunities'] < censoring['generated']
    assert censoring['conditional_drop_ratio'] > censoring['incorrect_generated_denominator_ratio']
    assert censoring['selective_trace_stops_after_RX']
    assert simulation.network.sensors['relay'].received_packets == censoring['successful_transit_RX_opportunities']

def test_demo_own_attacker_TX_does_not_resolve_its_dropped_transit_packets(config):
    simulation = packet_demo(config)
    state = simulation.detector.states['attacker']
    assert (state.received_transit, state.forwarded, state.failed_timeout) == (2, 0, 2)
    assert (state.suspected_at, state.isolated_at) == (1, 2)
    own = next((packet for packet in simulation.traffic_gen.generated_packets if packet.source_id == 'attacker'))
    assert own.status.value == 'DELIVERED'
    good = simulation.detector.states['good']
    assert (good.received_transit, good.forwarded, good.failed_timeout) == (2, 2, 0)
    assert good.suspected_at is None
    assert simulation.detector.summary()['conservation_ok']

def test_fpr_populations_include_unobserved_benign_nodes_and_report_conditional_NA():
    config = DetectorConfig(0.5, 1, 0.1, 1, 0.8, 1, 1, 10)
    trace = BenignTrace(1, 0, ('relay', 'unobserved'), ('sink',), 1, [('rx', 0.1, 'relay', 'p', 'source')])
    metrics = benign_metrics(replay_trace(trace, config))
    assert (metrics['FP'], metrics['TN'], metrics['fpr']) == (1, 1, 0.5)
    assert (metrics['conditional_FP'], metrics['conditional_TN'], metrics['conditional_fpr']) == (1, 0, 1)
    assert metrics['coverage'] == 0.5
    empty = benign_metrics(replay_trace(replace(trace, events=[]), config))
    assert (empty['FP'], empty['TN'], empty['fpr']) == (0, 2, 0)
    assert empty['conditional_fpr'] is None
    assert empty['window_fpr'] is None

def test_unknown_observation_kind_is_rejected_without_reading_truth(detector_config):
    trace = BenignTrace(1, 0, ('relay',), ('sink',), 5, [('selective_forwarding', 0.1, 'relay', 'p', 'source')])
    with pytest.raises(ValueError, match='observable'):
        replay_trace(trace, detector_config)

def test_selection_ties_follow_preregistered_order_and_do_not_use_validation_fields(calibration_protocol):
    config = DetectorConfig(0.8, 1, 0.02, 1, 1, 1, 1, 60)
    channels = [{'conditional_fpr': 0, 'min_seed_coverage': 0.5}]
    preferred = {'candidate_id': 'first', 'eligible': True, 'parameters': asdict(config), 'channels': channels, 'evaluation_score': -100, 'validation_fpr': 1}
    alternative = {**preferred, 'candidate_id': 'other', 'parameters': asdict(replace(config, trust_threshold=0.95)), 'evaluation_score': 100, 'validation_fpr': 0}
    assert select_candidate([alternative, preferred], calibration_protocol)['candidate_id'] == 'first'
    with pytest.raises(ValueError, match='no candidate'):
        select_candidate([{**preferred, 'eligible': False}], calibration_protocol)

@pytest.fixture
def instrumented_calibration(monkeypatch):
    calls = []
    reject_validation = [False]

    def capture(plan, seed, channel, directory, root, duration_s):
        phase = directory.parent.name
        if phase == 'benign_validation':
            selection = json.loads((directory.parent.parent / 'selection_before_validation.json').read_text(encoding='utf-8'))
            assert not selection['benign_validation_seen']
            assert not selection['evaluation_seen']
        calls.append((phase, seed, channel))
        directory.mkdir(parents=True)
        events = []
        for index in range(3):
            events.append(('rx', index + 0.1, 'relay', f'p{index}', 'source'))
            if phase != 'benign_validation' or not reject_validation[0]:
                events.append(('tx', index + 0.11, 'relay', f'p{index}', 'source'))
        return BenignTrace(seed, channel, ('relay', 'unobserved'), ('sink',), duration_s, events)
    monkeypatch.setattr('wsn_sim.calibration._capture_trace', capture)
    return (calls, reject_validation)

def test_calibration_selects_before_holdout_freezes_and_never_executes_reserved_seeds(project_root, calibration_protocol, instrumented_calibration, tmp_path):
    calls, _ = instrumented_calibration
    protocol_file = tmp_path / 'protocol.json'
    protocol_file.write_text(json.dumps(calibration_protocol), encoding='utf-8')
    frozen = tmp_path / 'frozen.json'
    report = run_calibration(project_root, protocol_file, tmp_path / 'runs', frozen)
    assert report['frozen'] and report['benign_validation_passed']
    assert report['fit_candidate_trials'] == 6
    assert report['benign_validation_trials'] == 3
    assert report['false_positive_reduction'] == 'NOT_DEMONSTRATED'
    assert not report['selection_used_evaluation'] and (not report['selection_used_attacker_labels'])
    assert [phase for phase, _, _ in calls] == ['calibration_fit'] * 3 + ['benign_validation'] * 3
    assert {seed for _, seed, _ in calls} == {71001, 72001}
    assert verify_freeze(frozen, project_root)['verified']
    lock = json.loads(frozen.with_suffix('.lock.json').read_text(encoding='utf-8'))
    assert lock['evaluation_runs_before_freeze'] == 0
    assert lock['protocol_sha256'] == report['protocol_sha256']
    assert json.loads(frozen.read_text(encoding='utf-8'))['calibration_status'] == 'CALIBRATED'
    directory = Path(report['output_directory'])
    rows = json.loads((directory / 'all_configurations.json').read_text(encoding='utf-8'))
    assert len(rows['references']) == 1 and len(rows['candidates']) == 2
    with pytest.raises(FileExistsError, match='already exists'):
        run_calibration(project_root, protocol_file, tmp_path / 'runs', frozen)
    frozen.write_text(frozen.read_text(encoding='utf-8') + ' ', encoding='utf-8')
    with pytest.raises(ValueError, match='changed'):
        verify_freeze(frozen, project_root)

def test_holdout_failure_is_preserved_and_does_not_trigger_reselection_or_freeze(project_root, calibration_protocol, instrumented_calibration, tmp_path):
    calls, reject_validation = instrumented_calibration
    reject_validation[0] = True
    protocol_file = tmp_path / 'protocol.json'
    protocol_file.write_text(json.dumps(calibration_protocol), encoding='utf-8')
    frozen = tmp_path / 'rejected.json'
    report = run_calibration(project_root, protocol_file, tmp_path / 'runs', frozen)
    assert not report['frozen'] and (not report['benign_validation_passed'])
    assert not report['reselected_after_validation']
    assert not frozen.exists() and (not frozen.with_suffix('.lock.json').exists())
    assert any((row['conditional_fpr'] == 1 for row in report['benign_validation_channels']))
    assert len(calls) == 6

def test_failed_physical_run_is_logged_and_not_silently_excluded(project_root, calibration_protocol, monkeypatch, tmp_path):

    def fail(*args, **kwargs):
        raise RuntimeError('injected capture failure')
    monkeypatch.setattr('wsn_sim.calibration._capture_trace', fail)
    protocol_file = tmp_path / 'protocol.json'
    protocol_file.write_text(json.dumps(calibration_protocol), encoding='utf-8')
    with pytest.raises(RuntimeError, match='injected capture'):
        run_calibration(project_root, protocol_file, tmp_path / 'runs')
    status_path = next((tmp_path / 'runs').glob('*/run_status.json'))
    status = json.loads(status_path.read_text(encoding='utf-8'))
    assert status['status'] == 'FAILED'
    assert status['completed_benign_runs'] == 0
    assert status['pending_benign_runs'] == 6
    assert len(status['failed_runs']) == 1

def test_aggregate_keeps_all_three_channel_conditions_and_coverage_denominators(detector_config):
    trace = BenignTrace(1, 0, ('relay', 'unobserved'), ('sink',), 5, [('rx', 0.1, 'relay', 'p', 'source')])
    rows = [{'channel_loss_probability': 0, **benign_metrics(replay_trace(trace, detector_config))}]
    channels = aggregate_benign(rows)
    assert [row['channel_loss_probability'] for row in channels] == [0, 0.01, 0.05]
    assert channels[0]['fpr'] == 0.5 and channels[0]['conditional_fpr'] == 1
    assert channels[0]['coverage'] == 0.5
    assert channels[1]['conditional_fpr'] is None and channels[1]['runs'] == 0
