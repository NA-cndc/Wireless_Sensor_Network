from __future__ import annotations
from heapq import heappop, heappush
from typing import TYPE_CHECKING
import networkx as nx
from wsn_sim.network import Network
if TYPE_CHECKING:
    from wsn_sim.detection import ForwardingDetector
REASON_CATEGORIES = {'node_dead': 'energy', 'relay_energy': 'energy', 'isolation': 'security', 'link_unavailable': 'link', 'unknown_node': 'route', 'invalid_route': 'route'}

class RoutingEngine:

    def __init__(self, network: Network, detector: ForwardingDetector | None=None) -> None:
        self.network = network
        self.detector = detector
        self.cache_enabled = False
        self.cache_hits = 0
        self._cache_epoch = 0
        self._cached_epoch = None
        self._route_cache = {}
        self._reachable_cache = None
        self._last_route_unique = False

    def get_mhr_route(self, source_id: str) -> list[str] | None:
        return self.find_route(source_id, 'MHR')

    def get_emhr_route(self, source_id: str, threshold_j: float | None=None) -> list[str] | None:
        return self.find_route(source_id, 'EMHR', threshold_j=threshold_j)

    def get_semhr_route(self, source_id: str, **options) -> list[str] | None:
        return self.find_route(source_id, 'S_EMHR', **options)

    def _node_ineligibility(self, node_id, algorithm, packet_source_id, time_s, threshold_j=None):
        if node_id in self.network.sinks:
            return None
        sensor = self.network.sensors.get(node_id)
        if sensor is None:
            return 'unknown_node'
        if not sensor.is_alive:
            return 'node_dead'
        if node_id == packet_source_id:
            return None
        threshold = self.network.config.energy_threshold_j if threshold_j is None else threshold_j
        if algorithm != 'MHR' and (not sensor.can_forward(threshold)):
            return 'relay_energy'
        if algorithm == 'S_EMHR' and self.detector.is_isolated(node_id, time_s):
            return 'isolation'
        return None

    def eligible(self, node_id: str, algorithm: str, packet_source_id: str, time_s: float, threshold_j: float | None=None) -> bool:
        return self._node_ineligibility(node_id, algorithm, packet_source_id, time_s, threshold_j) is None

    @property
    def validation_epoch(self):
        return (self._cache_epoch, self.detector.routing_epoch if self.detector is not None and self.network.config.routing_algorithm == 'S_EMHR' else 0)

    def invalidate_cache(self, node_id=None, removed=False):
        self._cache_epoch += 1
        self._reachable_cache = None
        if removed and node_id is not None:
            self._route_cache = {key: route for key, route in self._route_cache.items() if route is None or node_id not in route}
        else:
            self._route_cache.clear()
        self._cached_epoch = self.validation_epoch

    def _synchronize_cache(self):
        epoch = self.validation_epoch
        if epoch != self._cached_epoch:
            self._route_cache.clear()
            self._reachable_cache = None
            self._cached_epoch = epoch

    def find_route(self, source_id: str, algorithm: str | None=None, **options) -> list[str] | None:
        algorithm = self.network.config.routing_algorithm if algorithm is None else algorithm
        if not self.cache_enabled or algorithm != self.network.config.routing_algorithm:
            return self._find_route(source_id, algorithm, **options)
        if algorithm == 'S_EMHR' and self.detector is not None:
            self.detector.advance(options.get('time_s', 0))
        self._synchronize_cache()
        key = (source_id, algorithm, options.get('packet_source_id'), options.get('target_sink'), frozenset(options.get('forbidden') or ()), options.get('threshold_j'))
        if key in self._route_cache:
            self.cache_hits += 1
            route = self._route_cache[key]
            return None if route is None else list(route)
        route = self._find_route(source_id, algorithm, **options)
        if route is None or self._last_route_unique or algorithm == 'MHR':
            self._route_cache[key] = None if route is None else tuple(route)
        return route

    def reachable_sensor_ids(self, time_s: float) -> list[str]:
        if not self.cache_enabled:
            return self._reachable_sensor_ids(time_s)
        if self.network.config.routing_algorithm == 'S_EMHR' and self.detector is not None:
            self.detector.advance(time_s)
        self._synchronize_cache()
        if self._reachable_cache is None:
            self._reachable_cache = self._reachable_sensor_ids(time_s)
        return list(self._reachable_cache)

    def _find_route(self, source_id: str, algorithm: str | None=None, *, packet_source_id: str | None=None, target_sink: str | None=None, forbidden: set[str] | None=None, time_s: float=0.0, threshold_j: float | None=None) -> list[str] | None:
        algorithm = self.network.config.routing_algorithm if algorithm is None else algorithm
        if algorithm not in {'MHR', 'EMHR', 'S_EMHR'}:
            raise ValueError(f'unknown routing algorithm: {algorithm}')
        if algorithm == 'S_EMHR' and self.detector is None:
            raise ValueError('S_EMHR requires a forwarding detector')
        if target_sink is not None and target_sink not in self.network.sinks:
            return None
        packet_source_id = source_id if packet_source_id is None else packet_source_id
        blocked = forbidden or set()
        graph = nx.subgraph_view(self.network.graph, filter_node=lambda node: node not in blocked and self.eligible(node, algorithm, packet_source_id, time_s, threshold_j))
        if source_id not in self.network.sensors or source_id not in graph:
            return None

        def penalty(node: str) -> float:
            sensor = self.network.sensors.get(node)
            if algorithm == 'MHR' or sensor is None:
                return 0.0
            return self.network.config.initial_energy_j / (sensor.energy_j + self.network.config.energy_epsilon_j)
        self._last_route_unique = False
        path_counts = {source_id: 1}
        initial = (0, 0.0, 0.0, (source_id,))
        best = {source_id: initial}
        queue = [initial]
        while queue:
            cost = heappop(queue)
            hops, distance, energy_penalty, path = cost
            node = path[-1]
            if best[node] != cost:
                continue
            if node in self.network.sinks:
                if target_sink is None or node == target_sink:
                    matching = [end for end, label in best.items() if end in self.network.sinks and (target_sink is None or end == target_sink) and (label[:2] == cost[:2])]
                    self._last_route_unique = sum((path_counts[end] for end in matching)) == 1
                    return list(path)
                continue
            for neighbor in sorted(graph.neighbors(node)):
                edge_distance = self.network.distance(node, neighbor) if algorithm != 'MHR' else 0.0
                candidate = (hops + 1, distance + edge_distance, energy_penalty + penalty(neighbor), (*path, neighbor))
                if neighbor not in best or candidate[:2] < best[neighbor][:2]:
                    path_counts[neighbor] = path_counts[node]
                elif candidate[:2] == best[neighbor][:2]:
                    path_counts[neighbor] = min(2, path_counts[neighbor] + path_counts[node])
                if neighbor not in best or candidate < best[neighbor]:
                    best[neighbor] = candidate
                    heappush(queue, candidate)
        return None

    def _reachable_sensor_ids(self, time_s: float) -> list[str]:
        algorithm = self.network.config.routing_algorithm
        if algorithm == 'S_EMHR' and self.detector is None:
            raise ValueError('S_EMHR reachability requires a detector')
        graph = self.network.graph
        relays = {node for node in self.network.sensors if node in graph and self.eligible(node, algorithm, '', time_s)}
        reachable = {node for node in self.network.sinks if node in graph}
        frontier = list(reachable)
        while frontier:
            node = frontier.pop()
            for neighbor in graph.neighbors(node):
                if neighbor in relays and neighbor not in reachable:
                    reachable.add(neighbor)
                    frontier.append(neighbor)
        return sorted((node for node, sensor in self.network.sensors.items() if sensor.is_alive and node in graph and (node in reachable or any((neighbor in reachable for neighbor in graph.neighbors(node))))))

    def route_issues(self, route: list[str], packet_source_id: str, time_s: float) -> list[dict]:
        if len(route) < 2 or len(route) != len(set(route)) or route[-1] not in self.network.sinks or any((node in self.network.sinks for node in route[:-1])):
            return [{'reason': 'invalid_route', 'reason_category': 'route', 'node_id': None}]
        issues = []
        for node in route:
            reason = self._node_ineligibility(node, self.network.config.routing_algorithm, packet_source_id, time_s)
            if reason is not None:
                issues.append({'reason': reason, 'reason_category': REASON_CATEGORIES[reason], 'node_id': node})
        issues.extend(({'reason': 'link_unavailable', 'reason_category': 'link', 'node_id': None, 'sender_id': left, 'receiver_id': right} for left, right in zip(route, route[1:]) if not self.network.graph.has_edge(left, right)))
        return issues

    def route_is_valid(self, route: list[str], packet_source_id: str, time_s: float) -> bool:
        return not self.route_issues(route, packet_source_id, time_s)
