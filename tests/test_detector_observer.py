from collections import Counter
from dataclasses import replace
import ast
import inspect
import json
from math import nextafter
from pathlib import Path
import subprocess
import sys
import pytest
import wsn_sim.detection as detection_module
from wsn_sim.detection import ForwardingDetector, benign_calibration_profile
from wsn_sim.detector_verification import sensitivity_checks
from wsn_sim.metrics import security_metrics
from wsn_sim.models import Packet, PacketStatus
from wsn_sim.randomness import event_occurs
from wsn_sim.simulation import Simulation
from wsn_sim.storage import save_simulation

def test_early_forwarded_packets_wait_for_their_deadline_cohort(detector_config):
    detector = ForwardingDetector(detector_config, ['relay'])
    detector.observe_received('relay', 'failed', 'source', 0)
    detector.observe_received('relay', 'boundary', 'source', 4)
    detector.observe_forwarded('relay', 'boundary', 4.1)
    detector.observe_received('relay', 'next_cohort', 'source', 4.5)
    detector.observe_forwarded('relay', 'next_cohort', 4.6)
    detector.advance(5)
    first = detector.windows[-1]
    assert first['observations'] == 1
    assert first['forwarded'] == 0
    assert first['forwarding_ratio'] == 0
    assert first['trust'] == 0.5
    detector.advance(10)
    second = detector.windows[-1]
    assert second['observations'] == 2
    assert second['forwarded'] == 2
    assert second['forwarding_ratio'] == 1
    assert second['trust'] == 0.75

def test_known_forwarded_outcome_cannot_enter_a_cohort_before_its_deadline(detector_config):
    detector = ForwardingDetector(replace(detector_config, window_size_s=1, forwarding_timeout_s=2), ['relay'])
    detector.observe_received('relay', 'p', 'source', 0.1)
    detector.observe_forwarded('relay', 'p', 0.2)
    detector.advance(2)
    assert [row['observations'] for row in detector.windows] == [0, 0]
    assert all((row['status'] == 'insufficient_data' for row in detector.windows))
    assert detector.states['relay'].forwarded == 1
    assert detector.states['relay'].trust == 1
    assert detector.summary()['known_outcomes_awaiting_cohort'] == 1
    detector.advance(3)
    assert detector.windows[-1]['observations'] == 1
    assert detector.windows[-1]['forwarding_ratio'] == 1
    assert detector.observation_records()[0]['cohort_closed']

def test_received_forwarded_failed_pending_and_excluded_inputs_are_conserved(detector_config):
    detector = ForwardingDetector(detector_config, ['relay'], sink_ids=['sink'])
    detector.observe_received('relay', 'own', 'relay', 0)
    detector.observe_received('sink', 'sink_packet', 'source', 0)
    detector.observe_received('ghost', 'unknown_packet', 'source', 0)
    detector.observe_forwarded('relay', 'own', 0, source_id='relay')
    detector.observe_forwarded('sink', 'sink_packet', 0, source_id='source')
    detector.observe_forwarded('relay', 'unmatched', 0)
    detector.observe_received('relay', 'p', 'source', 0.1)
    detector.observe_received('relay', 'p', 'source', 0.2)
    detector.observe_forwarded('relay', 'p', 0.3, source_id='different_source')
    assert detector.states['relay'].pending == 1
    detector.observe_forwarded('relay', 'p', 0.4, source_id='source')
    detector.observe_forwarded('relay', 'p', 0.5)
    detector.observe_received('relay', 'q', 'source', 0.6)
    detector.advance(2)
    detector.observe_forwarded('relay', 'q', 2.1)
    detector.advance(5)
    detector.observe_received('relay', 'p', 'source', 6)
    summary = detector.summary()
    assert (summary['received_transit'], summary['forwarded'], summary['failed_timeout'], summary['pending']) == (2, 1, 1, 0)
    assert summary['input_counts'] == {'rx': 7, 'tx': 7}
    assert (summary['excluded_rx'], summary['excluded_tx'], summary['excluded']) == (5, 6, 11)
    assert summary['conservation_ok'] and summary['input_conservation_ok']
    assert summary['excluded_by_reason'] == {'rx:own_packet': 1, 'rx:sink': 1, 'rx:unknown_node': 1, 'rx:duplicate_received': 2, 'tx:own_packet': 1, 'tx:sink': 1, 'tx:unmatched_forwarded': 1, 'tx:source_mismatch': 1, 'tx:duplicate_forwarded': 1, 'tx:forwarded_after_timeout': 1}
    assert len(detector.observations) == 2
    assert Counter((row.outcome for row in detector.observations.values())) == {'forwarded': 1, 'failed_timeout': 1}
    assert len(detector.exclusions) == 11
    record = detector.observations['relay', 'p']
    assert record.received_at_s == 0.1
    assert record.deadline_s == 1.1
    assert record.resolved_at_s == 0.4

