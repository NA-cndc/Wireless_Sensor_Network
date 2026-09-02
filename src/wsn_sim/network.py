"""Reproducible WSN node generation and connectivity graph construction."""

from __future__ import annotations

from math import hypot

import networkx as nx
import numpy as np

from wsn_sim.config import SimulationConfig
from wsn_sim.models import Sensor, Sink


class Network:
    """Manage stationary nodes and a bidirectional NetworkX topology graph."""

    def __init__(
        self,
        config: SimulationConfig,
        communication_range_m: float | None = None,
    ) -> None:
        """Generate nodes from ``config.seed`` and build the first topology.

        Args:
            config: Validated simulation parameters.
            communication_range_m: Optional initial radio range. The first range
                in the configuration is used when omitted.
        """
        self.config = config
        self.sensors: dict[str, Sensor] = {}
        self.sinks: dict[str, Sink] = {}
        self.graph = nx.Graph()
        self.communication_range_m = 0.0
        self._generate_nodes()
        initial_range = (
            config.communication_ranges_m[0]
            if communication_range_m is None
            else communication_range_m
        )
        self.build_graph(initial_range)

    def _generate_nodes(self) -> None:
        rng = np.random.default_rng(self.config.seed)
        node_count = self.config.num_sensors + self.config.num_sinks
        coordinates = rng.uniform(
            low=(0.0, 0.0),
            high=(self.config.area_width_m, self.config.area_height_m),
            size=(node_count, 2),
        )

        for index, (x, y) in enumerate(coordinates[: self.config.num_sensors]):
            node_id = f"sensor_{index:03d}"
            self.sensors[node_id] = Sensor(
                node_id=node_id,
                x=float(x),
                y=float(y),
                initial_energy_j=self.config.initial_energy_j,
            )

        for index, (x, y) in enumerate(coordinates[self.config.num_sensors :]):
            node_id = f"sink_{index:02d}"
            self.sinks[node_id] = Sink(node_id=node_id, x=float(x), y=float(y))

    def build_graph(self, communication_range_m: float) -> nx.Graph:
        """Build a fresh graph without modifying generated node coordinates.

        Args:
            communication_range_m: Positive Euclidean link threshold in metres.

        Returns:
            The newly built undirected :class:`networkx.Graph`.

        Raises:
            ValueError: If the communication range is not positive.
        """
        if communication_range_m <= 0:
            raise ValueError("communication_range_m must be greater than zero")

        graph = nx.Graph()
        for sensor in self.sensors.values():
            graph.add_node(
                sensor.node_id,
                node_type="sensor",
                x=sensor.x,
                y=sensor.y,
                energy_j=sensor.energy_j,
            )
        for sink in self.sinks.values():
            graph.add_node(
                sink.node_id,
                node_type="sink",
                x=sink.x,
                y=sink.y,
            )

        sensor_nodes = list(self.sensors.values())
        sink_nodes = list(self.sinks.values())

        for left_index, left in enumerate(sensor_nodes):
            for right in sensor_nodes[left_index + 1 :]:
                self._add_edge_if_in_range(
                    graph, left, right, communication_range_m
                )
            for sink in sink_nodes:
                self._add_edge_if_in_range(
                    graph, left, sink, communication_range_m
                )

        self.graph = graph
        self.communication_range_m = float(communication_range_m)
        return graph

    @staticmethod
    def _add_edge_if_in_range(
        graph: nx.Graph,
        left: Sensor | Sink,
        right: Sensor | Sink,
        communication_range_m: float,
    ) -> None:
        distance_m = hypot(left.x - right.x, left.y - right.y)
        if distance_m <= communication_range_m:
            graph.add_edge(
                left.node_id,
                right.node_id,
                distance_m=distance_m,
            )

    def neighbors(self, node_id: str) -> list[str]:
        """Return the sorted neighboring node IDs for an existing node."""
        if node_id not in self.graph:
            raise KeyError(f"unknown node_id: {node_id}")
        return sorted(self.graph.neighbors(node_id))

    def isolated_sensor_ids(self) -> list[str]:
        """Return sensor IDs with graph degree zero."""
        return sorted(
            node_id
            for node_id in self.sensors
            if self.graph.degree[node_id] == 0
        )

    def routable_sensor_ids(self) -> list[str]:
        """Return sensors in connected components containing at least one sink."""
        routable: set[str] = set()
        sink_ids = set(self.sinks)
        for component in nx.connected_components(self.graph):
            if component & sink_ids:
                routable.update(component & self.sensors.keys())
        return sorted(routable)

    def topology_summary(self) -> dict[str, int | float]:
        """Return scalar topology statistics for the active graph and range."""
        return {
            "seed": self.config.seed,
            "communication_range_m": self.communication_range_m,
            "sensors": len(self.sensors),
            "sinks": len(self.sinks),
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "routable_sensors": len(self.routable_sensor_ids()),
            "isolated_sensors": len(self.isolated_sensor_ids()),
        }

    def coordinates(self) -> dict[str, tuple[float, float]]:
        """Return a copy of all node coordinates keyed by node ID."""
        return {
            node_id: (float(data["x"]), float(data["y"]))
            for node_id, data in self.graph.nodes(data=True)
        }
