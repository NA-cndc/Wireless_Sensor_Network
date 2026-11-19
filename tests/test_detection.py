from dataclasses import replace
import pytest
from wsn_sim.detection import ForwardingDetector, benign_calibration_profile

def test_fr_ewma_and_consecutive_bad_windows_match_hand_calculation(detector_config):
    detector = ForwardingDetector(detector_config, ['a'])
    detector.observe_received('a', 'p1', 's', 0.1)
    detector.observe_forwarded('a', 'p1', 0.2)
    detector.observe_received('a', 'p2', 's', 0.3)
    detector.advance(5)
    first = detector.windows[-1]
    assert (first['observations'], first['forwarded'], first['failed_timeout']) == (2, 1, 1)
    assert first['forwarding_ratio'] == 0.5
    assert first['trust'] == 0.75
    assert not detector.is_isolated('a', 5)
    detector.observe_received('a', 'p3', 's', 5.1)
    detector.advance(10)
    assert detector.states['a'].trust == 0.375
    assert detector.states['a'].suspected_at == 5
    assert detector.states['a'].isolated_at == 10
    assert detector.is_isolated('a', 10)

def test_pending_across_window_boundary_does_not_count_as_failed(detector_config):
    detector = ForwardingDetector(detector_config, ['a'])
    detector.observe_received('a', 'p', 's', 4.5)
    detector.advance(5)
    assert detector.windows[-1]['status'] == 'insufficient_data'
    assert detector.windows[-1]['observations'] == 0
    assert detector.states['a'].trust == 1
    assert len(detector.pending) == 1
    detector.observe_forwarded('a', 'p', 5.1)
    detector.advance(10)
    assert detector.windows[-1]['forwarding_ratio'] == 1
    assert detector.states['a'].failed == 0

def test_duplicate_own_sink_and_unmatched_forwarding_are_ignored(detector_config):
    detector = ForwardingDetector(detector_config, ['a'])
    detector.observe_received('a', 'own', 'a', 0)
    detector.observe_received('sink', 'p', 's', 0)
    detector.observe_forwarded('a', 'unknown', 0)
    detector.observe_received('a', 'p', 's', 0.1)
    detector.observe_received('a', 'p', 's', 0.2)
    detector.observe_forwarded('a', 'p', 0.3)
    detector.observe_forwarded('a', 'p', 0.4)
    detector.observe_received('a', 'p', 's', 0.5)
    detector.advance(5)
    state = detector.states['a']
    assert (state.received, state.forwarded, state.failed) == (1, 1, 0)
    assert detector.windows[-1]['observations'] == 1

def test_timeout_is_once_and_late_forwarding_cannot_rewrite_it(detector_config):
    detector = ForwardingDetector(detector_config, ['a'])
    detector.observe_received('a', 'p', 's', 1)
    detector.observe_forwarded('a', 'p', 2)
    detector.observe_forwarded('a', 'p', 3)
    detector.advance(5)
    assert detector.states['a'].failed == 1
    assert detector.states['a'].forwarded == 0
    timeouts = [row for row in detector.events if row['event'] == 'timeout']
    assert len(timeouts) == 1
    assert timeouts[0]['time_s'] == 2

def test_outcomes_at_boundary_belong_to_next_half_open_window(detector_config):
    detector = ForwardingDetector(detector_config, ['a'])
    detector.observe_received('a', 'p', 's', 4)
    detector.advance(5)
    assert detector.windows[-1]['observations'] == 0
    assert detector.windows[-1]['pending_total'] == 0
    assert detector.states['a'].failed_timeout == 1
    detector.advance(10)
    assert detector.windows[-1]['failed_timeout'] == 1

def test_empty_and_insufficient_windows_preserve_trust(detector_config):
    detector = ForwardingDetector(replace(detector_config, min_observations=2, initial_trust=0.9), ['a'])
    detector.observe_received('a', 'p', 's', 0)
    detector.advance(15)
    assert all((row['status'] == 'insufficient_data' for row in detector.windows))
    assert detector.states['a'].trust == 0.9
    assert detector.states['a'].valid_windows == 0
    assert not detector.is_isolated('a', 15)

def test_good_window_breaks_consecutive_bad_run(detector_config):
    detector = ForwardingDetector(replace(detector_config, trust_threshold=0.6), ['a'])
    detector.observe_received('a', 'p1', 's', 0)
    detector.advance(5)
    assert detector.states['a'].bad_windows == 1
    detector.observe_received('a', 'p2', 's', 5.1)
    detector.observe_forwarded('a', 'p2', 5.2)
    detector.advance(10)
    assert detector.states['a'].bad_windows == 0
    detector.observe_received('a', 'p3', 's', 10.1)
    detector.advance(15)
    assert detector.states['a'].bad_windows == 1
    assert not detector.is_isolated('a', 15)

def test_isolation_expires_into_probation_without_resetting_trust(detector_config):
    cfg = replace(detector_config, consecutive_bad_windows=1)
    detector = ForwardingDetector(cfg, ['a'])
    detector.observe_received('a', 'p1', 's', 0)
    detector.advance(5)
    assert detector.is_isolated('a', 5)
    detector.advance(15)
    assert not detector.is_isolated('a', 15)
    assert detector.states['a'].probation
    assert detector.states['a'].trust == 0.5
    detector.observe_received('a', 'p2', 's', 15.1)
    detector.advance(20)
    assert detector.is_isolated('a', 20)
    assert detector.states['a'].isolated_at == 5
    assert len([row for row in detector.events if row['event'] == 'isolated']) == 2

def test_insufficient_window_does_not_count_or_reset_a_bad_valid_window(detector_config):
    detector = ForwardingDetector(detector_config, ['a'])
    detector.observe_received('a', 'p1', 's', 0)
    detector.advance(10)
    assert detector.states['a'].bad_windows == 1
    assert not detector.is_isolated('a', 10)
    detector.observe_received('a', 'p2', 's', 10.1)
    detector.advance(15)
    assert detector.is_isolated('a', 15)

def test_benign_profile_does_not_claim_calibration(detector_config):
    detector = ForwardingDetector(detector_config, ['a'])
    detector.observe_received('a', 'p', 's', 0)
    detector.observe_forwarded('a', 'p', 0.1)
    detector.advance(5)
    profile = benign_calibration_profile(detector.windows)
    assert profile['valid_windows'] == 1
    assert profile['minimum_trust'] == 1
    assert profile['calibration_status'] == 'NEEDS_CALIBRATION'

def test_observer_accepts_only_behavior_events(detector_config):
    detector = ForwardingDetector(detector_config, ['a'])
    assert not hasattr(detector, 'attacker_ids')
    assert not hasattr(detector, 'p_drop')
    detector.advance(5)
    with pytest.raises(ValueError, match='monotonic'):
        detector.observe_received('a', 'p', 's', 4)
