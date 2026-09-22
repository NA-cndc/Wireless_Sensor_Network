"""Routing algorithms for the WSN simulation."""

from __future__ import annotations

import random
import networkx as nx

from wsn_sim.network import Network

class RoutingEngine:
    """Cung cấp các chiến lược định tuyến cho gói tin trong mạng WSN."""

    def __init__(self, network: Network) -> None:
        self.network = network

    def get_mhr_route(self, source_id: str) -> list[str] | None:
        """
        Minimum Hop Routing (MHR).
        Tìm đường đi ngắn nhất (ít hop nhất) đến bất kỳ trạm Sink nào.
        Nếu có nhiều đường cùng số hop, chọn ngẫu nhiên để cân bằng tải.
        """
        if source_id not in self.network.graph:
            return None

        sink_ids = set(self.network.sinks.keys())
        
        # 1. Tính số bước nhảy (hops) từ source đến tất cả các node trong mạng
        try:
            distances = nx.single_source_shortest_path_length(
                self.network.graph, source_id
            )
        except nx.NodeNotFound:
            return None

        # 2. Lọc ra danh sách các trạm Sink có thể kết nối được
        reachable_sinks_dists = {
            node: dist for node, dist in distances.items() if node in sink_ids
        }
        
        # Nếu không có Sink nào nằm trong tầm với -> Nút bị cô lập
        if not reachable_sinks_dists:
            return None

        # 3. Tìm mức hop thấp nhất và thu thập các trạm Sink đạt mức này
        min_hops = min(reachable_sinks_dists.values())
        closest_sinks = [
            node for node, dist in reachable_sinks_dists.items() if dist == min_hops
        ]

        # 4. Thu thập TẤT CẢ các con đường tối ưu đi đến các trạm Sink gần nhất
        all_optimal_paths = []
        for sink in closest_sinks:
            paths = list(nx.all_shortest_paths(
                self.network.graph, source=source_id, target=sink
            ))
            all_optimal_paths.extend(paths)

        # 5. Rút thăm ngẫu nhiên 1 lộ trình trong danh sách tối ưu
        if not all_optimal_paths:
            return None
            
        return random.choice(all_optimal_paths)

    def get_emhr_route(self, source_id: str, threshold_j: float = 0.5) -> list[str] | None:
        """
        Energy-aware Minimum Hop Routing (EMHR).
        Tìm lộ trình ít trạm nhất nhưng BỎ QUA các trạm trung gian có pin dưới ngưỡng.
        """
        if source_id not in self.network.graph:
            return None

        # 1. Định nghĩa bộ lọc node: Chỉ giữ lại Sink, Node nguồn, và Sensor đủ pin
        def is_eligible(node_id: str) -> bool:
            if node_id in self.network.sinks:
                return True
            if node_id == source_id:
                return True  # Node nguồn luôn được phép gửi gói tin của chính nó
                
            sensor = self.network.sensors.get(node_id)
            if sensor:
                # Gọi hàm can_forward của OOP để kiểm tra mức năng lượng
                return sensor.can_forward(threshold_j)
            return False

        # 2. Tạo một đồ thị "ảo" chỉ chứa các node khỏe mạnh
        valid_graph = nx.subgraph_view(self.network.graph, filter_node=is_eligible)

        # Trạng thái cô lập: Nguồn không còn kết nối trong mạng lưới khỏe mạnh
        if source_id not in valid_graph:
            return None

        sink_ids = set(self.network.sinks.keys())
        
        # 3. Chạy thuật toán tìm đường trên đồ thị ảo
        try:
            distances = nx.single_source_shortest_path_length(valid_graph, source_id)
        except nx.NodeNotFound:
            return None

        reachable_sinks_dists = {
            node: dist for node, dist in distances.items() if node in sink_ids
        }
        
        if not reachable_sinks_dists:
            return None

        min_hops = min(reachable_sinks_dists.values())
        closest_sinks = [
            node for node, dist in reachable_sinks_dists.items() if dist == min_hops
        ]

        all_optimal_paths = []
        for sink in closest_sinks:
            paths = list(nx.all_shortest_paths(
                valid_graph, source=source_id, target=sink
            ))
            all_optimal_paths.extend(paths)

        if not all_optimal_paths:
            return None
            
        # Chọn ngẫu nhiên 1 đường để cân bằng tải (Load Balancing)
        return random.choice(all_optimal_paths)