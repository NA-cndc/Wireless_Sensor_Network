"""Mô hình dữ liệu cho nút cảm biến (Sensor Node) trong mạng WSN."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Protocol


class PositionedNode(Protocol):
    """Giao diện (Protocol) định nghĩa các nút có tọa độ Descartes (x, y)."""

    x: float
    y: float


@dataclass(slots=True)
class Sensor:
    """Đại diện cho một nút cảm biến cố định, chịu ràng buộc về dung lượng pin giới hạn.

    Sử dụng slots=True để tối ưu hóa bộ nhớ RAM và tốc độ truy xuất thuộc tính
    khi mô phỏng quy mô lớn (450 sensor nodes).
    """

    node_id: str
    x: float
    y: float
    initial_energy_j: float
    energy_j: float | None = None
    is_alive: bool = True

    generated_packets: int = 0
    received_packets: int = 0
    forwarded_packets: int = 0
    dropped_packets: int = 0

    def __post_init__(self) -> None:
        """Kiểm tra tính hợp lệ của dữ liệu ngay sau khi khởi tạo đối tượng."""
        if not self.node_id:
            raise ValueError("node_id must not be empty")
        if self.initial_energy_j <= 0:
            raise ValueError("initial_energy_j must be greater than zero")
        if self.energy_j is None:
            self.energy_j = float(self.initial_energy_j)
        if self.energy_j < 0:
            raise ValueError("energy_j must not be negative")
        self.energy_j = float(self.energy_j)
        self.is_alive = self.energy_j > 0

    def distance_to(self, other: PositionedNode) -> float:
        """Tính khoảng cách hình học Euclid (mét) từ sensor này tới một nút khác.

        Công thức: d = sqrt((x1 - x2)^2 + (y1 - y2)^2)
        """
        return hypot(self.x - other.x, self.y - other.y)

    def consume_energy(self, amount_j: float) -> float:
        """Trừ bớt năng lượng tiêu thụ khi sensor thực hiện truyền (TX) hoặc nhận (RX) gói tin.

        Đảm bảo nguyên tắc bảo toàn năng lượng:
        - Năng lượng tiêu hao amount_j phải >= 0.
        - Năng lượng còn lại không bao giờ bị âm: E_new = max(0.0, E_old - amount_j).
        - Nếu năng lượng giảm về 0, tự động đánh dấu sensor đã chết (is_alive = False).

        Args:
            amount_j: Lượng năng lượng tiêu thụ tính bằng Joule.

        Returns:
            Năng lượng còn lại của sensor sau khi tiêu hao.
        """
        if amount_j < 0:
            raise ValueError("amount_j must not be negative")
        self.energy_j = max(0.0, self.energy_j - amount_j)
        self.is_alive = self.energy_j > 0
        return self.energy_j

    def can_forward(self, threshold_j: float) -> bool:
        """Kiểm tra xem sensor có đủ điều kiện làm nút chuyển tiếp (relay) hay không.

        Phục vụ trực tiếp cho thuật toán EMHR (Energy-aware Minimum-Hop Routing):
        Nút chỉ được phép làm relay khi:
        1. Nút vẫn còn sống (is_alive == True).
        2. Năng lượng còn lại lớn hơn hoặc bằng ngưỡng năng lượng an toàn (E_i >= threshold_j).

        Args:
            threshold_j: Ngưỡng năng lượng tối thiểu E_th (ví dụ: 20% của E_0 = 1.0 J).
        """
        if threshold_j < 0:
            raise ValueError("threshold_j must not be negative")
        return self.is_alive and self.energy_j >= threshold_j
