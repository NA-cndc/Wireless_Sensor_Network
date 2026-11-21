from math import hypot

import networkx as nx
import numpy as np

from wsn_sim.provenance import json_digest

SINK_POSITIONS = (
    (1500.0, 1500.0),
    (500.0, 500.0),
    (2500.0, 500.0),
    (500.0, 2500.0),
    (2500.0, 2500.0),
    (500.0, 1500.0),
    (2500.0, 1500.0),
)
TOPOLOGY_MODELS = ("uniform", "na")


class PhysicalTopology:
    def neighbors(self, node_id: str) -> list[str]:
        """Return the sorted neighboring node IDs for an existing node."""
        if node_id not in self.graph:
            raise KeyError(f"unknown node_id: {node_id}")
        return sorted(self.graph.neighbors(node_id))

    def isolated_sensor_ids(self) -> list[str]:
        """Return sensor IDs with graph degree zero."""
        return sorted(node_id for node_id in self.sensors if self.graph.degree[node_id] == 0)

    def coordinates(self) -> dict[str, tuple[float, float]]:
        """Return a copy of all node coordinates keyed by node ID."""
        return {
            node_id: (float(data["x"]), float(data["y"]))
            for node_id, data in self.graph.nodes(data=True)
        }

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


def generate_nodes(config, sensor_type, sink_type):
    rng = np.random.default_rng(config.seed)
    bounds = (config.area_width_m, config.area_height_m)
    use_na = (
        config.topology_model == "na"
        and bounds == (3000, 3000)
        and (config.num_sensors, config.num_sinks) == (450, 7)
    )
    sensor_count = int(rng.integers(400, 501)) if use_na else config.num_sensors
    sensor_coordinates = rng.uniform((0.0, 0.0), bounds, size=(sensor_count, 2))
    sink_coordinates = (
        SINK_POSITIONS if use_na
        else rng.uniform((0.0, 0.0), bounds, size=(config.num_sinks, 2))
    )
    sensors = {}
    for index, (x, y) in enumerate(sensor_coordinates):
        node_id = f"sensor_{index:03d}"
        sensors[node_id] = sensor_type(
            node_id=node_id, x=float(x), y=float(y), initial_energy_j=config.initial_energy_j,
        )
    sinks = {}
    for index, (x, y) in enumerate(sink_coordinates):
        node_id = f"sink_{index:02d}"
        sinks[node_id] = sink_type(node_id=node_id, x=float(x), y=float(y))
    return sensors, sinks


def physical_graph(sensors, sinks, radius):
    graph = nx.Graph()
    for node in sensors.values():
        graph.add_node(node.node_id, node_type="sensor", x=node.x, y=node.y, energy_j=node.energy_j)
    for node in sinks.values():
        graph.add_node(node.node_id, node_type="sink", x=node.x, y=node.y)
    sensor_nodes = list(sensors.values())
    for index, left in enumerate(sensor_nodes):
        for right in sensor_nodes[index + 1:]:
            _add_edge_if_in_range(graph, left, right, radius)
        for sink in sinks.values():
            _add_edge_if_in_range(graph, left, sink, radius)
    return graph


def _add_edge_if_in_range(graph, left, right, radius):
    distance = hypot(left.x - right.x, left.y - right.y)
    if distance <= radius:
        graph.add_edge(left.node_id, right.node_id, distance_m=distance)


def sink_connected_sensor_ids(graph, sensors, sinks, *, alive_only):
    sink_ids = set(sinks)
    if alive_only:
        alive = {node_id for node_id, node in sensors.items() if node.is_alive}
        graph = graph.subgraph(alive | sink_ids)
    reachable = set()
    for component in nx.connected_components(graph):
        if component & sink_ids:
            reachable.update(component & sensors.keys())
    return sorted(reachable)


def topology_record(network):
    coordinates = network.coordinates()
    edges = sorted(sorted(edge) for edge in network.graph.edges)
    return {
        "coordinates": coordinates,
        "physical_edges": edges,
        "topology_hash": json_digest({"coordinates": coordinates, "edges": edges}),
        "topology_seed": network.topology_seed,
        "actual_num_sensors": len(network.sensors),
    }


def terminal_log_sample(alive_sensors, physical_reachable_alive):
    return alive_sensors == 0 or physical_reachable_alive == 0
