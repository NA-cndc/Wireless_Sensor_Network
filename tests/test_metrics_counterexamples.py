from dataclasses import replace
from wsn_sim.detection import ForwardingDetector
from wsn_sim.metrics import LifetimeTracker, security_metrics

def test_death_at_three_is_not_replaced_by_poll_at_ten(network_factory):
    network = network_factory({'s': (0, 0)}, [('s', 'k')])
    tracker = LifetimeTracker(network)
    tracker.observe(0, 0)
    network.sensors['s'].consume_energy(5, 3)
    tracker.observe(10, 1024)
    assert tracker.milestones['FND']['time_s'] == 3
    assert tracker.milestones['FND']['received_payload_bits'] is None
    assert tracker.reachability['status'] == 'no_alive_sensors'

def test_historical_cutoff_does_not_rewind_detector_clock(detector_config):
    detector = ForwardingDetector(replace(detector_config, consecutive_bad_windows=1), ['relay'])
    detector.observe_received('relay', 'p', 'source', 5.1)
    detector.advance(10)
    result = security_metrics(['relay'], ['relay'], detector, 5)
    assert result['TP'] == 0 and result['FN'] == 1
