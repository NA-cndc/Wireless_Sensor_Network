from dataclasses import replace
import pytest
from wsn_sim.detection import ForwardingDetector
from wsn_sim.routing import RoutingEngine
from wsn_sim.simulation import Simulation

@pytest.mark.parametrize('forwarded', [False, True])
def test_probation_requires_observations_received_after_expiry(detector_config, forwarded):
    cfg = replace(detector_config, trust_threshold=0.7, consecutive_bad_windows=1, isolation_duration_s=6)
    detector = ForwardingDetector(cfg, ['relay'])
    detector.observe_received('relay', 'first', 'source', 0)
    detector.advance(5)
    assert detector.states['relay'].isolated_until == 11
    detector.observe_received('relay', 'old', 'source', 10)
    if forwarded:
        detector.observe_forwarded('relay', 'old', 10.1)
    detector.advance(15)
    state = detector.states['relay']
    assert state.probation
    assert not detector.is_isolated('relay', 15)
    assert state.trust == (0.75 if forwarded else 0.25)
    assert state.bad_windows == 0
    assert detector.windows[-1]['recovery_observations'] == 0
    detector.observe_received('relay', 'fresh', 'source', 15.1)
    if forwarded:
        detector.observe_forwarded('relay', 'fresh', 15.2)
    detector.advance(20)
    if forwarded:
        assert not state.probation
        assert state.trust == 0.875
        assert [row['time_s'] for row in detector.events if row['event'] == 'recovered'] == [20]
    else:
        assert detector.is_isolated('relay', 20)
        assert state.trust == 0.125

def test_failed_reroute_is_a_logged_decision_with_its_cause(network_factory, detector_config):
    net = network_factory({'s': (0, 0), 'h': (10, 0), 'a': (20, 0)}, [('s', 'h'), ('h', 'a'), ('a', 'k')], routing_algorithm='S_EMHR', detector=detector_config, bandwidth_bps=1024)
    simulation = Simulation(net.config, network=net)
    packet = simulation.traffic_gen.generate_packet('s')

    def fail():
        yield simulation.env.timeout(0.5)
        net.sensors['a'].consume_energy(4.5, simulation.env.now)
    simulation.env.process(fail())
    simulation.run_for(1.1)
    assert packet.status.value == 'NO_ROUTE'
    assert packet.actual_path == ['s', 'h']
    assert simulation.traffic_gen.reroutes == []
    decisions = simulation.traffic_gen.reroute_decisions
    assert len(decisions) == 1
    row = decisions[0]
    assert row['outcome'] == 'unreachable'
    assert row['reason'] == 'relay_energy' and row['reason_category'] == 'energy'
    assert row['trigger_nodes'] == ['a']
    assert row['route_after'] is None
    assert row['added_edge_count'] == row['removed_edge_count'] == 0

def test_emhr_does_not_mislabel_link_failure_as_security_avoidance(network_factory, detector_config):
    cfg = replace(detector_config, window_size_s=0.5, forwarding_timeout_s=0.1, consecutive_bad_windows=1)
    net = network_factory({'s': (0, 0), 'h': (10, 0), 'a': (20, 0), 'b': (20, 10)}, [('s', 'h'), ('h', 'a'), ('a', 'k'), ('h', 'b'), ('b', 'k')], routing_algorithm='EMHR', detector=cfg, bandwidth_bps=1024)
    simulation = Simulation(net.config, network=net)
    packet = simulation.traffic_gen.generate_packet('s')
    simulation.detector.observe_received('a', 'debug_observation', 's', 0)

    def fail():
        yield simulation.env.timeout(0.5)
        net.graph.remove_edge('h', 'a')
    simulation.env.process(fail())
    simulation.run_for(3.1)
    assert packet.status.value == 'DELIVERED'
    assert simulation.traffic_gen.reroutes[0]['reason'] == 'link_unavailable'
    assert simulation.traffic_gen.reroutes[0]['reason_category'] == 'link'

