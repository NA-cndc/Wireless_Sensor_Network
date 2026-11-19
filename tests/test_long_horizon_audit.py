from dataclasses import replace
import importlib.util
import json
import hashlib
from pathlib import Path
import numpy as np
import pytest
from wsn_sim.calibration import validate_protocol
from wsn_sim.config import DetectorConfig
from wsn_sim.detection import ForwardingDetector
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('security_crosscheck_study', ROOT / 'analysis/security_crosscheck/study.py')
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)

@pytest.mark.parametrize('window', [1, 2])
@pytest.mark.parametrize('beta', [0.5, 0.8])
@pytest.mark.parametrize('minimum', [1, 2])
def test_fast_cohort_projection_matches_reference_at_deadlines_and_cutoff(window, beta, minimum):
    params = dict(beta_trust=beta, window_size_s=window, forwarding_timeout_s=0.2, min_observations=minimum, trust_threshold=0.8, consecutive_bad_windows=2, initial_trust=1, isolation_duration_s=2, calibration_status='TEST_ONLY')
    trace = {'sensor_ids': np.array(['relay', 'other']), 'relay': np.array([0, 0, 0, 0, 1, 1]), 'rx': np.array([0.1, 0.8, 1.1, 3.9, 0.4, 1.2]), 'tx': np.array([0.11, 1.0, np.nan, np.nan, 0.41, 1.21])}
    d = ForwardingDetector(DetectorConfig(**params), trace['sensor_ids'].tolist())
    events = []
    for i, (node, rx, tx) in enumerate(zip(trace['relay'], trace['rx'], trace['tx'])):
        events.append((float(rx), 0, trace['sensor_ids'][node], str(i)))
        if np.isfinite(tx):
            events.append((float(tx), 1, trace['sensor_ids'][node], str(i)))
    for t, kind, node, packet in sorted(events):
        if kind == 0:
            d.observe_received(str(node), packet, 'source', t)
        else:
            d.observe_forwarded(str(node), packet, t, source_id='source')
    d.advance(4)
    n, f = study.cohort_arrays(trace, window, 0.2, 4)
    actual = study.fast_prediction(n, f, params)
    for i, node in enumerate(trace['sensor_ids']):
        state = d.states[node]
        assert actual['trust'][i] == pytest.approx(state.trust)
        assert actual['valid_windows'][i] == state.valid_windows
        assert (None if np.isnan(actual['first'][i]) else actual['first'][i]) == state.suspected_at
    assert d.states['relay'].pending == 1
    assert d.summary()['conservation_ok']

def test_K_changes_isolation_but_does_not_change_ever_suspected_FPR():
    base = DetectorConfig(0.5, 1, 0.1, 1, 0.8, 1, 1, 10)
    a = ForwardingDetector(base, ['honest'])
    b = ForwardingDetector(replace(base, consecutive_bad_windows=3), ['honest'])
    for detector in (a, b):
        detector.observe_received('honest', 'legitimate_forwarding_failure', 'source', 0.1)
        detector.advance(1)
    assert a.states['honest'].suspected_at == b.states['honest'].suspected_at == 1
    assert a.states['honest'].isolated_at == 1
    assert b.states['honest'].isolated_at is None

def test_projection_does_not_round_exact_decimal_deadline_into_success():
    trace = {'sensor_ids': np.array(['relay']), 'relay': np.array([0]), 'rx': np.array([0.1]), 'tx': np.array([0.3])}
    n, f = study.cohort_arrays(trace, 1, 0.2, 1)
    assert n.sum() == 1
    assert f.sum() == 0

def test_registered_long_protocol_requires_disjoint_seeds_and_declared_prediction():
    p = study.protocol()
    validate_protocol(p)
    p['seed_partitions']['benign_validation'][0] = p['seed_partitions']['calibration_fit'][0]
    with pytest.raises(ValueError, match='overlap'):
        validate_protocol(p)
    p = study.protocol()
    p['prediction'] = 'currently_suspected'
    with pytest.raises(ValueError, match='prediction'):
        validate_protocol(p)

def test_counterfactual_overhead_uses_radio_units_and_does_not_claim_simulated_cost():
    module_spec = importlib.util.spec_from_file_location('overhead', ROOT / 'analysis/security_crosscheck/overhead.py')
    overhead = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(overhead)
    unspecified = overhead.estimate(100, 128, 250000)
    assert unspecified['estimated_overhearing_energy_j'] is None
    assert unspecified['estimated_ACK_packets'] is None
    result = overhead.estimate(100, 128, 250000, observers_per_tx=1, ack_bytes=16, ack_distance_m=10)
    assert result['estimated_overhearing_energy_j'] == pytest.approx(0.00512)
    assert result['estimated_active_RX_time_s'] == pytest.approx(0.4096)
    assert result['estimated_system_ACK_energy_j'] == pytest.approx(0.0012928)
    assert result['simulated_monitoring_energy_j'] is None
    assert result['simulated_control_packets'] is None
    with pytest.raises(ValueError):
        overhead.estimate(100, 128, 250000, ack_bytes=16)

def test_long_freeze_verifies_validation_evidence_and_rejects_tampering(tmp_path):
    from wsn_sim.calibration import verify_freeze, source_fingerprint, json_digest
    p = study.protocol()
    cfg = {**p['fixed'], **{k: v[0] for k, v in p['grid'].items()}, 'calibration_status': 'CALIBRATED'}
    path = tmp_path / 'configs/detector.json'
    path.parent.mkdir()
    path.write_text(json.dumps(cfg), encoding='utf-8')
    evidence = tmp_path / 'results/gate.json'
    evidence.parent.mkdir()
    fingerprint = source_fingerprint(tmp_path)
    gate = {'benign_passed': True, 'attack_passed': True, 'protocol_sha256': json_digest(p), 'parameters': {**cfg, 'calibration_status': 'TEST_ONLY'}, 'source_sha256': fingerprint['sha256']}
    evidence.write_text(json.dumps(gate), encoding='utf-8')
    lock = {'protocol': p, 'protocol_sha256': json_digest(p), 'benign_validation_passed': True, 'source_fingerprint': fingerprint, 'detector_parameters': cfg, 'simulation_configuration': {}, 'simulation_config_sha256': json_digest({}), 'config_file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'validation_evidence_path': 'results/gate.json', 'validation_evidence_sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(), 'scope': '10000s ideal observer empirical validation'}
    path.with_suffix('.lock.json').write_text(json.dumps(lock), encoding='utf-8')
    assert verify_freeze(path, tmp_path)['verified']
    gate['attack_passed'] = False
    evidence.write_text(json.dumps(gate), encoding='utf-8')
    with pytest.raises(ValueError, match='evidence changed'):
        verify_freeze(path, tmp_path)
    lock['validation_evidence_sha256'] = hashlib.sha256(evidence.read_bytes()).hexdigest()
    path.with_suffix('.lock.json').write_text(json.dumps(lock), encoding='utf-8')
    with pytest.raises(ValueError, match='gates or provenance'):
        verify_freeze(path, tmp_path)