@pytest.mark.parametrize(('when', 'forwarded'), [(nextafter(1.0, 0.0), 1), (1.0, 0), (nextafter(1.0, 2.0), 0)])
def test_timeout_boundary_is_strict_without_premature_failure(detector_config, when, forwarded):
    detector = ForwardingDetector(detector_config, ['relay'])
    detector.observe_received('relay', 'p', 'source', 0)
    detector.observe_forwarded('relay', 'p', when)
    detector.advance(5)
    state = detector.states['relay']
    assert state.forwarded == forwarded
    assert state.failed_timeout == 1 - forwarded
    assert state.pending == 0
    assert detector.windows[-1]['observations'] == 1
    assert detector.windows[-1]['forwarding_ratio'] == forwarded
    assert state.conservation_ok

def test_late_forward_does_not_rewrite_closed_cohort_or_trust(detector_config):
    detector = ForwardingDetector(detector_config, ['relay'])
    detector.observe_received('relay', 'p', 'source', 0)
    detector.advance(5)
    before = dict(detector.windows[-1])
    detector.observe_forwarded('relay', 'p', 6)
    assert detector.windows[-1] == before
    assert detector.states['relay'].trust == 0.5
    assert detector.states['relay'].failed_timeout == 1
    assert detector.exclusions[-1]['reason'] == 'forwarded_after_timeout'

def test_deadline_at_window_boundary_belongs_to_the_next_cohort_even_when_forwarded_early(detector_config):
    detector = ForwardingDetector(detector_config, ['relay'])
    detector.observe_received('relay', 'p', 'source', 4)
    detector.observe_forwarded('relay', 'p', 4.2)
    detector.advance(5)
    assert detector.windows[-1]['observations'] == 0
    assert detector.observation_records()[0]['matured']
    assert not detector.observation_records()[0]['cohort_closed']
    detector.advance(10)
    assert detector.windows[-1]['observations'] == 1
    assert detector.windows[-1]['cohort_index'] == 1
    assert detector.windows[-1]['window_start_s'] == 5
    assert detector.windows[-1]['window_end_s'] == 10

def test_decimal_clock_boundaries_and_nonzero_start_do_not_drift(detector_config):
    cfg = replace(detector_config, window_size_s=0.1, forwarding_timeout_s=0.3)
    detector = ForwardingDetector(cfg, ['relay'], start_time_s=2.3)
    detector.observe_received('relay', 'p', 'source', 2.3)
    detector.observe_forwarded('relay', 'p', 2.6)
    detector.advance(2.9)
    assert [row['time_s'] for row in detector.windows] == [2.4, 2.5, 2.6, 2.7, 2.8, 2.9]
    sampled = [row for row in detector.windows if row['observations']]
    assert len(sampled) == 1
    assert sampled[0]['time_s'] == 2.7
    assert sampled[0]['failed_timeout'] == 1

@pytest.mark.parametrize('initial_trust', [0, 0.4, 1])
def test_empty_cohorts_never_synthesize_zero_trust_or_suspicion(detector_config, initial_trust):
    detector = ForwardingDetector(replace(detector_config, initial_trust=initial_trust), ['relay'])
    detector.advance(20)
    assert all((row['status'] == 'insufficient_data' and row['forwarding_ratio'] is None for row in detector.windows))
    assert detector.states['relay'].trust == initial_trust
    assert not detector.states['relay'].suspected
    assert detector.states['relay'].bad_windows == 0
    assert not detector.is_isolated('relay', 20)
    profile = benign_calibration_profile(detector.windows)
    assert profile['valid_windows'] == 0
    assert profile['minimum_trust'] is None
    assert profile['calibration_status'] == 'NEEDS_CALIBRATION'

