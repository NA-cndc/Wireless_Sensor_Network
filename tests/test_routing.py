from itertools import permutations
import networkx as nx
import pytest
from wsn_sim.routing import RoutingEngine

def test_mhr_uses_minimum_hops_and_stable_ids(network_factory):
    net = network_factory({'s': (0, 0), 'a': (50, 40), 'b': (50, 0)}, [('s', 'a'), ('a', 'k'), ('s', 'b'), ('b', 'k')])
    router = RoutingEngine(net)
    assert router.get_mhr_route('s') == ['s', 'a', 'k']
    net.graph.add_edge('s', 'k')
    assert router.get_mhr_route('s') == ['s', 'k']

def test_mhr_avoids_dead_nodes_without_emhr_threshold(network_factory):
    net = network_factory({'s': (0, 0), 'a': (50, 0)}, [('s', 'a'), ('a', 'k')])
    router = RoutingEngine(net)
    net.sensors['a'].consume_energy(4.9, 0)
    assert router.get_mhr_route('s') == ['s', 'a', 'k']
    assert router.get_emhr_route('s') is None
    net.sensors['a'].consume_energy(1, 0)
    assert router.get_mhr_route('s') is None

def test_emhr_hops_take_priority_over_distance_and_energy(network_factory):
    net = network_factory({'s': (0, 0), 'a': (50, 100), 'b': (30, 0), 'c': (60, 0)}, [('s', 'a'), ('a', 'k'), ('s', 'b'), ('b', 'c'), ('c', 'k')])
    net.sensors['a'].consume_energy(4, 0)
    assert RoutingEngine(net).get_emhr_route('s') == ['s', 'a', 'k']

def test_emhr_distance_takes_priority_over_energy(network_factory):
    net = network_factory({'s': (0, 0), 'a': (50, 0), 'b': (50, 50)}, [('s', 'a'), ('a', 'k'), ('s', 'b'), ('b', 'k')])
    net.sensors['a'].consume_energy(4, 0)
    assert RoutingEngine(net).get_emhr_route('s') == ['s', 'a', 'k']

def test_emhr_equal_distance_prefers_smaller_energy_penalty(network_factory):
    net = network_factory({'s': (0, 0), 'a': (50, 10), 'b': (50, -10)}, [('s', 'a'), ('a', 'k'), ('s', 'b'), ('b', 'k')])
    net.sensors['a'].consume_energy(3, 0)
    assert RoutingEngine(net).get_emhr_route('s') == ['s', 'b', 'k']

def test_emhr_energy_tie_is_not_lost_to_large_source_penalty(network_factory):
    net = network_factory({'s': (0, 0), 'a': (50, 10), 'b': (50, -10)}, [('s', 'a'), ('a', 'k'), ('s', 'b'), ('b', 'k')])
    net.sensors['s'].consume_energy(5 - 1e-09, 0)
    net.sensors['a'].consume_energy(1e-08, 0)
    assert RoutingEngine(net).get_emhr_route('s') == ['s', 'b', 'k']

def test_emhr_threshold_is_inclusive_and_source_has_own_packet_exception(network_factory):
    net = network_factory({'s': (0, 0), 'a': (50, 0)}, [('s', 'a'), ('a', 'k')])
    net.sensors['s'].consume_energy(4.9, 0)
    net.sensors['a'].consume_energy(4, 0)
    router = RoutingEngine(net)
    assert router.get_emhr_route('s') == ['s', 'a', 'k']
    net.sensors['a'].consume_energy(0.001, 0)
    assert router.get_emhr_route('s') is None
    assert router.find_route('a', packet_source_id='s') is None
    assert router.get_emhr_route('a') == ['a', 'k']
    net.sensors['s'].consume_energy(1, 0)
    assert router.get_mhr_route('s') is None
    assert router.get_emhr_route('missing') is None

def test_sink_cannot_be_used_as_a_relay(network_factory):
    net = network_factory({'s': (0, 0)}, [('s', 'k1'), ('k1', 'k2')], sinks={'k1': (10, 0), 'k2': (20, 0)})
    router = RoutingEngine(net)
    assert router.get_emhr_route('s') == ['s', 'k1']
    assert router.find_route('s', target_sink='k2') is None
    assert not router.route_is_valid(['s', 'k1', 'k2'], 's', 0)

@pytest.mark.parametrize('reverse', [False, True])
def test_route_tie_break_does_not_depend_on_graph_insertion(network_factory, reverse):
    edges = [('s', 'b'), ('b', 'k'), ('s', 'a'), ('a', 'k')]
    net = network_factory({'s': (0, 0), 'b': (50, -10), 'a': (50, 10)}, list(reversed(edges)) if reverse else edges)
    assert RoutingEngine(net).get_emhr_route('s') == ['s', 'a', 'k']

def test_emhr_matches_exhaustive_oracle_on_small_graph(network_factory):
    net = network_factory({'s': (0, 0), 'a': (20, 40), 'b': (40, 0), 'c': (60, 20)}, [('s', 'a'), ('s', 'b'), ('a', 'b'), ('a', 'c'), ('b', 'c'), ('c', 'k'), ('b', 'k')])
    for energies in permutations((0.5, 1.0, 5.0)):
        for node, energy in zip(('a', 'b', 'c'), energies):
            net.sensors[node].energy_j = energy
        paths = [path for path in nx.all_simple_paths(net.graph, 's', 'k') if all((net.sensors[node].energy_j >= net.config.energy_threshold_j for node in path[1:-1]))]

        def cost(path):
            return (len(path) - 1, sum((net.distance(a, b) for a, b in zip(path, path[1:]))), sum((net.config.initial_energy_j / (net.sensors[node].energy_j + net.config.energy_epsilon_j) for node in path[:-1])), tuple(path))
        expected = min(paths, key=cost) if paths else None
        assert RoutingEngine(net).get_emhr_route('s') == expected
