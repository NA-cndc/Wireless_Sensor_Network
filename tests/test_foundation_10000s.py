"""Contract tests for routing, the simulation boundary, and conservation."""

from dataclasses import replace
from math import hypot

import networkx as nx
import pytest

from analysis.foundation.config import SimulationConfig
from analysis.foundation.models.packet import PacketStatus
from analysis.foundation.network import Network
from analysis.foundation.routing import RoutingEngine
from analysis.foundation.runner import CONFIG_PATH
from analysis.foundation.simulation import Simulation


@pytest.fixture(scope="module")
def config():
    return SimulationConfig.from_json(CONFIG_PATH)


def small_network(config, count, edges):
    network = Network(replace(config, num_sensors=count, num_sinks=1))
    network.graph.remove_edges_from(list(network.graph.edges))
    for left, right, distance in edges:
        network.graph.add_edge(left, right, distance_m=distance)
    return network


@pytest.mark.parametrize("radius", [250, 300, 350])
def test_mhr_matches_virtual_super_sink(config, radius):
    network = Network(config, radius)
    graph = network.graph.copy()
    graph.add_edges_from((sink, "virtual") for sink in network.sinks)
    expected = nx.single_source_shortest_path_length(graph, "virtual")
    router = RoutingEngine(network)
    assert not network.graph.is_directed()
    assert set(network.routable_sensor_ids()) == set(network.sensors) & expected.keys()
    for source in network.sensors:
        route = router.get_mhr_route(source)
        if source not in expected:
            assert route is None
        else:
            assert route[-1] in network.sinks
            assert len(route) == expected[source]
            for a, b in zip(route, route[1:]):
                assert network.graph.has_edge(a, b)
                left, right = network.graph.nodes[a], network.graph.nodes[b]
                assert hypot(left["x"] - right["x"], left["y"] - right["y"]) <= radius
    other = Network(replace(config, seed=config.seed + 1), radius)
    assert all(other.coordinates()[sink] != network.coordinates()[sink] for sink in network.sinks)


def test_emhr_threshold_priority_and_no_fallback(config):
    source, short, long, sink = "sensor_000", "sensor_001", "sensor_002", "sink_00"
    net = small_network(config, 3, [(source, short, 10), (short, sink, 10),
                                    (source, long, 20), (long, sink, 20)])
    router = RoutingEngine(net)
    net.sensors[source].energy_j = 0.2
    net.sensors[short].energy_j = 0.5
    assert router.get_emhr_route(source) == [source, long, sink]
    net.sensors[long].energy_j = 0.5
    assert router.get_emhr_route(source) is None
    net.sensors[short].energy_j = 1
    net.sensors[long].energy_j = 4
    assert router.get_emhr_route(source) == [source, short, sink]
    net.graph[long][sink]["distance_m"] = 10
    net.graph[source][long]["distance_m"] = 10
    assert router.get_emhr_route(source) == [source, long, sink]
    net.graph.add_edge(source, sink, distance_m=200)
    assert router.get_emhr_route(source) == [source, sink]


@pytest.mark.parametrize("algorithm", ["MHR", "EMHR"])
def test_default_run_reaches_exact_limit_and_generates_for_disconnected(config, algorithm):
    net = small_network(replace(config, channel_loss_probability=0), 3, [("sensor_000", "sink_00", 20)])
    sim = Simulation(net, routing_algo=algorithm)
    assert sim.run_for() == 10_000
    summary = sim.summary()
    assert summary["stop_reason"] == "duration_limit"
    assert summary["rounds"] == 1_000
    assert summary["generated_packets"] == 3_000
    assert summary["delivered_packets"] == 999
    assert summary["drop_reasons"]["unreachable"] == 2_000
    assert summary["drop_reasons"]["simulation_end_duration_limit"] == 1
    assert summary["milestones"]["LND"]["time_s"] is None
    assert summary["milestones"]["functional_death"]["time_s"] == 0
    assert sim.samples[-1]["Pending_Packets"] == 0


def test_lnd_stops_simpy_before_limit_and_closes_samples(config):
    config = replace(config, initial_energy_j=1e-9, channel_loss_probability=0)
    net = small_network(config, 1, [("sensor_000", "sink_00", 100)])
    sim = Simulation(net)
    assert sim.run_for() == sim.env.now == 10
    summary = sim.summary()
    assert summary["stop_reason"] == "lnd"
    assert summary["drop_reasons"]["energy_depletion"] == 1
    assert summary["data_tx_attempts"] == 0
    assert summary["energy_consumed_j"] == config.initial_energy_j
    for name in ("FND", "HND", "LND"):
        assert summary["milestones"][name] == {"time_s": 10.0, "payload_bits": 0}
    assert sim.samples[-1]["Time_s"] == 10


@pytest.mark.parametrize("loss", [0, 1])
def test_completion_at_limit_counts_and_full_tx_is_charged_even_if_lost(config, loss):
    net = small_network(replace(config, channel_loss_probability=loss), 1, [("sensor_000", "sink_00", 20)])
    sim = Simulation(net, routing_algo="MHR")
    duration = 10 + config.packet_size_bytes * 8 / 250_000
    sim.run_for(duration, finalize=True)
    summary = sim.summary()
    packet, = sim.traffic_gen.generated_packets
    assert packet.tx_attempts == summary["data_tx_attempts"] == 1
    assert summary["energy_consumed_j"] == pytest.approx(sum(summary["energy_ledger_j"].values()))
    assert summary["energy_ledger_j"]["data_tx_j"] == pytest.approx(sim.radio.compute_tx_energy(1024, 20))
    assert summary["energy_ledger_j"].get("data_rx_j", 0) == 0
    assert summary["pending_packets"] == 0
    if loss:
        assert packet.drop_reason == "natural_link_loss"
        assert packet.status == PacketStatus.DROPPED
        assert summary["delivered_payload_bits"] == 0
    else:
        assert packet.status == PacketStatus.DELIVERED
        assert packet.delivered_at == duration
        assert packet.current_hop_index == packet.hop_count == 1
        assert net.sinks[packet.route[-1]].received_packet_ids == {packet.packet_id}
        assert summary["delivered_payload_bits"] == 1024


def test_transmission_crossing_limit_is_accounted_for(config):
    net = small_network(config, 1, [("sensor_000", "sink_00", 20)])
    sim = Simulation(net)
    sim.run_for(10.001, finalize=True)
    packet, = sim.traffic_gen.generated_packets
    assert packet.tx_attempts == 1
    assert packet.current_hop_index == 0
    assert packet.drop_reason == "simulation_end_duration_limit"
    assert sim.traffic_gen.cutoff_state[packet.packet_id] == "transmitting"


def test_gpsr_recovery_terminates_at_the_first_sink(config):
    config = replace(config, num_sensors=3, num_sinks=2, channel_loss_probability=0)
    network = Network(config, 300)
    nodes = [*network.sensors.values(), *network.sinks.values()]
    for node, coordinates in zip(nodes, [(0, 0), (0, 300), (410, 200), (350, 0), (250, 450)]):
        node.x, node.y = coordinates
    network.build_graph(300)
    sim = Simulation(network, routing_algo="GPSR")
    sim.run_for(11, finalize=True)
    forwarded = sim.traffic_gen.generated_packets[0]
    assert forwarded.route == ["sensor_000", "sensor_001", "sink_01"]
    assert forwarded.status == PacketStatus.DELIVERED
