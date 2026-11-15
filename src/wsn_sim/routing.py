"""Routing algorithms for the WSN simulation (Tối ưu hóa hiệu năng cao)."""

from __future__ import annotations

import heapq
import random
from math import hypot

import networkx as nx

from wsn_sim.network import Network


class RoutingEngine:
    """Cung cấp các chiến lược định tuyến cho gói tin trong mạng WSN."""

    def __init__(self, network: Network) -> None:
        self.network = network
        self._static_dist_cache: dict[str, list[tuple[str, float]]] | None = None
        self._cached_alpha: float | None = None

    def get_mhr_route(self, source_id: str) -> list[str] | None:
        """
        Minimum Hop Routing (MHR) - Tối ưu BFS dừng sớm theo từng lớp hop.
        Giữ nguyên cân bằng tải ngẫu nhiên giữa các Sink cùng số hop nhỏ nhất.
        """
        sensors = self.network.sensors
        sinks = self.network.sinks
        src_sensor = sensors.get(source_id)
        if src_sensor is None or not src_sensor.is_alive:
            return None

        adj = self.network.graph._adj
        if source_id not in adj:
            return None

        parent: dict[str, str | None] = {source_id: None}
        current_level = [source_id]
        found_sinks: list[str] = []

        # Duyệt BFS từng lớp hop; dừng ngay khi chạm lớp đầu tiên có Sink
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

        if not found_sinks:
            return None

        curr: str | None = random.choice(found_sinks)
        route: list[str] = []
        while curr is not None:
            route.append(curr)
            curr = parent[curr]
        route.reverse()
        return route

    def get_emhr_route(self, source_id: str, alpha: float = 0.8) -> list[str] | None:
        """
        Energy-aware Minimum Hop Routing (EMHR) với Cơ chế Dự phòng (Fallback).
        Tối ưu hóa bằng BFS dừng sớm + Cache trạng thái pin láng giềng theo gói tin.
        """
        sensors = self.network.sensors
        sinks = self.network.sinks
        src_sensor = sensors.get(source_id)
        if src_sensor is None or not src_sensor.is_alive:
            return None

        adj = self.network.graph._adj
        if source_id not in adj:
            return None

        eligible_cache: dict[str, bool] = {}

        def is_eligible(node_id: str) -> bool:
            cached = eligible_cache.get(node_id)
            if cached is not None:
                return cached

            sensor = sensors.get(node_id)
            if sensor is None or not sensor.is_alive or sensor.energy_j <= 0.1:
                eligible_cache[node_id] = False
                return False

            total_e = 0.0
            count = 0
            for nb in adj[node_id]:
                nb_s = sensors.get(nb)
                if nb_s is not None and nb_s.is_alive:
                    total_e += nb_s.energy_j
                    count += 1

            res = True if count == 0 else (sensor.energy_j >= alpha * (total_e / count))
            eligible_cache[node_id] = res
            return res

        def bfs_early_exit(check_eligible: bool) -> list[str] | None:
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
                            if check_eligible:
                                ok = is_eligible(v)
                            else:
                                sv = sensors.get(v)
                                ok = sv is not None and sv.is_alive
                            if ok:
                                parent[v] = u
                                next_level.append(v)
                current_level = next_level

            if not found_sinks:
                return None

            curr: str | None = random.choice(found_sinks)
            route: list[str] = []
            while curr is not None:
                route.append(curr)
                curr = parent[curr]
            route.reverse()
            return route

        # Bước 1: Tìm đường qua các node khỏe mạnh (Dừng ngay khi chạm Sink gần nhất)
        route = bfs_early_exit(check_eligible=True)

        # Bước 2 (Fallback): Nếu không có đường khỏe, tìm đường qua mọi node còn sống
        if route is None:
            route = bfs_early_exit(check_eligible=False)

        return route

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

        # Tính sẵn (dist_m / r_max) ** alpha một lần duy nhất cho toàn bộ mô phỏng
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

            # Dừng ngay khi pop được trạm Sink có tổng chi phí thấp nhất
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