def test_reroute_prefers_current_sink_before_a_new_shorter_sink_among_seven(network_factory, detector_config):
    sinks = {f'k{index}': (100 + index * 20, 0) for index in range(7)}
    net = network_factory({'s': (0, 0), 'h': (10, 0), 'a': (20, 0), 'b': (20, 20)}, [('s', 'h'), ('h', 'a'), ('a', 'k0'), ('h', 'b'), ('b', 'k0')], sinks=sinks, routing_algorithm='S_EMHR', detector=detector_config, bandwidth_bps=1024)
    simulation = Simulation(net.config, network=net)
    packet = simulation.traffic_gen.generate_packet('s')

    def change():
        yield simulation.env.timeout(0.5)
        net.graph.remove_edge('h', 'a')
        net.graph.add_edge('h', 'k1')
    simulation.env.process(change())
    simulation.run_for(3.1)
    assert packet.actual_path == ['s', 'h', 'b', 'k0']
    row = simulation.traffic_gen.reroutes[0]
    assert not row['sink_changed']
    assert row['removed_edge_count'] == row['added_edge_count'] == 2
    assert len(row['removed_edges']) + len(row['added_edges']) == 4
    assert net.sensors['a'].is_alive and 'a' in net.graph

@pytest.mark.parametrize('cause', ['node_dead', 'relay_energy', 'isolation'])
def test_route_issue_names_the_relay_and_preserves_physical_graph(network_factory, detector_config, cause):
    cfg = replace(detector_config, consecutive_bad_windows=1)
    net = network_factory({'s': (0, 0), 'a': (10, 0), 'b': (10, 10)}, [('s', 'a'), ('a', 'k'), ('s', 'b'), ('b', 'k')], routing_algorithm='S_EMHR', detector=cfg)
    simulation = Simulation(net.config, network=net)
    edges = set(net.graph.edges)
    if cause == 'isolation':
        simulation.detector.observe_received('a', 'debug', 's', 0)
        simulation.detector.advance(5)
    else:
        net.sensors['a'].consume_energy(5 if cause == 'node_dead' else 4.5, 0)
    issues = simulation.router.route_issues(['s', 'a', 'k'], 's', 5)
    assert issues[0]['reason'] == cause and issues[0]['node_id'] == 'a'
    assert simulation.router.get_semhr_route('s', time_s=5) == ['s', 'b', 'k']
    assert set(net.graph.edges) == edges
    assert net.sensors['a'].is_alive == (cause != 'node_dead')

def test_isolated_source_can_send_own_traffic_but_not_relay_transit(network_factory, detector_config):
    cfg = replace(detector_config, consecutive_bad_windows=1)
    net = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')], routing_algorithm='S_EMHR', detector=cfg)
    simulation = Simulation(net.config, network=net)
    simulation.detector.observe_received('a', 'debug', 's', 0)
    simulation.run_for(5)
    assert simulation.router.get_semhr_route('s', time_s=5) is None
    assert simulation.router.get_semhr_route('a', time_s=5) == ['a', 'k']
    own = simulation.traffic_gen.generate_packet('a')
    simulation.run_for(0.1)
    assert own.status.value == 'DELIVERED'
    assert 'k' not in simulation.detector.states
    assert not simulation.detector.is_isolated('k', simulation.env.now)
    assert net.sensors['a'].is_alive

def test_secure_view_uses_the_same_emhr_order_without_isolation(network_factory, detector_config):
    net = network_factory({'s': (0, 0), 'a': (30, 0), 'b': (30, 5)}, [('s', 'a'), ('a', 'k'), ('s', 'b'), ('b', 'k')], routing_algorithm='S_EMHR', detector=detector_config)
    simulation = Simulation(net.config, network=net)
    router = RoutingEngine(net, simulation.detector)
    assert router.get_semhr_route('s') == router.get_emhr_route('s') == ['s', 'a', 'k']