def test_insufficient_cohort_preserves_trust_and_bad_streak(detector_config):
    detector = ForwardingDetector(replace(detector_config, min_observations=2), ['relay'])
    detector.observe_received('relay', 'p1', 'source', 0)
    detector.observe_received('relay', 'p2', 'source', 0)
    detector.advance(5)
    assert detector.states['relay'].trust == 0.5
    assert detector.states['relay'].bad_windows == 1
    detector.observe_received('relay', 'p3', 'source', 5.1)
    detector.advance(10)
    assert detector.windows[-1]['status'] == 'insufficient_data'
    assert detector.windows[-1]['observations'] == 1
    assert detector.states['relay'].trust == 0.5
    assert detector.states['relay'].bad_windows == 1
    assert not detector.is_isolated('relay', 10)

def test_threshold_equality_is_not_bad(detector_config):
    detector = ForwardingDetector(replace(detector_config, trust_threshold=0.5, consecutive_bad_windows=1), ['relay'])
    detector.observe_received('relay', 'p', 'source', 0)
    detector.advance(5)
    assert detector.states['relay'].trust == 0.5
    assert not detector.states['relay'].suspected
    assert not detector.is_isolated('relay', 5)

def test_no_extra_forwarding_ratio_gate_can_suppress_low_trust_isolation(detector_config):
    cfg = replace(detector_config, initial_trust=0, beta_trust=0.9, consecutive_bad_windows=1)
    detector = ForwardingDetector(cfg, ['relay'])
    detector.observe_received('relay', 'p', 'source', 0)
    detector.observe_forwarded('relay', 'p', 0.1)
    detector.advance(5)
    assert detector.windows[-1]['forwarding_ratio'] == 1
    assert detector.states['relay'].trust == pytest.approx(0.1)
    assert detector.is_isolated('relay', 5)

def test_suspected_and_isolated_events_keep_distinct_times_and_complete_context(detector_config):
    detector = ForwardingDetector(detector_config, ['relay'])
    detector.observe_received('relay', 'p1', 'source', 0)
    detector.advance(5)
    detector.observe_received('relay', 'p2', 'source', 5.1)
    detector.advance(10)
    suspected = next((row for row in detector.events if row['event'] == 'suspected'))
    isolated = next((row for row in detector.events if row['event'] == 'isolated'))
    assert suspected['time_s'] == 5
    assert isolated['time_s'] == 10
    for row in (suspected, isolated):
        assert row['reason']
        assert row['observations'] == 1
        assert row['forwarding_ratio'] == 0
        assert row['trust'] < row['trust_threshold']
        assert row['min_observations'] == 1
        assert row['required_bad_windows'] == 2
    assert suspected['bad_windows'] == 1
    assert isolated['bad_windows'] == 2
    assert detector.states['relay'].suspected_at == 5
    assert detector.states['relay'].isolated_at == 10

def test_same_observations_are_unchanged_by_ground_truth_evaluation(detector_config):
    detector = ForwardingDetector(detector_config, ['relay'])
    detector.observe_received('relay', 'p', 'source', 0)
    detector.advance(5)
    before = detector.summary()
    benign = security_metrics(['relay'], [], detector, 5)
    malicious = security_metrics(['relay'], ['relay'], detector, 5)
    assert benign['FP'] == 1
    assert malicious['TP'] == 1
    assert detector.summary() == before

def test_detector_source_has_no_ground_truth_or_energy_shortcuts():
    tree = ast.parse(inspect.getsource(detection_module))
    accessed = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not accessed.intersection({'attacker_ids', 'attacker_flag', 'is_attacker', 'p_drop', 'drop_reason', 'decision_seed', 'is_alive', 'energy_j', 'attack'})
    assert not any((isinstance(node, ast.ImportFrom) and node.module and any((name in node.module for name in ('attacks', 'traffic', 'metrics', 'network'))) for node in ast.walk(tree)))

