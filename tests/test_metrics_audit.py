from dataclasses import replace
import pytest
from wsn_sim.detection import ForwardingDetector
from wsn_sim.metrics import packet_event_metrics, security_metrics
from wsn_sim.simulation import Simulation

def test_historical_security_cutoff_uses_only_observations_and_predictions_before_cutoff(detector_config):
    cfg = replace(detector_config, consecutive_bad_windows=1)
    detector = ForwardingDetector(cfg, ['a', 'b', 'unobserved'])
    detector.observe_received('b', 'good', 'source', 0)
    detector.observe_forwarded('b', 'good', 0.1)
    detector.observe_received('a', 'bad', 'source', 5.1)
    detector.advance(10)
    before = detector.summary()
    result = security_metrics(['a', 'b', 'unobserved'], ['a', 'unobserved'], detector, 5)
    assert (result['TP'], result['FP'], result['TN'], result['FN']) == (0, 0, 1, 2)
    assert result['coverage'] == pytest.approx(1 / 3)
    assert result['conditional_on_observable']['population_ids'] == ['b']
    assert result['conditional_on_observable']['tpr'] is None
    assert detector.summary() == before
    later = security_metrics(['a', 'b', 'unobserved'], ['a', 'unobserved'], detector, 10, attack_start_time_s=2)
    assert later['attacker_delays']['a']['detection_delay_s'] == 8
    assert later['attacker_delays']['a']['isolation_delay_s'] == 8
    assert later['attacker_delays']['unobserved']['detection_censored']
    assert later['attacker_delays']['unobserved']['detection_delay_s'] is None

def test_security_formulas_match_non_symmetric_hand_matrix(detector_config):
    detector = ForwardingDetector(replace(detector_config, consecutive_bad_windows=1), list('abcdefgh'))
    for node in 'abef':
        detector.observe_received(node, node, 'source', 0)
    detector.observe_forwarded('f', 'f', 0.1)
    result = security_metrics(list('abcdefgh'), list('abcd'), detector, 5)
    assert (result['TP'], result['FP'], result['TN'], result['FN']) == (2, 1, 3, 2)
    assert result['tpr'] == result['recall'] == 0.5
    assert result['fpr'] == 0.25
    assert result['precision'] == pytest.approx(2 / 3)
    assert result['f1'] == pytest.approx(4 / 7)
    assert result['population_size'] == 8 and result['coverage'] == 0.5
    conditional = result['conditional_on_observable']
    assert (conditional['TP'], conditional['FP'], conditional['TN'], conditional['FN']) == (2, 1, 1, 0)
    assert conditional['population_size'] == 4

def test_security_subset_never_counts_predictions_outside_its_population(detector_config):
    detector = ForwardingDetector(detector_config, ['inside', 'outside'])
    detector.observe_received('outside', 'p', 'source', 0)
    detector.advance(5)
    result = security_metrics(['inside'], [], detector, 5)
    assert (result['TP'], result['FP'], result['TN'], result['FN']) == (0, 0, 1, 0)
    assert result['conditional_on_observable']['population_size'] == 0
    assert result['conditional_on_observable']['fpr'] is None
    with pytest.raises(ValueError, match='population'):
        security_metrics(['missing'], [], detector, 5)

def test_delay_origin_never_clamps_pre_attack_alarm_to_zero(detector_config):
    detector = ForwardingDetector(detector_config, ['relay'])
    detector.observe_received('relay', 'p', 'source', 0)
    detector.advance(10)
    result = security_metrics(['relay'], ['relay'], detector, 10, attack_start_time_s=6)
    delay = result['attacker_delays']['relay']
    assert delay['pre_origin_suspected_at_s'] == 5
    assert delay['detection_delay_s'] is None
    assert delay['detection_censored']
    assert delay['detection_na_reason'] == 'no_post_origin_detection'
    assert delay['at_risk_duration_s'] == 4

def test_first_transit_origin_reports_no_opportunity_without_removing_FN(detector_config):
    detector = ForwardingDetector(detector_config, ['relay', 'silent'])
    detector.observe_received('relay', 'p', 'source', 2)
    result = security_metrics(['relay', 'silent'], ['relay', 'silent'], detector, 5, delay_origin='first_transit_rx')
    assert result['FN'] == 1
    assert result['attacker_delays']['relay']['detection_delay_s'] == 3
    assert result['attacker_delays']['silent']['delay_origin_s'] is None
    assert result['attacker_delays']['silent']['detection_na_reason'] == 'no_transit_opportunity'

