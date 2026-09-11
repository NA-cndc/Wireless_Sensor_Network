"""Mô hình trạng thái và vòng đời của gói tin (Packet) trong mạng WSN."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class PacketStatus(str, Enum):
    """Các trạng thái trong vòng đời của một gói tin."""

    CREATED = "CREATED"  # Gói tin vừa được khởi tạo tại sensor nguồn
    IN_TRANSIT = "IN_TRANSIT"  # Gói tin đang được chuyển tiếp qua các nút trung gian
    DELIVERED = "DELIVERED"  # Gói tin đã đến được một trạm Sink an toàn
    DROPPED = "DROPPED"  # Gói tin bị hủy (do node cạn pin, mất gói kênh truyền hoặc tấn công)
    NO_ROUTE = "NO_ROUTE"  # Không tìm thấy đường đi khả thi tới bất kỳ trạm Sink nào


@dataclass(slots=True)
class Packet:
    """Đại diện cho một gói dữ liệu cảm biến và trạng thái theo dõi đường truyền.

    Tuân thủ bảng cấu trúc gói tin (Mục 3.7.3) trong đề cương nghiên cứu:
    - packet_id: Định danh duy nhất toàn cục của gói.
    - sequence_number: Số thứ tự gói của mỗi sensor (giúp Sink phát hiện gói bị mất).
    - source_id: ID của sensor tạo ra dữ liệu.
    - sink_id: ID của Sink đích được thuật toán định tuyến lựa chọn.
    - created_at: Mốc thời gian gói được sinh ra (giây).
    - size_bytes: Kích thước gói tin (mặc định 128 byte).
    - route: Tuyến đường chuyển tiếp [source, relay_1, relay_2, ..., sink].
    - current_hop_index: Vị trí chặng nhảy hiện tại của gói trên tuyến đường.
    - status: Trạng thái hiện thời của gói.
    - delivered_at: Mốc thời gian nhận gói tại trạm Sink.
    - drop_reason: Lý do cụ thể nếu gói bị hủy (natural_link_loss, selective_forwarding, energy_depletion, v.v.).
    """

    packet_id: str  # Định danh duy nhất của gói tin (ví dụ: 'pkt_sensor_001_1')
    source_id: str  # ID của sensor nguồn phát dữ liệu
    created_at: float  # Thời điểm sinh gói (giây)
    size_bytes: int  # Kích thước payload tính bằng byte (mặc định 128 byte)
    sequence_number: int = 0  # Số thứ tự tuần tự để sink theo dõi gói mất
    sink_id: str | None = None  # Trạm sink đích được chọn
    route: list[str] = field(default_factory=list)  # Danh sách ID các node trên đường đi
    current_hop_index: int = 0  # Chỉ số chặng đang đứng trên đường truyền
    status: PacketStatus = PacketStatus.CREATED  # Trạng thái vòng đời ban đầu
    delivered_at: float | None = None  # Thời điểm nhận thành công tại Sink
    drop_reason: str | None = None  # Ghi nhận nguyên nhân nếu bị mất gói

    def __post_init__(self) -> None:
        """Xác thực tính toàn vẹn của gói tin ngay sau khi tạo đối tượng."""
        if not self.packet_id:
            raise ValueError("packet_id must not be empty")
        if not self.source_id:
            raise ValueError("source_id must not be empty")
        if self.created_at < 0:
            raise ValueError("created_at must not be negative")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError("size_bytes must be an integer")
        if self.size_bytes <= 0:
            raise ValueError("size_bytes must be greater than zero")
        if self.sequence_number < 0:
            raise ValueError("sequence_number must not be negative")
        if self.route:
            route = list(self.route)
            self.route = []
            self.assign_route(route)
        if self.delivered_at is not None:
            self.mark_delivered(self.delivered_at)

    def assign_route(self, route: Sequence[str]) -> None:
        """Gán tuyến đường chuyển tiếp multi-hop cho gói tin.

        Quy tắc bắt buộc:
        - Tuyến đường không được rỗng.
        - Nút đầu tiên trong tuyến đường phải trùng với source_id của gói.
        - Gán tuyến thành công sẽ đưa trạng thái gói từ CREATED sang IN_TRANSIT.
        """
        route_nodes = list(route)
        if not route_nodes:
            raise ValueError("route must not be empty")
        if route_nodes[0] != self.source_id:
            raise ValueError("route must start at source_id")
        self.route = route_nodes
        self.current_hop_index = 0
        self.status = PacketStatus.IN_TRANSIT
        self.delivered_at = None
        self.drop_reason = None

    @property
    def hop_count(self) -> int:
        """Tính số chặng nhảy (số cạnh truyền dẫn) trên đường đi: số cạnh = len(route) - 1."""
        return max(0, len(self.route) - 1)

    @property
    def latency_s(self) -> float | None:
        """Tính độ trễ truyền gói đầu cuối (End-to-End Latency) = delivered_at - created_at."""
        if self.delivered_at is None:
            return None
        return self.delivered_at - self.created_at

    def mark_delivered(self, delivered_at: float) -> None:
        """Đánh dấu gói tin đã được giao tới Sink đích thành công.

        Args:
            delivered_at: Mốc thời gian nhận gói (không được nhỏ hơn thời gian tạo created_at).
        """
        if delivered_at < self.created_at:
            raise ValueError("delivered_at must not be earlier than created_at")
        self.delivered_at = delivered_at
        self.status = PacketStatus.DELIVERED
        self.drop_reason = None
        if self.route:
            self.current_hop_index = len(self.route) - 1

    def mark_dropped(self, reason: str, no_route: bool = False) -> None:
        """Đánh dấu gói tin bị hủy trên đường truyền hoặc không tìm thấy đường đi.

        Args:
            reason: Chuỗi mô tả nguyên nhân hủy (ví dụ: 'energy_depletion', 'selective_forwarding').
            no_route: Đặt True nếu lý do là đồ thị không có đường nối tới Sink.
        """
        if not reason:
            raise ValueError("drop reason must not be empty")
        self.status = PacketStatus.NO_ROUTE if no_route else PacketStatus.DROPPED
        self.drop_reason = reason
        self.delivered_at = None
