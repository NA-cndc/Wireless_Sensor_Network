"""Routing algorithms for the WSN simulation: MHR and EMHR."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, Sequence

from wsn_sim.network import Network

if TYPE_CHECKING:
    from wsn_sim.energy import RadioModel


ENERGY_EPSILON_J = 1e-15


class RoutingEngine:
    """Cung cấp các thuật toán định tuyến MHR và EMHR."""

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
        """Hàm phạt năng lượng của các sensor trong đường."""
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
        is_source: bool = True,
        avoid_nodes: set[str] | Sequence[str] | None = None,
    ) -> bool:
        """Kiểm tra xem lộ trình hiện tại còn hợp lệ để tiếp tục truyền dẫn hay không."""
        # Tuyến đường hợp lệ phải có ít nhất 2 nút (nút gửi và nút nhận)
        if not route or len(route) < 2:
            return False

        eth = self.threshold_j if threshold_j is None else float(threshold_j)
        avoid = set(avoid_nodes) if avoid_nodes else set()

        # Nút đầu tiên trong tuyến phải tồn tại và còn sống
        src = self.network.sensors.get(route[0])
        if not src or not src.is_alive:
            return False

        # Nếu nút đầu tiên là một Relay (không phải nguồn gốc gói) trong EMHR: bắt buộc phải >= Eth
        if not is_source and algorithm == "EMHR" and not src.can_forward(eth):
            return False

        # Điểm kết thúc của tuyến đường bắt buộc phải là một trạm Sink thật
        if route[-1] not in self.network.sinks:
            return False

        # Duyệt từng chặng nhảy (hop) trên tuyến để kiểm tra tính toàn vẹn
        for i in range(len(route) - 1):
            u, v = route[i], route[i + 1]
            # Cạnh truyền thông vô tuyến giữa hai nút phải còn tồn tại trong bán kính R hiện tại
            if not self.network.graph.has_edge(u, v):
                return False

            # Nút tiếp theo không được nằm trong tập các nút cần né tránh (chống tạo vòng lặp)
            if v in avoid:
                return False

            # Các nút chuyển tiếp trung gian (i > 0) phải còn sống và đáp ứng điều kiện năng lượng
            if i > 0:
                relay = self.network.sensors.get(u)
                if not relay or not relay.is_alive:
                    return False
                # Đối với thuật toán EMHR, mọi relay bắt buộc phải có năng lượng >= Eth
                if algorithm == "EMHR" and not relay.can_forward(eth):
                    return False

        return True

    def _find_lexicographic_path(
        self,
        source_id: str,
        threshold_j: float | None = None,
        avoid_nodes: set[str] | Sequence[str] | None = None,
        is_source: bool = True,
    ) -> list[str] | None:
        """Thuật toán tìm đường Lexicographic hiệu năng cao bằng BFS Layering và DAG DP."""
        if source_id not in self.network.sensors:
            return None
        source_sensor = self.network.sensors[source_id]
        if not source_sensor.is_alive:
            return None
        # Nếu nguồn tìm đường là relay trong EMHR thì relay đó phải có năng lượng >= Eth
        if not is_source and threshold_j is not None and not source_sensor.can_forward(threshold_j):
            return None

        sinks = set(self.network.sinks.keys())
        eth = self.threshold_j if threshold_j is None else float(threshold_j)
        e0 = self.network.config.initial_energy_j

        # Giai đoạn 1: BFS Layering để tìm độ dài chặng nhảy tối thiểu h* tới trạm Sink gần nhất
        # Tập visited được khởi tạo chứa sẵn avoid_nodes để tuyệt đối không duyệt lại nút đã qua
        avoid = set(avoid_nodes) if avoid_nodes else set()
        visited = {source_id} | avoid
        levels = [{source_id}]
        found_sinks: list[str] = []

        while levels[-1]:
            next_level: set[str] = set()
            for u in levels[-1]:
                for v in self.network.graph.neighbors(u):
                    if v in visited:
                        continue
                    if v in sinks:
                        # Đã tiếp cận được trạm Sink ở tầng hiện tại
                        next_level.add(v)
                        visited.add(v)
                    else:
                        sensor = self.network.sensors.get(v)
                        # Lọc nút chuyển tiếp: EMHR yêu cầu pin >= Eth; MHR chỉ yêu cầu nút còn sống
                        is_ok = sensor.can_forward(eth) if threshold_j is not None else (sensor and sensor.is_alive)
                        if is_ok:
                            next_level.add(v)
                            visited.add(v)

            if not next_level:
                break

            levels.append(next_level)
            sinks_in_level = next_level & sinks
            # Dừng BFS ngay khi phát hiện Sink ở tầng nông nhất (đảm bảo số hop h* là nhỏ nhất)
            if sinks_in_level:
                found_sinks = sorted(sinks_in_level)
                break

        # Nếu không có Sink nào tiếp cận được trong đồ thị liên thông
        if not found_sinks:
            return None

        # Số chặng nhảy tối thiểu h* chính là số tầng BFS trừ đi tầng gốc 0
        h_star = len(levels) - 1

        # Giai đoạn 2: Quy hoạch động (DAG Dynamic Programming) trên các tầng BFS để tối ưu thứ tự từ điển
        # Trạng thái DP lưu: (tổng_khoảng_cách_D, hàm_phạt_năng_lượng_Phi, lộ_trình_path)
        dp: dict[str, tuple[float, float, list[str]]] = {source_id: (0.0, 0.0, [source_id])}

        for d in range(1, h_star + 1):
            for v in levels[d]:
                best_v: tuple[float, float, list[str]] | None = None
                # Hàm phạt năng lượng phi(v) = E0 / (E_v + epsilon) cho sensor; bằng 0 cho sink
                v_penalty = (e0 / (self.network.sensors[v].energy_j + self.epsilon)) if v in self.network.sensors else 0.0

                for u in levels[d - 1]:
                    if u in dp and self.network.graph.has_edge(u, v):
                        u_dist, u_phi, u_path = dp[u]
                        edge_dist = self.network.graph[u][v].get("distance_m", 0.0)
                        # So sánh bộ 3 mục tiêu theo thứ tự Lexicographic: khoảng cách D -> hàm phạt Phi -> lộ trình
                        cand = (
                            round(u_dist + edge_dist, 6),
                            round(u_phi + v_penalty, 6),
                            u_path + [v],
                        )
                        if best_v is None or cand < best_v:
                            best_v = cand

                if best_v is not None:
                    dp[v] = best_v

        # Chọn đường đi tối ưu nhất trong số các Sink cùng đạt số hop nhỏ nhất h*
        best_overall: tuple[float, float, list[str]] | None = None
        for s in found_sinks:
            if s in dp:
                cand = dp[s]
                if best_overall is None or cand < best_overall:
                    best_overall = cand

        return best_overall[2] if best_overall else None

    def get_mhr_route(
        self,
        source_id: str,
        avoid_nodes: set[str] | Sequence[str] | None = None,
        is_source: bool = True,
    ) -> list[str] | None:
        """Thuật toán MHR: Minimum Hop Routing (không ràng buộc ngưỡng năng lượng Eth)."""
        return self._find_lexicographic_path(source_id, threshold_j=None, avoid_nodes=avoid_nodes, is_source=is_source)

    def get_emhr_route(
        self,
        source_id: str,
        threshold_j: float | None = None,
        avoid_nodes: set[str] | Sequence[str] | None = None,
        is_source: bool = True,
    ) -> list[str] | None:
        """Thuật toán EMHR: Energy-aware Minimum-Hop Routing (loại các relay có pin < Eth)."""
        eth = self.threshold_j if threshold_j is None else float(threshold_j)
        return self._find_lexicographic_path(source_id, threshold_j=eth, avoid_nodes=avoid_nodes, is_source=is_source)

    def get_route(
        self,
        source_id: str,
        algorithm: str | None = None,
        avoid_nodes: set[str] | Sequence[str] | None = None,
        is_source: bool = True,
    ) -> list[str] | None:
        """Điều phối tìm tuyến theo thuật toán cấu hình có caching và tự động vô hiệu hóa cache."""
        algo = algorithm if algorithm is not None else self.algorithm
        avoid = set(avoid_nodes) if avoid_nodes else set()

        # Cache đường đi chỉ áp dụng cho truy vấn nguồn gốc không có ràng buộc tránh node
        if not avoid and is_source:
            cached = self._route_cache.get(source_id)
            if cached:
                # Kiểm tra tuyến trong cache còn hợp lệ hay không trước khi tái sử dụng
                if self.is_route_valid(cached, algorithm=algo, is_source=True):
                    return list(cached)
                else:
                    self.route_change_count += 1
                    self._route_cache.pop(source_id, None)

        # Tính toán đường đi mới theo thuật toán được chọn
        if algo == "MHR":
            route = self.get_mhr_route(source_id, avoid_nodes=avoid, is_source=is_source)
        else:
            route = self.get_emhr_route(source_id, threshold_j=self.threshold_j, avoid_nodes=avoid, is_source=is_source)

        # Chỉ lưu vào bộ nhớ đệm cache nếu tuyến không bị giới hạn bởi tập avoid_nodes
        if route and not avoid and is_source:
            self._route_cache[source_id] = list(route)
        return route

    def transmission_feasibility_snapshot(
        self,
        radio: RadioModel,
        packet_size_bytes: int,
        time_s: float,
    ) -> dict[str, Any]:
        """Evaluate one-packet reachability without mutating routing or batteries.

        ``routing_eligible`` applies the current MHR/EMHR relay rule, but does not
        debit energy. ``energy_feasible`` additionally requires enough energy for
        every TX and RX on one path.  Each source is evaluated independently at
        this snapshot, so the result is diagnostic and is not a promise that all
        listed sources can deliver concurrently or in the future.
        """
        if packet_size_bytes <= 0:
            raise ValueError('packet_size_bytes must be greater than zero')

        alive_ids = {
            node_id
            for node_id, sensor in self.network.sensors.items()
            if sensor.is_alive
        }
        sink_ids = set(self.network.sinks)
        packet_bits = packet_size_bytes * 8
        rx_cost = radio.compute_rx_energy(packet_bits)
        threshold = self.threshold_j

        def sender_can_transmit(
            node_id: str,
            next_id: str,
            *,
            is_source: bool,
            include_energy: bool,
        ) -> bool:
            sensor = self.network.sensors[node_id]
            if not sensor.is_alive:
                return False
            if (
                not is_source
                and self.algorithm == 'EMHR'
                and not sensor.can_forward(threshold)
            ):
                return False
            if not include_energy:
                return True
            edge_data = self.network.graph[node_id][next_id]
            distance_value = edge_data.get('distance_m')
            if distance_value is None:
                receiver = self.network.sensors.get(next_id)
                if receiver is None:
                    receiver = self.network.sinks.get(next_id)
                if receiver is None:
                    raise ValueError(
                        f'Cannot determine distance from {node_id!r} to '
                        f'unknown receiver {next_id!r}'
                    )
                distance = sensor.distance_to(receiver)
            else:
                distance = float(distance_value)
            tx_cost = radio.compute_tx_energy(packet_bits, distance)
            available = sensor.energy_j if is_source else sensor.energy_j - rx_cost
            if (
                not is_source
                and self.algorithm == 'EMHR'
                and available < threshold - ENERGY_EPSILON_J
            ):
                return False
            return available >= tx_cost - ENERGY_EPSILON_J

        def has_path(source_id: str, *, include_energy: bool) -> bool:
            queue = deque([source_id])
            visited = {source_id}
            while queue:
                current = queue.popleft()
                for neighbor in sorted(self.network.graph.neighbors(current)):
                    if neighbor in visited:
                        continue
                    if not sender_can_transmit(
                        current,
                        neighbor,
                        is_source=current == source_id,
                        include_energy=include_energy,
                    ):
                        continue
                    if neighbor in sink_ids:
                        return True
                    receiver = self.network.sensors.get(neighbor)
                    if receiver is None or not receiver.is_alive:
                        continue
                    if (
                        include_energy
                        and receiver.energy_j < rx_cost - ENERGY_EPSILON_J
                    ):
                        continue
                    visited.add(neighbor)
                    queue.append(neighbor)
            return False

        routing_ids = {
            source_id
            for source_id in alive_ids
            if has_path(source_id, include_energy=False)
        }
        feasible_ids = {
            source_id
            for source_id in alive_ids
            if has_path(source_id, include_energy=True)
        }
        alive_count = len(alive_ids)

        def ratio(count: int) -> float | None:
            return count / alive_count if alive_count else None

        return {
            'time_s': float(time_s),
            'alive_sensors': alive_count,
            'routing_eligible_sensors': len(routing_ids),
            'routing_eligible_ratio': ratio(len(routing_ids)),
            'energy_feasible_sensors': len(feasible_ids),
            'energy_feasible_ratio': ratio(len(feasible_ids)),
            'routing_eligible_sensor_ids': sorted(routing_ids),
            'energy_feasible_sensor_ids': sorted(feasible_ids),
            'state': (
                'all_dead'
                if alive_count == 0
                else 'operational'
                if len(feasible_ids) == alive_count
                else 'partially_feasible'
                if feasible_ids
                else 'none_feasible'
            ),
            'definition': (
                'independent_one_packet_snapshot_with_tx_rx_energy_and_'
                f'{self.algorithm.lower()}_relay_rules_not_future_delivery_guarantee'
            ),
        }