def test_detector_rejects_broad_config_and_nonprimitive_observation_objects(config, detector_config):
    with pytest.raises(TypeError, match='only a DetectorConfig'):
        ForwardingDetector(config, ['relay'])
    detector = ForwardingDetector(detector_config, ['relay'])
    with pytest.raises(TypeError, match='IDs must be strings'):
        detector.observe_received('relay', Packet('p', 'source', 0, 128), 'source', 0)
    assert detector.summary()['input_counts'] == {'rx': 0, 'tx': 0}

@pytest.mark.parametrize('time_s', [-1, float('nan'), float('inf'), True])
def test_invalid_observer_times_do_not_change_counters(detector_config, time_s):
    detector = ForwardingDetector(detector_config, ['relay'])
    with pytest.raises((TypeError, ValueError)):
        detector.observe_received('relay', 'p', 'source', time_s)
    assert detector.summary()['input_counts'] == {'rx': 0, 'tx': 0}

def test_unrepresentable_timeout_does_not_accept_a_partial_observation(detector_config):
    cfg = replace(detector_config, window_size_s=100000.0, forwarding_timeout_s=1e-20)
    detector = ForwardingDetector(cfg, ['relay'], start_time_s=1e+20)
    with pytest.raises(ValueError, match='finite simulation clock'):
        detector.observe_received('relay', 'p', 'source', 1e+20)
    assert detector.summary()['conservation_ok']
    assert detector.summary()['input_conservation_ok']

def test_energy_death_after_rx_is_not_exempted_using_true_drop_reason(network_factory, detector_config):
    cfg = replace(detector_config, window_size_s=1, forwarding_timeout_s=0.1)
    network = network_factory({'source': (0, 0), 'relay': (10, 0)}, [('source', 'relay'), ('relay', 'sink')], sinks={'sink': (20, 0)}, detector=cfg, routing_algorithm='MHR')
    simulation = Simulation(network.config, network=network)
    budget = 1024 * 5e-08 + 1024 * (5e-08 + 1e-11 * 10 ** 2) / 2
    network.sensors['relay'].consume_energy(5 - budget, 0)
    packet = simulation.traffic_gen.generate_packet('source')
    simulation.run_for(1.1)
    assert packet.drop_reason == 'energy_depletion'
    state = simulation.detector.states['relay']
    assert (state.received_transit, state.forwarded, state.failed_timeout, state.pending) == (1, 0, 1, 0)
    assert state.trust == 0.5
    assert state.suspected_at == 1
    assert network.sensors['relay'].died_at == pytest.approx(1024 / 250000)
    timeout = next((row for row in simulation.detector.events if row['event'] == 'timeout'))
    assert timeout['reason'] == 'forwarding_not_observed_before_deadline'
    assert simulation.detector.summary()['input_conservation_ok']

def test_next_hop_loss_still_counts_observed_relay_tx(network_factory, detector_config, config):

    def loses(seed, sender, receiver):
        return event_occurs(replace(config, seed=seed).stream_seeds['channel_loss'], 0.5, 'source_p1', sender, receiver, 0)
    seed = next((seed for seed in range(1000) if not loses(seed, 'source', 'relay') and loses(seed, 'relay', 'sink')))
    cfg = replace(detector_config, window_size_s=1, forwarding_timeout_s=0.1)
    network = network_factory({'source': (0, 0), 'relay': (10, 0)}, [('source', 'relay'), ('relay', 'sink')], sinks={'sink': (20, 0)}, detector=cfg, channel_loss_probability=0.5, seed=seed)
    simulation = Simulation(network.config, network=network)
    packet = simulation.traffic_gen.generate_packet('source')
    simulation.run_for(1.1)
    assert packet.drop_reason == 'natural_link_loss'
    state = simulation.detector.states['relay']
    assert (state.received_transit, state.forwarded, state.failed_timeout) == (1, 1, 0)
    assert state.trust == 1
    assert state.suspected_at is None

