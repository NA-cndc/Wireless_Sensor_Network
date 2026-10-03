"""Mô hình dữ liệu cho trạm thu thập (Sink Node) trong mạng WSN."""

from __future__ import annotations

from dataclasses import dataclass, field

from wsn_sim.models.packet import Packet


@dataclass(slots=True)
class Sink:
    """Đại diện cho trạm thu thập dữ liệu gốc (Sink Node) trong mô hình đa sink (7 sinks).

    Đặc điểm thiết kế theo đề cương:
    1. Không bị giới hạn về năng lượng (được cấp nguồn điện ngoài liên tục).
    2. Có cơ chế lọc và khử trùng lặp gói tin (Packet Deduplication) dựa trên ID duy nhất.
    """

    node_id: str
    x: float
    y: float

    received_packet_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        """Xác thực định danh nút không được rỗng."""
        if not self.node_id:
            raise ValueError("node_id must not be empty")

    def receive(self, packet: Packet, received_at: float) -> bool:
        """Tiếp nhận một gói tin khi nó di chuyển đến trạm Sink đích.

        Quy trình xử lý:
        1. Kiểm tra ID gói tin đã từng được ghi nhận tại sink này hay chưa.
        2. Nếu đã tồn tại -> Bỏ qua (tránh đếm lặp gói trùng bản sao).
        3. Nếu là gói mới -> Chuyển trạng thái gói sang DELIVERED, ghi nhận thời điểm đến,
           và thêm ID vào danh sách đã nhận.

        Args:
            packet: Gói tin đến trạm sink.
            received_at: Mốc thời gian mô phỏng (giây) tại thời điểm nhận.

        Returns:
            True nếu gói tin được nhận mới thành công; False nếu là gói trùng lặp.
        """
        if packet.packet_id in self.received_packet_ids:
            return False

        packet.mark_delivered(received_at)
        self.received_packet_ids.add(packet.packet_id)
        return True

    @property
    def received_packet_count(self) -> int:
        """Trả về tổng số lượng gói tin độc nhất (không trùng lặp) đã đến sink thành công."""
        return len(self.received_packet_ids)
