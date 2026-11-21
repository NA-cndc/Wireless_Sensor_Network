"""Routing algorithms for the WSN simulation (Tối ưu hóa hiệu năng cao)."""

from __future__ import annotations

import heapq
import random
from math import hypot

import networkx as nx

from analysis.foundation.network import Network


class RoutingEngine:
    """Cung cấp các chiến lược định tuyến cho gói tin trong mạng WSN."""

    def __init__(
        self, network: Network, rng: random.Random | None = None, *, cache_mhr: bool = False,
    ) -> None:
        self.network = network
        self.rng = rng if rng is not None else random.Random(network.config.effective_traffic_seed)
        self._mhr_graph = network.graph
        self._mhr_choices: dict[str, list[list[str]]] | None = {} if cache_mhr else None
        self._static_dist_cache: dict[str, list[tuple[str, float]]] | None = None
        self._cached_alpha: float | None = None

    def invalidate_mhr(self) -> None:
        if self._mhr_choices is not None:
            self._mhr_choices.clear()

    def get_mhr_route(self, source_id: str) -> list[str] | None:
        if self._mhr_graph is not self.network.graph:
            self.invalidate_mhr()
            self._mhr_graph = self.network.graph
        choices = None if self._mhr_choices is None else self._mhr_choices.get(source_id)
        if choices is None:
            choices = self._mhr_shortest_routes(source_id)
            if self._mhr_choices is not None:
                self._mhr_choices[source_id] = choices
        return self.rng.choice(choices) if choices else None

    def _mhr_shortest_routes(self, source_id: str) -> list[list[str]]:
        """
        Minimum Hop Routing (MHR) - Tối ưu BFS dừng sớm theo từng lớp hop.
        Giữ nguyên cân bằng tải ngẫu nhiên giữa các Sink cùng số hop nhỏ nhất.
        """
        sensors = self.network.sensors
        sinks = self.network.sinks
        src_sensor = sensors.get(source_id)
        if src_sensor is None or not src_sensor.is_alive:
            return []

        adj = self.network.graph._adj
        if source_id not in adj:
            return []

        parent: dict[str, str | None] = {source_id: None}
        current_level = [source_id]
        found_sinks: list[str] = []

        while current_level and not found_sinks:
            next_level: list[str] = []
            for u in current_level:
                for v in adj[u]:
                    if v in parent:
                        continue
                    if v in sinks:
                        parent[v] = u
                        found_sinks.append(v)
                    else:
                        sv = sensors.get(v)
                        if sv is not None and sv.is_alive:
                            parent[v] = u
                            next_level.append(v)
            current_level = next_level

        return [self._reconstruct(parent, sink_id) for sink_id in found_sinks]

    @staticmethod
    def _reconstruct(parent: dict[str, str | None], node_id: str) -> list[str]:
        route: list[str] = []
        current: str | None = node_id
        while current is not None:
            route.append(current)
            current = parent[current]
        route.reverse()
        return route

    @property
    def relay_threshold_j(self) -> float:
        return self.network.config.emhr_alpha * self.network.config.initial_energy_j

    def get_emhr_route(
        self, source_id: str, alpha: float | None = None, *, excluded: set[str] | None = None,
    ) -> list[str] | None:
        """Find the minimum (hop count, distance in metres, relay energy penalty)."""
        sensors = self.network.sensors
        sinks = self.network.sinks
        graph = self.network.graph
        source = sensors.get(source_id)
        if source is None or not source.is_alive or source_id not in graph:
            return None

        initial_energy = self.network.config.initial_energy_j
        threshold = self.relay_threshold_j if alpha is None else alpha * initial_energy
        blocked = excluded or set()
        origin = (0, 0.0, 0.0)
        best = {source_id: origin}
        parent: dict[str, str | None] = {source_id: None}
        queue = [(origin, source_id)]
        while queue:
            score, node_id = heapq.heappop(queue)
            if score != best[node_id]:
                continue
            if node_id in sinks:
                return self._reconstruct(parent, node_id)
            hops, distance, penalty = score
            for neighbor, edge in graph[node_id].items():
                if neighbor in blocked:
                    continue
                relay_penalty = 0.0
                if neighbor not in sinks:
                    relay = sensors[neighbor]
                    if not relay.can_forward(threshold):
                        continue
                    relay_penalty = initial_energy / (relay.energy_j + 1e-12)
                candidate = (hops + 1, distance + edge["distance_m"], penalty + relay_penalty)
                if neighbor not in best or candidate < best[neighbor]:
                    best[neighbor] = candidate
                    parent[neighbor] = node_id
                    heapq.heappush(queue, (candidate, neighbor))
        return None

    def get_weighted_dijkstra_route(
        self, source_id: str, alpha: float = 2.0, beta: float = 2.0
    ) -> list[str] | None:
        """
        1. Energy-Distance Weighted Dijkstra (Tối ưu heapq dừng sớm + Cache khoảng cách tĩnh).
        """
        sensors = self.network.sensors
        sinks = self.network.sinks
        src_sensor = sensors.get(source_id)
        if src_sensor is None or not src_sensor.is_alive:
            return None

        adj = self.network.graph._adj
        if source_id not in adj:
            return None

        r_max = self.network.communication_range_m or 300.0
        init_energy = getattr(self.network.config, "initial_energy_j", 5.0)

        if self._static_dist_cache is None or self._cached_alpha != alpha:
            self._cached_alpha = alpha
            self._static_dist_cache = {
                u: [
                    (v, (attrs.get("distance_m", r_max) / r_max) ** alpha)
                    for v, attrs in neighbors.items()
                ]
                for u, neighbors in adj.items()
            }

        static_adj = self._static_dist_cache
        node_energy_cost_cache: dict[str, float] = {}

        pq: list[tuple[float, str]] = [(0.0, source_id)]
        best_dist: dict[str, float] = {source_id: 0.0}
        parent: dict[str, str | None] = {source_id: None}

        while pq:
            cur_cost, u = heapq.heappop(pq)
            if cur_cost > best_dist.get(u, float("inf")):
                continue

            if u in sinks:
                route: list[str] = []
                curr: str | None = u
                while curr is not None:
                    route.append(curr)
                    curr = parent[curr]
                route.reverse()
                return route

            for v, d_cost in static_adj[u]:
                if v in sinks:
                    e_cost = 1.0
                else:
                    e_cost = node_energy_cost_cache.get(v)
                    if e_cost is None:
                        sv = sensors.get(v)
                        if sv is None or not sv.is_alive:
                            node_energy_cost_cache[v] = -1.0
                            continue
                        energy_ratio = max(sv.energy_j, 1e-6) / init_energy
                        e_cost = (1.0 / energy_ratio) ** beta
                        node_energy_cost_cache[v] = e_cost
                    elif e_cost < 0.0:
                        continue

                new_cost = cur_cost + d_cost * e_cost
                if new_cost < best_dist.get(v, float("inf")):
                    best_dist[v] = new_cost
                    parent[v] = u
                    heapq.heappush(pq, (new_cost, v))

        return None

    def get_mmbcr_route(self, source_id: str) -> list[str] | None:
        """
        2. Min-Max Battery Cost Routing (MMBCR):
        Phá vỡ nút thắt cổ chai dựa trên năng lượng của nút yếu nhất trên toàn tuyến.
        """
        sensors = self.network.sensors
        sinks = self.network.sinks
        src_sensor = sensors.get(source_id)
        if src_sensor is None or not src_sensor.is_alive:
            return None

        adj = self.network.graph._adj
        if source_id not in adj:
            return None

        init_energy = getattr(self.network.config, "initial_energy_j", 5.0)

        pq: list[tuple[float, int, str]] = [(0.0, 0, source_id)]
        best_state: dict[str, tuple[float, int]] = {source_id: (0.0, 0)}
        parent: dict[str, str | None] = {source_id: None}

        while pq:
            cur_max_cost, hops, u = heapq.heappop(pq)
            if (cur_max_cost, hops) > best_state.get(u, (float("inf"), 10**9)):
                continue

            if u in sinks:
                route: list[str] = []
                curr: str | None = u
                while curr is not None:
                    route.append(curr)
                    curr = parent[curr]
                route.reverse()
                return route

            for v in adj[u]:
                if v in sinks:
                    v_cost = 0.0
                else:
                    sensor_v = sensors.get(v)
                    if sensor_v is None or not sensor_v.is_alive:
                        continue
                    v_cost = init_energy / max(sensor_v.energy_j, 1e-6)

                new_state = (max(cur_max_cost, v_cost), hops + 1)
                if new_state < best_state.get(v, (float("inf"), 10**9)):
                    best_state[v] = new_state
                    parent[v] = u
                    heapq.heappush(pq, (new_state[0], new_state[1], v))

        return None

    def get_gpsr_route(self, source_id: str) -> list[str] | None:
        """
        3. Energy-Aware GPSR (Greedy Perimeter Stateless Routing):
        Định tuyến cục bộ dựa trên tọa độ địa lý (x, y) kết hợp trọng số năng lượng.
        """
        sensors = self.network.sensors
        sinks = self.network.sinks
        src_sensor = sensors.get(source_id)
        if src_sensor is None or not src_sensor.is_alive:
            return None

        adj = self.network.graph._adj
        if source_id not in adj:
            return None

        r_max = self.network.communication_range_m or 300.0
        init_energy = getattr(self.network.config, "initial_energy_j", 5.0)

        def get_pos(nid: str) -> tuple[float, float]:
            if nid in sinks:
                s = sinks[nid]
                return (s.x, s.y)
            sn = sensors[nid]
            return (sn.x, sn.y)

        route = [source_id]
        visited = {source_id}
        curr = source_id

        for _ in range(60):
            if curr in sinks:
                return route

            neighbors = adj[curr]
            for nb in neighbors:
                if nb in sinks:
                    route.append(nb)
                    return route

            cx, cy = get_pos(curr)
            target_sink = min(
                sinks,
                key=lambda sid: hypot(cx - sinks[sid].x, cy - sinks[sid].y),
            )
            sx, sy = get_pos(target_sink)
            curr_dist_to_sink = hypot(cx - sx, cy - sy)

            best_next = None
            best_score = -1.0

            for nb in neighbors:
                if nb in visited or nb not in sensors:
                    continue
                nb_sensor = sensors[nb]
                if not nb_sensor.is_alive:
                    continue

                nb_dist_to_sink = hypot(nb_sensor.x - sx, nb_sensor.y - sy)
                progress = curr_dist_to_sink - nb_dist_to_sink
                if progress > 0:
                    energy_ratio = nb_sensor.energy_j / init_energy
                    score = (progress / r_max) * (0.4 + 0.6 * energy_ratio)
                    if score > best_score:
                        best_score = score
                        best_next = nb

            if best_next is not None:
                visited.add(best_next)
                route.append(best_next)
                curr = best_next
            else:
                def is_alive(nid: str) -> bool:
                    if nid in sinks:
                        return True
                    sn = sensors.get(nid)
                    return sn is not None and sn.is_alive

                alive_graph = nx.subgraph_view(self.network.graph, filter_node=is_alive)
                try:
                    recovery_path = nx.shortest_path(
                        alive_graph, source=curr, target=target_sink
                    )
                    for node in recovery_path[1:]:
                        if node in route:
                            cut_idx = route.index(node)
                            route = route[: cut_idx + 1]
                        else:
                            route.append(node)
                        if node in sinks:
                            break
                    return route
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    return None

        return None

    def get_route(self, source_id: str, routing_algo: str = "MHR") -> list[str] | None:
        if routing_algo == "MHR":
            return self.get_mhr_route(source_id)
        elif routing_algo == "EMHR":
            return self.get_emhr_route(source_id)
        elif routing_algo == "Weighted_Dijkstra":
            return self.get_weighted_dijkstra_route(source_id)
        elif routing_algo == "MMBCR":
            return self.get_mmbcr_route(source_id)
        elif routing_algo == "GPSR":
            return self.get_gpsr_route(source_id)
        else:
            raise ValueError(f"Thuật toán định tuyến không hợp lệ: {routing_algo}")
