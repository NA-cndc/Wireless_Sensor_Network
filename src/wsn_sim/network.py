from __future__ import annotations
from math import hypot
import networkx as nx
from wsn_sim.config import SimulationConfig, require_number
from wsn_sim.models import Sensor, Sink
from wsn_sim.topology import PhysicalTopology, generate_nodes, physical_graph, sink_connected_sensor_ids

class Network(PhysicalTopology):

    def __init__(self, config: SimulationConfig, communication_range_m: float | None=None, *, range_m: float | None=None, sensors: dict[str, Sensor] | None=None, sinks: dict[str, Sink] | None=None) -> None:
        self.config = config
        self.topology_seed = config.stream_seeds['topology'] if sensors is None else None
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
        self.sensors, self.sinks = generate_nodes(self.config, Sensor, Sink)

    def build_graph(self, communication_range_m: float | None=None, *, range_m: float | None=None) -> nx.Graph:
        effective_range = range_m if communication_range_m is None else communication_range_m
        if effective_range is None:
            raise TypeError("build_graph() missing required argument: 'communication_range_m' or 'range_m'")
        require_number('communication_range_m', effective_range)
        self.graph = physical_graph(self.sensors, self.sinks, effective_range)
        self.communication_range_m = float(effective_range)
        return self.graph

    def distance(self, left_id: str, right_id: str) -> float:
        left = self.sensors.get(left_id) or self.sinks[left_id]
        right = self.sensors.get(right_id) or self.sinks[right_id]
        return hypot(left.x - right.x, left.y - right.y)

    def routable_sensor_ids(self, *, alive_only: bool = True) -> list[str]:
        return sink_connected_sensor_ids(self.graph, self.sensors, self.sinks, alive_only=alive_only)