def test_raw_packet_events_deduplicate_sink_delivery_and_preserve_in_flight():
    events = [{'time_s': 0, 'event': 'created', 'packet_id': 'p1', 'payload_size_bytes': 128, 'wire_size_bytes': 160}, {'time_s': 0, 'event': 'tx', 'packet_id': 'p1', 'node_id': 's'}, {'time_s': 0.1, 'event': 'rx', 'packet_id': 'p1', 'node_id': 'r'}, {'time_s': 0.1, 'event': 'tx', 'packet_id': 'p1', 'node_id': 'r'}, {'time_s': 0.2, 'event': 'rx', 'packet_id': 'p1', 'node_id': 'k'}, {'time_s': 0.2, 'event': 'rx', 'packet_id': 'p1', 'node_id': 'k'}, {'time_s': 0.2, 'event': 'delivered', 'packet_id': 'p1'}, {'time_s': 0.2, 'event': 'delivered', 'packet_id': 'p1'}, {'time_s': 0.3, 'event': 'created', 'packet_id': 'p2', 'payload_size_bytes': 128, 'wire_size_bytes': 128}, {'time_s': 0.3, 'event': 'reroute_failed', 'packet_id': 'p2', 'reason': 'isolation', 'reason_category': 'security'}, {'time_s': 0.3, 'event': 'dropped', 'packet_id': 'p2', 'reason': 'unreachable'}, {'time_s': 0.4, 'event': 'created', 'packet_id': 'p3', 'payload_size_bytes': 128, 'wire_size_bytes': 128}, {'time_s': 0.4, 'event': 'rerouted', 'packet_id': 'p3', 'reason': 'link_unavailable', 'reason_category': 'link', 'added_edge_count': 2, 'removed_edge_count': 2}, {'time_s': 0.4, 'event': 'tx', 'packet_id': 'p3', 'node_id': 's'}]
    result = packet_event_metrics(events, 1)
    assert (result['generated'], result['delivered'], result['dropped'], result['pending_in_flight']) == (3, 1, 1, 1)
    assert result['conservation_ok']
    assert result['duplicate_delivery_events'] == 1
    assert result['received_unique_at_sink'] == 1
    assert result['pdr'] == pytest.approx(1 / 3)
    assert result['received_payload_bits'] == 1024 and result['received_wire_bits'] == 1280
    assert result['goodput_bps'] == 1024 and result['throughput_bps'] == 1280
    assert result['mean_actual_hops'] == 2 and result['mean_latency_s'] == 0.2
    assert result['reroute_count'] == 1 and result['reroute_decision_count'] == 2
    assert result['reroute_failed_count'] == 1
    assert result['route_edges_changed'] == 4

def test_raw_packet_events_reject_orphan_or_conflicting_terminal_records():
    with pytest.raises(ValueError, match='creation'):
        packet_event_metrics([{'time_s': 1, 'packet_id': 'p', 'event': 'delivered'}], 2)
    rows = [{'time_s': 0, 'packet_id': 'p', 'event': 'created', 'payload_size_bytes': 128, 'wire_size_bytes': 128}, {'time_s': 1, 'packet_id': 'p', 'event': 'delivered'}, {'time_s': 2, 'packet_id': 'p', 'event': 'dropped', 'reason': 'natural_link_loss'}]
    with pytest.raises(ValueError, match='terminal'):
        packet_event_metrics(rows, 3)

def test_energy_per_bit_uses_run_depletion_and_reconciles_raw_energy_events(network_factory):
    net = network_factory({'s': (0, 0)}, [('s', 'k')], sinks={'k': (10, 0)}, wire_size_bytes=160)
    net.sensors['s'].consume_energy(0.5, 0)
    simulation = Simulation(net.config, network=net)
    simulation.traffic_gen.generate_packet('s')
    simulation.run_for(0.1)
    performance = simulation.summary()['performance']
    expected = 1280 * (5e-08 + 1e-11 * 10 ** 2)
    assert performance['pre_simulation_depletion_j'] == 0.5
    assert performance['consumed_since_start_j'] == pytest.approx(expected)
    assert performance['radio_energy_j'] == pytest.approx(expected)
    assert performance['energy_from_events_j'] == pytest.approx(expected)
    assert performance['energy_per_payload_bit_j'] == pytest.approx(expected / 1024)
    assert performance['energy_conservation_ok']
    assert sum((row['consumed_j'] for row in simulation.energy_events)) == pytest.approx(expected)
    assert performance['control_packets'] is None
    assert performance['routing_overhead']['control_packets'] is None
    assert performance['security_overhead']['monitoring_energy_j'] is None