@pytest.mark.parametrize('failure', ['channel', 'rx_energy'])
def test_failed_reception_never_creates_detector_pending(network_factory, detector_config, failure):
    cfg = replace(detector_config, window_size_s=1, forwarding_timeout_s=0.1)
    network = network_factory({'source': (0, 0), 'relay': (10, 0)}, [('source', 'relay'), ('relay', 'sink')], sinks={'sink': (20, 0)}, detector=cfg, routing_algorithm='MHR', channel_loss_probability=1 if failure == 'channel' else 0)
    if failure == 'rx_energy':
        network.sensors['relay'].consume_energy(5 - 1e-08, 0)
    simulation = Simulation(network.config, network=network)
    simulation.traffic_gen.generate_packet('source')
    simulation.run_for(1.1)
    assert simulation.detector.states['relay'].received_transit == 0
    assert simulation.detector.states['relay'].trust == 1
    assert not simulation.detector.pending

def test_missing_tx_observation_is_not_excused_by_successful_delivery(network_factory, detector_config, monkeypatch):
    cfg = replace(detector_config, window_size_s=1, forwarding_timeout_s=0.1)
    network = network_factory({'source': (0, 0), 'relay': (50, 0)}, detector=cfg, communication_range_m=60)
    simulation = Simulation(network.config, network=network)
    original = simulation.detector.observe_forwarded

    def lose_relay_observation(relay_id, packet_id, time_s, *, source_id=None):
        if relay_id != 'relay':
            original(relay_id, packet_id, time_s, source_id=source_id)
    monkeypatch.setattr(simulation.detector, 'observe_forwarded', lose_relay_observation)
    packet = simulation.traffic_gen.generate_packet('source')
    simulation.run_for(1.1)
    assert packet.status is PacketStatus.DELIVERED
    assert simulation.detector.states['relay'].failed_timeout == 1
    assert simulation.detector.states['relay'].suspected_at == 1

