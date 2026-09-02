"""Tests for reproducible topology generation and graph constraints."""

from math import hypot

import pytest

from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network


def test_expected_node_counts_and_unique_ids(network: Network) -> None:
    all_ids = [*network.sensors, *network.sinks]

    assert len(network.sensors) == 450
    assert len(network.sinks) == 7
    assert network.graph.number_of_nodes() == 457
    assert len(all_ids) == len(set(all_ids))


def test_coordinates_stay_inside_configured_area(network: Network) -> None:
    for _, (x, y) in network.coordinates().items():
        assert 0 <= x <= network.config.area_width_m
        assert 0 <= y <= network.config.area_height_m


def test_edges_respect_range_distance_and_sink_rule(network: Network) -> None:
    radius = network.communication_range_m
    for left, right, data in network.graph.edges(data=True):
        assert not (left.startswith("sink_") and right.startswith("sink_"))
        left_data = network.graph.nodes[left]
        right_data = network.graph.nodes[right]
        expected = hypot(
            left_data["x"] - right_data["x"],
            left_data["y"] - right_data["y"],
        )
        assert data["distance_m"] == pytest.approx(expected)
        assert data["distance_m"] <= radius


def test_same_seed_reproduces_coordinates_and_edges(
    config: SimulationConfig,
) -> None:
    first = Network(config, 300)
    second = Network(config, 300)

    assert first.coordinates() == second.coordinates()
    assert set(first.graph.edges) == set(second.graph.edges)


def test_ranges_rebuild_graph_without_moving_nodes(network: Network) -> None:
    coordinates = network.coordinates()
    edge_counts = []

    for radius in (250, 300, 350):
        network.build_graph(radius)
        edge_counts.append(network.graph.number_of_edges())
        assert network.coordinates() == coordinates

    assert edge_counts == sorted(edge_counts)


def test_neighbors_isolated_routable_and_summary(network: Network) -> None:
    summary = network.topology_summary()

    assert isinstance(network.neighbors("sensor_000"), list)
    assert set(network.isolated_sensor_ids()) <= set(network.sensors)
    assert set(network.routable_sensor_ids()) <= set(network.sensors)
    assert summary["seed"] == 42
    assert summary["sensors"] == 450
    assert summary["sinks"] == 7
    assert summary["nodes"] == 457