def test_external_energy_events_stop_simulation_at_real_LND_and_keep_payload_prefix(network_factory):
    net = network_factory({'a': (0, 0), 'b': (0, 10)}, [('a', 'k'), ('b', 'k')], sinks={'k': (10, 0)})
    simulation = Simulation(net.config, network=net)
    simulation.traffic_gen.generate_packet('a')

    def deaths():
        yield simulation.env.timeout(2)
        net.sensors['a'].consume_energy(5, simulation.env.now)
        yield simulation.env.timeout(2)
        net.sensors['b'].consume_energy(5, simulation.env.now)
    simulation.env.process(deaths())
    assert simulation.run_for(5) == 4
    summary = simulation.summary()
    assert summary['stop_reason'] == 'LND'
    assert summary['lifetime']['FND'] == {'time_s': 2, 'censored': False, 'received_payload_bits': 1024}
    assert summary['lifetime']['HND']['time_s'] == 2
    assert summary['lifetime']['LND']['time_s'] == 4
    assert summary['reachability']['status'] == 'no_alive_sensors'
    assert summary['lifetime']['functional_network_death']['time_s'] is None

def test_link_change_updates_functional_death_without_battery_death(network_factory):
    net = network_factory({'s': (0, 0), 'r': (10, 0), 't': (0, 10)}, [('s', 'r'), ('t', 'r'), ('r', 'k')])
    simulation = Simulation(net.config, network=net)

    def disconnect():
        yield simulation.env.timeout(0.5)
        simulation.set_link_state('r', 'k', available=False)
        yield simulation.env.timeout(0.5)
        simulation.set_link_state('r', 'k', available=True)
    simulation.env.process(disconnect())
    simulation.run_for(1.1)
    summary = simulation.summary()
    assert summary['lifetime']['functional_network_death']['time_s'] == 0.5
    assert summary['lifetime']['FND']['time_s'] is None
    assert summary['reachability']['physical_reachable_alive'] == 3
    assert [row['time_s'] for row in simulation.network_events] == [0.5, 1]

def test_secure_reachability_changes_at_isolation_and_exact_expiry_without_energy_change(network_factory, detector_config):
    cfg = replace(detector_config, window_size_s=1, forwarding_timeout_s=0.1, consecutive_bad_windows=1, isolation_duration_s=1.5)
    net = network_factory({'s': (0, 0), 'r': (10, 0), 't': (0, 10)}, [('s', 'r'), ('t', 'r'), ('r', 'k')], routing_algorithm='S_EMHR', detector=cfg)
    simulation = Simulation(net.config, network=net)
    simulation.detector.observe_received('r', 'debug_observable_transit', 's', 0)
    simulation.run_for(1.1)
    summary = simulation.summary()
    assert summary['reachability']['physical_reachable_alive'] == 3
    assert summary['reachability']['routing_reachable_alive'] == 1
    assert summary['lifetime']['functional_routing_network_death']['time_s'] == 1
    assert summary['lifetime']['functional_network_death']['time_s'] is None
    simulation.run_for(1.5)
    assert simulation.detector.states['r'].probation
    assert simulation.summary()['reachability']['routing_reachable_alive'] == 3
    assert any((row['time_s'] == 2.5 and row['routing_reachable_alive'] == 3 for row in simulation.lifetime.reachability_events))

@pytest.mark.parametrize('death_first,expected_payload', [(True, 0), (False, 1024)])
def test_same_timestamp_payload_at_death_follows_actual_simpy_event_order(network_factory, death_first, expected_payload):
    net = network_factory({'a': (0, 0), 'b': (0, 10)}, [('a', 'k')], sinks={'k': (10, 0)}, bandwidth_bps=1024)
    simulation = Simulation(net.config, network=net)

    def death():
        yield simulation.env.timeout(1)
        net.sensors['b'].consume_energy(5, simulation.env.now)
    if death_first:
        simulation.env.process(death())
    simulation.traffic_gen.generate_packet('a')
    if not death_first:
        simulation.env.process(death())
    simulation.run_for(1.1)
    assert simulation.summary()['lifetime']['FND']['time_s'] == 1
    assert simulation.summary()['lifetime']['FND']['received_payload_bits'] == expected_payload

def test_max_round_boundary_keeps_packet_in_flight_and_lifetime_censored(network_factory):
    net = network_factory({'s': (0, 0)}, [('s', 'k')], max_rounds=2)
    simulation = Simulation(net.config, network=net)
    simulation.run_for(100)
    summary = simulation.summary()
    assert summary['stop_reason'] == 'max_rounds' and summary['time_s'] == 20
    assert summary['performance']['generated'] == 2
    assert summary['performance']['delivered'] == 1
    assert summary['performance']['pending_in_flight'] == 1
    for name in ('FND', 'HND', 'LND'):
        assert summary['lifetime'][name]['censored']
        assert summary['lifetime'][name]['time_s'] is None
    assert summary['lifetime_metadata']['censoring_reason'] == 'max_rounds'