def test_saved_detector_data_has_pair_ledger_exclusions_cohorts_and_conserved_counters(network_factory, detector_config, tmp_path, project_root):
    import pandas as pd
    network = network_factory({'source': (0, 0), 'relay': (50, 0)}, detector=detector_config, communication_range_m=60)
    simulation = Simulation(network.config, network=network)
    simulation.traffic_gen.generate_packet('source')
    simulation.run_for(5.1)
    save_simulation(simulation, tmp_path, project_root)
    ledger = pd.read_csv(tmp_path / 'detector_observations.csv')
    excluded = pd.read_csv(tmp_path / 'detector_excluded.csv')
    assert {'relay_id', 'packet_id', 'deadline_s', 'cohort_index', 'outcome', 'matured', 'cohort_closed'}.issubset(ledger.columns)
    assert {'reason', 'observation_kind'}.issubset(excluded.columns)
    summary = json.loads((tmp_path / 'detector_summary.json').read_text(encoding='utf-8'))
    assert summary['conservation_ok'] and summary['input_conservation_ok']
    assert summary['model']['next_hop_ack_required'] is False
    manifest = json.loads((tmp_path / 'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['observer']['version'] == 'ideal_observer_deadline_cohorts_v1'

@pytest.mark.parametrize('kind', ['rx', 'tx'])
def test_backdated_input_is_rejected_without_revising_counts_or_trust(detector_config, kind):
    detector = ForwardingDetector(detector_config, ['relay'])
    detector.observe_received('relay', 'p', 'source', 0)
    detector.advance(5)
    before = detector.summary()
    if kind == 'rx':
        call = lambda: detector.observe_received('relay', 'q', 'source', 4)
    else:
        call = lambda: detector.observe_forwarded('relay', 'p', 4)
    with pytest.raises(ValueError, match='monotonic'):
        call()
    assert detector.summary() == before

def test_sensitivity_records_every_test_only_configuration_without_selecting_optimum():
    rows = sensitivity_checks()
    assert len(rows) == 7
    by_parameter = {next(iter(row['changed_parameters']), 'base'): row for row in rows}
    assert set(by_parameter) == {'base', 'window_size_s', 'min_observations', 'beta_trust', 'trust_threshold', 'consecutive_bad_windows', 'forwarding_timeout_s'}
    assert all((row['parameters']['calibration_status'] == 'TEST_ONLY' for row in rows))
    assert all((row['summary']['conservation_ok'] and row['summary']['input_conservation_ok'] for row in rows))
    assert by_parameter['base']['summary']['relays']['relay']['trust'] == 0.9375
    assert by_parameter['min_observations']['summary']['relays']['relay']['trust'] == 0.75
    assert by_parameter['forwarding_timeout_s']['summary']['failed_timeout'] == 2
    assert by_parameter['base']['summary']['failed_timeout'] == 1
    assert by_parameter['consecutive_bad_windows']['summary']['relays']['relay']['isolated_at'] == 1
    assert by_parameter['base']['summary']['relays']['relay']['isolated_at'] is None

def test_detector_check_script_exports_real_cases_pair_ledgers_and_no_calibration_claim(project_root, tmp_path):
    result = subprocess.run([sys.executable, 'scripts/check_detector.py', '--output', str(tmp_path)], cwd=project_root, check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report['stage'] == 3
    assert report['checks_passed']
    assert report['configuration_selected'] is False
    assert report['calibration_status'] == 'NEEDS_CALIBRATION'
    assert [row['trust'] for row in report['hand_calculation']['windows']] == [0.75, 0.375]
    assert [row['observations'] for row in report['deadline_cohort']['windows']] == [1, 2]
    cases = report['simulation_cases']
    assert cases['benign']['summary']['performance']['delivered'] == 1
    assert cases['channel_after_tx']['summary']['detector']['failed_timeout'] == 0
    assert cases['relay_energy_failure']['summary']['detector']['failed_timeout'] == 1
    assert cases['missing_tx_observation']['summary']['performance']['delivered'] == 1
    assert cases['missing_tx_observation']['summary']['detector']['failed_timeout'] == 1
    relay = cases['selective_forwarding']['summary']['detector']['relays']['relay']
    assert (relay['suspected_at'], relay['isolated_at']) == (1, 2)
    directory = Path(report['output_directory'])
    assert (directory / 'selective_forwarding' / 'detector_observations.csv').exists()
    assert (directory / 'selective_forwarding' / 'detector_excluded.csv').exists()
    sensitivity = json.loads((directory / 'sensitivity.json').read_text(encoding='utf-8'))
    assert not sensitivity['selection_performed']
    assert len(sensitivity['configurations']) == 7
    manifest = json.loads((directory / 'run_manifest.json').read_text(encoding='utf-8'))
    assert all((Path(path).exists() for path in manifest['generated_files']))

def test_benign_collection_cli_keeps_all_overrides_and_revokes_calibrated_label(project_root, detector_config, tmp_path):
    from dataclasses import asdict
    path = tmp_path / 'detector.json'
    path.write_text(json.dumps(asdict(replace(detector_config, calibration_status='CALIBRATED'))), encoding='utf-8')
    result = subprocess.run([sys.executable, 'scripts/calibrate_detector.py', '--detector-config', str(path), '--duration', '11', '--seed', '314', '--channel-loss', '0.05', '--window-size-s', '2', '--forwarding-timeout-s', '0.2', '--beta-trust', '0.6', '--trust-threshold', '0.7', '--initial-trust', '0.9', '--isolation-duration-s', '5', '--min-observations', '2', '--consecutive-bad-windows', '3', '--output', str(tmp_path)], cwd=project_root, check=True, capture_output=True, text=True)
    body, _, output = result.stdout.rpartition('output_directory=')
    report = json.loads(body)
    assert report['calibration_status'] == 'NEEDS_CALIBRATION'
    assert report['valid_windows'] == 0
    assert report['minimum_trust'] is None
    assert report['detector_parameters'] == {'beta_trust': 0.6, 'window_size_s': 2, 'forwarding_timeout_s': 0.2, 'min_observations': 2, 'trust_threshold': 0.7, 'consecutive_bad_windows': 3, 'initial_trust': 0.9, 'isolation_duration_s': 5, 'calibration_status': 'TEST_ONLY'}
    assert report['observation_counters']['known_outcomes_awaiting_cohort'] > 0
    assert report['observation_counters']['input_conservation_ok']
    manifest = json.loads((Path(output.strip()) / 'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['configuration']['seed'] == 314
    assert manifest['configuration']['channel_loss_probability'] == 0.05
    assert manifest['attack']['attacker_count'] == 0
    assert manifest['configuration']['detector']['calibration_status'] == 'TEST_ONLY'
