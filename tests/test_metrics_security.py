from dataclasses import replace
import pytest
from wsn_sim.detection import ForwardingDetector
from wsn_sim.metrics import LifetimeTracker, security_metrics
from wsn_sim.simulation import Simulation

def test_confusion_matrix_keeps_unobserved_attackers_in_denominator(detector_config):
    detector = ForwardingDetector(replace(detector_config, consecutive_bad_windows=1), ['a', 'b', 'c', 'd'])
    detector.observe_received('a', 'p1', 's', 0)
    detector.observe_received('b', 'p2', 's', 0)
    detector.observe_received('c', 'p3', 's', 0)
    detector.observe_forwarded('c', 'p3', 0.1)
    result = security_metrics(['a', 'b', 'c', 'd'], ['a', 'd'], detector, 5)
    assert [result[name] for name in ('TP', 'FP', 'TN', 'FN')] == [1, 1, 1, 1]
    assert [result[name] for name in ('tpr', 'recall', 'fpr', 'precision', 'f1')] == [0.5] * 5
    assert result['coverage'] == 0.75
    assert result['attacker_delays']['a']['detection_delay_s'] == 5
    assert result['attacker_delays']['d']['detection_delay_s'] is None
    assert result['attacker_delays']['d']['detection_na_reason'] == 'not_detected'

def test_zero_denominators_are_na_with_reasons(detector_config, network_factory):
    detector = ForwardingDetector(detector_config, ['a'])
    result = security_metrics(['a'], [], detector, 0)
    assert result['tpr'] is None
    assert result['precision'] is None
    assert result['f1'] is None
    assert result['na_reasons']['precision'] == 'zero_denominator'
    net = network_factory({'s': (0, 0)}, [('s', 'k')])
    metrics = Simulation(net.config, network=net).summary()['performance']
    assert metrics['pdr'] is None
    assert metrics['mean_latency_s'] is None
    assert metrics['energy_per_payload_bit_j'] is None
    assert metrics['na_reasons']['pdr'] == 'no_generated_packets'

def test_performance_metrics_match_a_single_known_delivery(network_factory):
    net = network_factory({'s': (0, 0)}, [('s', 'k')], sinks={'k': (10, 0)})
    simulation = Simulation(net.config, network=net)
    simulation.run_for(11)
    metrics = simulation.summary()['performance']
    assert metrics['pdr'] == 1
    assert metrics['throughput_bps'] == pytest.approx(1024 / 11)
    assert metrics['goodput_bps'] == metrics['throughput_bps']
    assert metrics['mean_actual_hops'] == 1
    assert metrics['mean_latency_s'] == pytest.approx(1024 / 250000)
    consumed = simulation.radio.compute_tx_energy(1024, 10)
    assert metrics['consumed_energy_j'] == pytest.approx(consumed)
    assert metrics['energy_per_payload_bit_j'] == pytest.approx(consumed / 1024)
    assert metrics['control_packets'] is None
    assert simulation.summary()['lifetime']['FND']['censored']
    assert simulation.summary()['lifetime']['FND']['time_s'] is None

def test_explicit_wire_size_is_distinct_from_payload_without_inventing_headers(network_factory):
    net = network_factory({'s': (0, 0)}, [('s', 'k')], wire_size_bytes=160)
    simulation = Simulation(net.config, network=net)
    simulation.run_for(11)
    metrics = simulation.summary()['performance']
    assert metrics['throughput_bps'] == pytest.approx(1280 / 11)
    assert metrics['goodput_bps'] == pytest.approx(1024 / 11)
    assert metrics['mean_latency_s'] == pytest.approx(1280 / 250000)

def test_lifetime_milestones_track_payload_received_at_each_death(network_factory):
    net = network_factory({node: (index * 10, 0) for index, node in enumerate('abcd')})
    tracker = LifetimeTracker(net)
    tracker.observe(0, 0)
    for index, node in enumerate('abcd', 1):
        net.sensors[node].consume_energy(5, index)
        tracker.observe(index, 1024 * index)
    assert tracker.milestones['FND'] == {'time_s': 1, 'censored': False, 'received_payload_bits': 1024}
    assert tracker.milestones['HND']['time_s'] == 2
    assert tracker.milestones['LND']['time_s'] == 4
    assert tracker.milestones['LND']['received_payload_bits'] == 4096
    assert tracker.milestones['functional_network_death']['time_s'] is None
    assert tracker.reachability['status'] == 'no_alive_sensors'
    assert tracker.reachability['physical_reachable_ratio'] is None

def test_functional_network_death_is_separate_from_battery_death(network_factory):
    net = network_factory({'a': (0, 0), 'b': (1000, 0), 'c': (1000, 1000)}, [('a', 'k')])
    simulation = Simulation(net.config, network=net)
    lifetime = simulation.summary()['lifetime']
    assert lifetime['functional_network_death']['time_s'] == 0
    assert lifetime['FND']['time_s'] is None
    assert lifetime['HND']['censored']

def test_no_live_sensors_is_handled_without_division_by_zero(network_factory):
    net = network_factory({'s': (0, 0)}, [])
    net.sensors['s'].consume_energy(5, 0)
    simulation = Simulation(net.config, network=net)
    assert simulation.run_for(20) == 0
    assert simulation.summary()['lifetime']['functional_network_death']['time_s'] is None
    assert simulation.summary()['reachability']['status'] == 'no_alive_sensors'
    assert simulation.summary()['stop_reason'] == 'LND'
