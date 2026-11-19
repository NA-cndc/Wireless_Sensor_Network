from dataclasses import replace
import pytest
from wsn_sim.models import Packet, PacketStatus
from wsn_sim.simulation import Simulation

@pytest.mark.parametrize('change', ['isolation', 'link', 'energy', 'sink_switch', 'no_route'])
def test_in_flight_packet_reroutes_from_current_holder_without_loops(network_factory, detector_config, change):
    cfg = replace(detector_config, beta_trust=0.2, window_size_s=0.5, forwarding_timeout_s=0.1, consecutive_bad_windows=1, isolation_duration_s=20)
    sinks = {'k0': (100, 0), 'k1': (100, 40)}
    edges = [('s', 'h'), ('h', 'a'), ('a', 'k0')]
    if change != 'no_route':
        edges += [('h', 'b'), ('b', 'k1' if change == 'sink_switch' else 'k0')]
    net = network_factory({'s': (0, 0), 'h': (10, 0), 'a': (40, 0), 'b': (40, 40)}, edges, sinks=sinks, routing_algorithm='S_EMHR', detector=cfg, bandwidth_bps=1024)
    simulation = Simulation(net.config, network=net)
    initial_route = simulation.router.get_semhr_route('s')
    assert initial_route == ['s', 'h', 'a', 'k0']
    packet = simulation.traffic_gen.generate_packet('s')
    if change in {'isolation', 'sink_switch', 'no_route'}:
        simulation.detector.observe_received('a', 'observed_transit', 's', 0)
    else:

        def alter_network():
            yield simulation.env.timeout(0.5)
            if change == 'link':
                net.graph.remove_edge('h', 'a')
            else:
                net.sensors['a'].consume_energy(4.1, float(simulation.env.now))
        simulation.env.process(alter_network())
    simulation.run_for(3.1)
    assert packet.packet_id == 's_p1'
    assert packet.created_at == 0
    assert len(packet.actual_path) == len(set(packet.actual_path))
    if change == 'no_route':
        assert packet.status is PacketStatus.NO_ROUTE
        assert packet.actual_path == ['s', 'h']
        assert packet.actual_hop_count == 1
        assert packet.drop_reason == 'unreachable'
    else:
        expected_sink = 'k1' if change == 'sink_switch' else 'k0'
        assert packet.actual_path == ['s', 'h', 'b', expected_sink]
        assert packet.status is PacketStatus.DELIVERED
        assert packet.delivered_at == 3
        assert len(simulation.traffic_gen.reroutes) == 1
        record = simulation.traffic_gen.reroutes[0]
        assert record['node_id'] == 'h'
        assert record['time_s'] == 1
        assert record['route_before'] == initial_route
        assert record['route_after'] == packet.actual_path
    assert net.sensors['a'].is_alive
    assert 'a' in net.graph
    if change in {'isolation', 'sink_switch', 'no_route'}:
        assert simulation.detector.is_isolated('a', simulation.env.now)
        assert net.graph.has_edge('h', 'a')

def test_relay_cannot_use_own_packet_energy_exception_while_rerouting(network_factory):
    net = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')])
    simulation = Simulation(net.config, network=net)
    packet = Packet('p', 's', 0, 128)
    packet.assign_route(['s', 'a', 'k'])
    packet.advance_to('a')
    net.sensors['a'].consume_energy(4.5, 0)
    simulation.traffic_gen.generated_packets.append(packet)
    simulation.env.process(simulation.traffic_gen._transmit_packet(packet))
    simulation.run_for(0.1)
    assert packet.status is PacketStatus.NO_ROUTE
    assert packet.actual_path == ['s', 'a']
    assert simulation.router.get_emhr_route('a') == ['a', 'k']

def test_packet_reroute_does_not_rewind_actual_path_or_allow_terminal_reuse():
    packet = Packet('p', 's', 0, 128)
    packet.assign_route(['s', 'a', 'k'])
    packet.advance_to('a')
    with pytest.raises(ValueError, match='revisit'):
        packet.assign_route(['a', 's', 'k'])
    packet.assign_route(['a', 'b', 'k2'])
    assert packet.route == ['s', 'a', 'b', 'k2']
    assert packet.actual_path == ['s', 'a']
    assert packet.mark_dropped('unreachable')
    assert not packet.mark_dropped('selective_forwarding')
    assert not packet.mark_delivered(2)
    assert packet.drop_reason == 'unreachable'
    with pytest.raises(ValueError, match='terminal'):
        packet.assign_route(['a', 'k'])
    with pytest.raises(ValueError, match='transit'):
        packet.advance_to('b')
