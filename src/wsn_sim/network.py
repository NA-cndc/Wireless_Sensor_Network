from __future__ import annotations
from math import hypot
import networkx as nx
import numpy as np
from wsn_sim.config import SimulationConfig, require_number
from wsn_sim.models import Sensor, Sink

class Network:

    def __init__(self, config: SimulationConfig, communication_range_m: float | None=None, *, range_m: float | None=None, sensors: dict[str, Sensor] | None=None, sinks: dict[str, Sink] | None=None) -> None:
        self.config = config
        if (sensors is None) != (sinks is None):
            raise ValueError('provide both sensors and sinks for a custom topology')
        self.sensors = {} if sensors is None else dict(sensors)
        self.sinks = {} if sinks is None else dict(sinks)
        self.graph = nx.Graph()
        self.communication_range_m = 0.0
        if sensors is None:
            self._generate_nodes()
        elif len(self.sensors) != config.num_sensors or len(self.sinks) != config.num_sinks:
            raise ValueError('custom node counts must match the configuration')
        if set(self.sensors) & set(self.sinks) or any((key != node.node_id for key, node in [*self.sensors.items(), *self.sinks.items()])):
            raise ValueError('node IDs must be unique and match their dictionary keys')
        effective_range = range_m if communication_range_m is None else communication_range_m
        initial_range = config.communication_range_m if effective_range is None else effective_range
        self.build_graph(initial_range)

    def _generate_nodes(self) -> None:
        rng = np.random.default_rng(self.config.stream_seeds['topology'])
        node_count = self.config.num_sensors + self.config.num_sinks
        coordinates = rng.uniform(low=(0.0, 0.0), high=(self.config.area_width_m, self.config.area_height_m), size=(node_count, 2))
        for index, (x, y) in enumerate(coordinates[:self.config.num_sensors]):
            node_id = f'sensor_{index:03d}'
            self.sensors[node_id] = Sensor(node_id=node_id, x=float(x), y=float(y), initial_energy_j=self.config.initial_energy_j)
        for index, (x, y) in enumerate(coordinates[self.config.num_sensors:]):
            node_id = f'sink_{index:02d}'
            self.sinks[node_id] = Sink(node_id=node_id, x=float(x), y=float(y))

    def build_graph(self, communication_range_m: float | None=None, *, range_m: float | None=None) -> nx.Graph:
        effective_range = range_m if communication_range_m is None else communication_range_m
        if effective_range is None:
            raise TypeError("build_graph() missing required argument: 'communication_range_m' or 'range_m'")
        require_number('communication_range_m', effective_range)
        communication_range_m = effective_range
        graph = nx.Graph()
        for sensor in self.sensors.values():
            graph.add_node(sensor.node_id, node_type='sensor', x=sensor.x, y=sensor.y, energy_j=sensor.energy_j)
        for sink in self.sinks.values():
            graph.add_node(sink.node_id, node_type='sink', x=sink.x, y=sink.y)
        sensor_nodes = list(self.sensors.values())
        sink_nodes = list(self.sinks.values())
        for left_index, left in enumerate(sensor_nodes):
            for right in sensor_nodes[left_index + 1:]:
                self._add_edge_if_in_range(graph, left, right, communication_range_m)
            for sink in sink_nodes:
                self._add_edge_if_in_range(graph, left, sink, communication_range_m)
        self.graph = graph
        self.communication_range_m = float(communication_range_m)
        return graph

    @staticmethod
    def _add_edge_if_in_range(graph: nx.Graph, left: Sensor | Sink, right: Sensor | Sink, communication_range_m: float) -> None:
        distance_m = hypot(left.x - right.x, left.y - right.y)
        if distance_m <= communication_range_m:
            graph.add_edge(left.node_id, right.node_id, distance_m=distance_m)

    def neighbors(self, node_id: str) -> list[str]:
        if node_id not in self.graph:
            raise KeyError(f'unknown node_id: {node_id}')
        return sorted(self.graph.neighbors(node_id))

    def distance(self, left_id: str, right_id: str) -> float:
        left = self.sensors.get(left_id) or self.sinks[left_id]
        right = self.sensors.get(right_id) or self.sinks[right_id]
        return hypot(left.x - right.x, left.y - right.y)

    def isolated_sensor_ids(self) -> list[str]:
        return sorted((node_id for node_id in self.sensors if self.graph.degree[node_id] == 0))

    def routable_sensor_ids(self) -> list[str]:
        routable: set[str] = set()
        sink_ids = set(self.sinks)
        live_graph = nx.subgraph_view(self.graph, filter_node=lambda node: node in self.sinks or self.sensors[node].is_alive)
        for component in nx.connected_components(live_graph):
            if component & sink_ids:
                routable.update(component & self.sensors.keys())
        return sorted(routable)

    def topology_summary(self) -> dict[str, int | float]:
        return {'seed': self.config.seed, 'communication_range_m': self.communication_range_m, 'sensors': len(self.sensors), 'sinks': len(self.sinks), 'nodes': self.graph.number_of_nodes(), 'edges': self.graph.number_of_edges(), 'routable_sensors': len(self.routable_sensor_ids()), 'isolated_sensors': len(self.isolated_sensor_ids())}

    def coordinates(self) -> dict[str, tuple[float, float]]:
        return {node_id: (float(data['x']), float(data['y'])) for node_id, data in self.graph.nodes(data=True)}
