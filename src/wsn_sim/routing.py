"""Routing algorithms for the WSN simulation: MHR, EMHR, and S-EMHR.

Triển khai BFS Layering kết hợp DAG Dynamic Programming để tối ưu hóa thứ tự Lexicographic:
1. H(P): Số chặng nhảy (hops) nhỏ nhất tới bất kỳ Sink nào.
2. D(P): Tổng khoảng cách vật lý nhỏ nhất.
3. Phi_E(P): Hàm phạt năng lượng các nút trung gian nhỏ nhất.
4. Tuple định danh nút để tie-break xác định tuyệt đối (Deterministic).

Bảo đảm vô hiệu hóa bộ đệm (Cache Invalidation) khi năng lượng/ngưỡng/blacklist thay đổi.
"""

from __future__ import annotations

from typing import Any, Sequence

from wsn_sim.network import Network


class RoutingEngine:
    """Cung cấp các thuật toán định tuyến MHR, EMHR, và S-EMHR theo đặc tả đề cương."""

    def __init__(
        self,
        network: Network,
        algorithm: str = "EMHR",
        alpha_energy: float = 0.20,
        epsilon: float = 1e-9,
    ) -> None:
        self.network = network
        self.algorithm = algorithm
        self.alpha_energy = float(alpha_energy)
        self.epsilon = float(epsilon)
        self.route_change_count: int = 0
        self._route_cache: dict[str, list[str]] = {}

    @property
    def threshold_j(self) -> float:
        """Ngưỡng năng lượng relay Eth = alpha_energy * E0 (mặc định 0.20 * 5.0 = 1.0 J)."""
        return self.alpha_energy * self.network.config.initial_energy_j

    def invalidate_cache(self, node_id: str | None = None) -> None:
        """Xóa cache đường đi khi mạng có sự thay đổi trạng thái."""
        if node_id is None:
            self._route_cache.clear()
        else:
            self._route_cache.pop(node_id, None)

    def compute_path_distance(self, path: Sequence[str]) -> float:
        """Tính tổng quãng đường Euclid của một lộ trình D(P) = sum d(u, v)."""
        total_dist = 0.0
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            if self.network.graph.has_edge(u, v):
                total_dist += float(self.network.graph[u][v].get("distance_m", 0.0))
            else:
                u_node = self.network.sensors.get(u) or self.network.sinks.get(u)
                v_node = self.network.sensors.get(v) or self.network.sinks.get(v)
                if u_node and v_node:
                    total_dist += float(u_node.distance_to(v_node))
        return total_dist

    def compute_energy_penalty(self, path: Sequence[str]) -> float:
        """Hàm phạt năng lượng của các sensor trong đường:

        Phi_E(P) = sum_{u in V(P) cap V_S} (E0 / (E_u + epsilon))
        """
        e0 = self.network.config.initial_energy_j
        penalty = 0.0
        for node_id in path:
            sensor = self.network.sensors.get(node_id)
            if sensor is not None:
                penalty += e0 / (sensor.energy_j + self.epsilon)
        return penalty

    def is_route_valid(
        self,
        route: list[str],
        algorithm: str = "EMHR",
        threshold_j: float | None = None,
        blacklist: set[str] | None = None,
    ) -> bool:
        """Kiểm tra xem lộ trình hiện tại còn hợp lệ để tiếp tục truyền dẫn hay không."""
        if not route or len(route) < 2:
            return False

        eth = self.threshold_j if threshold_j is None else float(threshold_j)
        bl = blacklist if blacklist is not None else set()

        src = self.network.sensors.get(route[0])
        if not src or not src.is_alive:
            return False

        if route[-1] not in self.network.sinks:
            return False

        for i in range(len(route) - 1):
            u, v = route[i], route[i + 1]
            if not self.network.graph.has_edge(u, v):
                return False

            if i > 0:
                relay = self.network.sensors.get(u)
                if not relay or not relay.is_alive:
                    return False
                if algorithm in ("EMHR", "S-EMHR") and relay.energy_j < eth:
                    return False
                if algorithm == "S-EMHR" and u in bl:
                    return False

        return True

    def _find_lexicographic_path(
        self,
        source_id: str,
        threshold_j: float | None = None,
        blacklist: set[str] | None = None,
    ) -> list[str] | None:
        """Thuật toán tìm đường Lexicographic hiệu năng cao bằng BFS Layering và DAG DP."""
        if source_id not in self.network.sensors:
            return None
        source_sensor = self.network.sensors[source_id]
        if not source_sensor.is_alive:
            return None

        sinks = set(self.network.sinks.keys())
        bl = blacklist if blacklist is not None else set()
        eth = self.threshold_j if threshold_j is None else float(threshold_j)
        e0 = self.network.config.initial_energy_j

        visited = {source_id}
        levels = [{source_id}]
        found_sinks: list[str] = []

        while levels[-1]:
            next_level: set[str] = set()
            for u in levels[-1]:
                for v in self.network.graph.neighbors(u):
                    if v in bl or v in visited:
                        continue
                    if v in sinks:
                        next_level.add(v)
                        visited.add(v)
                    else:
                        sensor = self.network.sensors.get(v)
                        is_ok = sensor.can_forward(eth) if threshold_j is not None else (sensor and sensor.is_alive)
                        if is_ok:
                            next_level.add(v)
                            visited.add(v)

            if not next_level:
                break

            levels.append(next_level)
            sinks_in_level = next_level & sinks
            if sinks_in_level:
                found_sinks = sorted(sinks_in_level)
                break

        if not found_sinks:
            return None

        h_star = len(levels) - 1

        dp: dict[str, tuple[float, float, list[str]]] = {source_id: (0.0, 0.0, [source_id])}

        for d in range(1, h_star + 1):
            for v in levels[d]:
                best_v: tuple[float, float, list[str]] | None = None
                v_penalty = (e0 / (self.network.sensors[v].energy_j + self.epsilon)) if v in self.network.sensors else 0.0

                for u in levels[d - 1]:
                    if u in dp and self.network.graph.has_edge(u, v):
                        u_dist, u_phi, u_path = dp[u]
                        edge_dist = self.network.graph[u][v].get("distance_m", 0.0)
                        cand = (
                            round(u_dist + edge_dist, 6),
                            round(u_phi + v_penalty, 6),
                            u_path + [v],
                        )
                        if best_v is None or cand < best_v:
                            best_v = cand

                if best_v is not None:
                    dp[v] = best_v

        best_overall: tuple[float, float, list[str]] | None = None
        for s in found_sinks:
            if s in dp:
                cand = dp[s]
                if best_overall is None or cand < best_overall:
                    best_overall = cand

        return best_overall[2] if best_overall else None

    def get_mhr_route(self, source_id: str) -> list[str] | None:
        """Minimum Hop Routing (MHR) baseline."""
        return self._find_lexicographic_path(source_id, threshold_j=None, blacklist=None)

    def get_emhr_route(
        self,
        source_id: str,
        threshold_j: float | None = None,
        blacklist: set[str] | None = None,
    ) -> list[str] | None:
        """Energy-aware Minimum-Hop Routing (EMHR) / S-EMHR."""
        eth = self.threshold_j if threshold_j is None else float(threshold_j)
        return self._find_lexicographic_path(source_id, threshold_j=eth, blacklist=blacklist)

    def get_semhr_route(
        self,
        source_id: str,
        blacklist: set[str],
        threshold_j: float | None = None,
    ) -> list[str] | None:
        """Security-aware EMHR: Tìm tuyến tối ưu bỏ qua các node nghi ngờ trong blacklist."""
        return self.get_emhr_route(source_id, threshold_j=threshold_j, blacklist=blacklist)

    def get_route(
        self,
        source_id: str,
        algorithm: str | None = None,
        blacklist: set[str] | None = None,
    ) -> list[str] | None:
        """Điều phối tìm tuyến theo thuật toán cấu hình có caching và tự động vô hiệu hóa cache."""
        algo = algorithm if algorithm is not None else self.algorithm
        bl = blacklist or set()

        cached = self._route_cache.get(source_id)
        if cached:
            if self.is_route_valid(cached, algorithm=algo, blacklist=bl):
                return list(cached)
            else:
                self.route_change_count += 1
                self._route_cache.pop(source_id, None)

        if algo == "MHR":
            route = self.get_mhr_route(source_id)
        elif algo in ("EMHR", "MHR-SF"):
            route = self.get_emhr_route(source_id, threshold_j=self.threshold_j)
        elif algo == "S-EMHR":
            route = self.get_semhr_route(source_id, blacklist=bl, threshold_j=self.threshold_j)
        else:
            route = self.get_emhr_route(source_id, threshold_j=self.threshold_j)

        if route:
            self._route_cache[source_id] = list(route)
        return route