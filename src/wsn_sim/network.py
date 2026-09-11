"""Module quản lý không gian mạng WSN, sinh tọa độ ngẫu nhiên tái lập và xây dựng đồ thị liên kết."""

from __future__ import annotations

from math import hypot
from typing import Any

import networkx as nx
import numpy as np

from wsn_sim.config import SimulationConfig
from wsn_sim.models import Sensor, Sink


class Network:
    """Lớp quản lý toàn bộ các node cố định (Sensor, Sink) và đồ thị topology vô hướng NetworkX."""

    def __init__(
        self,
        config: SimulationConfig,
        communication_range_m: float | None = None,
    ) -> None:
        """Khởi tạo mạng WSN từ cấu hình thí nghiệm.

        Quy trình khởi tạo:
        1. Tiếp nhận cấu hình thí nghiệm (SimulationConfig).
        2. Sinh tọa độ ngẫu nhiên cho toàn bộ 450 sensors và 7 sinks dựa trên random seed.
        3. Xây dựng đồ thị liên kết ban đầu theo bán kính truyền thông được chỉ định.

        Args:
            config: Cấu hình tham số mô phỏng đã qua kiểm tra hợp lệ.
            communication_range_m: Bán kính truyền thông ban đầu (mét). Nếu bỏ trống,
                sẽ dùng bán kính đầu tiên trong cấu hình (mặc định 250m).
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
        """Sinh tọa độ phẳng ngẫu nhiên có kiểm soát hạt giống (Seed) trong vùng 3000m x 3000m.

        Đảm bảo tính tái lập (Reproducibility): Cùng một random seed (ví dụ: seed=42)
        sẽ luôn sinh ra đúng một bộ tọa độ giống hệt nhau trên mọi máy tính.
        """
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
        """Xây dựng lại đồ thị liên kết NetworkX theo bán kính truyền thông R.

        Nguyên tắc cốt lõi:
        - Tọa độ địa lý của các node được giữ nguyên tuyệt đối (không di chuyển nút).
        - Một cạnh liên kết được thiết lập khi khoảng cách Euclid giữa 2 node <= R.
        - Không thiết lập cạnh trực tiếp giữa Sink với Sink (các trạm thu thập độc lập).

        Args:
            communication_range_m: Bán kính truyền thông vô tuyến R (mét), yêu cầu R > 0.

        Returns:
            Đối tượng đồ thị vô hướng networkx.Graph mới.
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
                self._add_edge_if_in_range(graph, left, right, communication_range_m)

            for sink in sink_nodes:
                self._add_edge_if_in_range(graph, left, sink, communication_range_m)

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
        """Kiểm tra khoảng cách Euclid và tạo cạnh liên kết nếu khoảng cách <= R."""
        distance_m = hypot(left.x - right.x, left.y - right.y)
        if distance_m <= communication_range_m:
            graph.add_edge(
                left.node_id,
                right.node_id,
                distance_m=distance_m,
            )

    def neighbors(self, node_id: str) -> list[str]:
        """Trả về danh sách định danh (ID) các nút láng giềng kết nối trực tiếp với node_id."""
        if node_id not in self.graph:
            raise KeyError(f"unknown node_id: {node_id}")
        return sorted(self.graph.neighbors(node_id))

    def isolated_sensor_ids(self) -> list[str]:
        """Tìm các sensor bị cô lập hoàn toàn (bậc của đỉnh degree = 0, không có sóng tới ai)."""
        return sorted(node_id for node_id in self.sensors if self.graph.degree[node_id] == 0)

    def routable_sensor_ids(self) -> list[str]:
        """Xác định các sensor có khả năng truyền dữ liệu tới ít nhất một trạm Sink.

        Thuật toán phân tích các thành phần liên thông (connected components) trong đồ thị:
        Nếu một thành phần liên thông chứa ít nhất 1 trạm Sink, thì toàn bộ Sensor
        thuộc thành phần liên thông đó đều có đường truyền đến Sink.
        """
        routable: set[str] = set()
        sink_ids = set(self.sinks)
        for component in nx.connected_components(self.graph):
            if component & sink_ids:
                routable.update(component & self.sensors.keys())
        return sorted(routable)

    def topology_summary(self) -> dict[str, int | float]:
        """Tổng hợp các chỉ số thống kê cơ bản của mạng ở bán kính truyền hiện tại."""
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
        """Trả về bản sao bảng tra cứu tọa độ (x, y) của tất cả 457 node."""
        return {
            node_id: (float(data["x"]), float(data["y"]))
            for node_id, data in self.graph.nodes(data=True)
        }

    def build_virtual_super_sink_graph(self, virtual_sink_id: str = "virtual_sink") -> nx.Graph:
        """Tạo bản sao đồ thị có bổ sung nút Virtual Super-Sink kết nối tới cả 7 trạm Sink thật.

        Theo đặc tả đề cương (Mục 3.3):
        - Để tìm đường đi tối ưu từ một sensor tới *bất kỳ sink nào*, tạo một nút ảo (K_0).
        - Nối K_0 với tất cả 7 trạm sink bằng cạnh có chi phí/khoảng cách bằng 0.
        - Thuật toán định tuyến tìm đường ngắn nhất tới K_0, sau đó cắt bỏ cạnh ảo cuối cùng
          để thu được sink thật đích đến tối ưu nhất.

        Args:
            virtual_sink_id: Tên định danh cho nút siêu sink ảo (mặc định: 'virtual_sink').

        Returns:
            Đồ thị NetworkX mới chứa nút ảo K_0 và các cạnh ảo nối tới 7 sink.
        """
        v_graph = self.graph.copy()
        center_x = self.config.area_width_m / 2.0
        center_y = self.config.area_height_m / 2.0
        v_graph.add_node(
            virtual_sink_id,
            node_type="virtual_sink",
            x=center_x,
            y=center_y,
        )
        for sink_id in self.sinks:
            v_graph.add_edge(virtual_sink_id, sink_id, distance_m=0.0, weight=0.0)
        return v_graph

    def check_network_connectivity(self) -> dict[str, Any]:
        """Kiểm tra độ phủ sóng vô tuyến và đánh giá tiêu chí nghiệm thu liên thông mạng.

        Tiêu chí theo đề cương nghiên cứu:
        - Tỷ lệ sensor có đường đến ít nhất một sink phải đạt tối thiểu 95% (routable_ratio >= 0.95).

        Returns:
            Từ điển chứa: tổng số sensor, sink, số nút cô lập, số nút liên thông,
            tỷ lệ liên thông, cờ đạt ngưỡng 95% và kích thước cụm liên thông lớn nhất.
        """
        isolated = self.isolated_sensor_ids()
        routable = self.routable_sensor_ids()
        total_sensors = len(self.sensors)
        routable_ratio = (len(routable) / total_sensors) if total_sensors > 0 else 0.0

        components = list(nx.connected_components(self.graph))
        largest_comp_size = max((len(c) for c in components), default=0)

        return {
            "total_sensors": total_sensors,
            "total_sinks": len(self.sinks),
            "isolated_sensors_count": len(isolated),
            "isolated_sensor_ids": isolated,
            "routable_sensors_count": len(routable),
            "routable_ratio": routable_ratio,
            "meets_95_percent_threshold": routable_ratio >= 0.95,
            "connected_components_count": len(components),
            "largest_component_size": largest_comp_size,
        }
