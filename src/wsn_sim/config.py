"""Module nạp, kiểm tra tính hợp lệ và quản lý cấu hình thí nghiệm WSN."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

REQUIRED_COMMUNICATION_RANGES_M = {250.0, 300.0, 350.0}
ENERGY_FAILURE_POLICIES = {"reject_without_debit", "partial_debit"}


def _require_positive_number(name: str, value: object) -> None:
    """Kiểm tra một giá trị bắt buộc phải là số dương (int hoặc float > 0)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _require_positive_integer(name: str, value: object) -> None:
    """Kiểm tra một giá trị bắt buộc phải là số nguyên dương (int > 0)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Lưu trữ và xác thực toàn bộ các tham số đầu vào của mô phỏng WSN.

    frozen=True: Đảm bảo cấu hình là bất biến (Immutable), tránh việc vô tình sửa đổi tham số
    trong quá trình đang chạy mô phỏng.
    """

    area_width_m: float  # Chiều rộng vùng quan sát (mét, ví dụ: 3000.0 m)
    area_height_m: float  # Chiều cao vùng quan sát (mét, ví dụ: 3000.0 m)
    num_sensors: int  # Tổng số nút cảm biến trong mạng (ví dụ: 450 nút)
    num_sinks: int  # Tổng số trạm thu thập dữ liệu (ví dụ: 7 sinks)
    initial_energy_j: float  # Mức năng lượng pin ban đầu của mỗi sensor (Joule, ví dụ: 5.0 J)
    packet_size_bytes: int  # Kích thước mỗi gói dữ liệu (byte, ví dụ: 128 bytes = 1024 bits)
    packet_interval_s: float  # Chu kỳ sinh gói tin định kỳ của mỗi sensor (giây, ví dụ: 10.0 s)
    communication_ranges_m: tuple[float, ...]  # Bộ bán kính phủ sóng vô tuyến (mét: bắt buộc có 250, 300, 350 m)
    seed: int  # Hạt giống khởi tạo số ngẫu nhiên (đảm bảo tái lập hoàn toàn topology)
    payload_size_bytes: int | None = None
    energy_failure_policy: str = "reject_without_debit"

    def __post_init__(self) -> None:
        """Thực hiện kiểm tra nghiêm ngặt kiểu dữ liệu và miền giá trị logic."""
        # Xác thực kích thước không gian mô phỏng phải là số dương (> 0 mét)
        _require_positive_number("area_width_m", self.area_width_m)
        _require_positive_number("area_height_m", self.area_height_m)

        # Xác thực số lượng nút cảm biến và sink phải là số nguyên dương
        _require_positive_integer("num_sensors", self.num_sensors)
        _require_positive_integer("num_sinks", self.num_sinks)

        # Xác thực mức pin ban đầu (> 0 Joule), kích thước gói (> 0 byte) và chu kỳ sinh gói (> 0 giây)
        _require_positive_number("initial_energy_j", self.initial_energy_j)
        _require_positive_integer("packet_size_bytes", self.packet_size_bytes)
        _require_positive_number("packet_interval_s", self.packet_interval_s)

        payload_size = self.packet_size_bytes if self.payload_size_bytes is None else self.payload_size_bytes
        if isinstance(payload_size, bool) or not isinstance(payload_size, int):
            raise TypeError("payload_size_bytes must be an integer")
        if payload_size < 0:
            raise ValueError("payload_size_bytes must not be negative")
        if payload_size > self.packet_size_bytes:
            raise ValueError("payload_size_bytes must not exceed packet_size_bytes")
        object.__setattr__(self, "payload_size_bytes", payload_size)

        if self.energy_failure_policy not in ENERGY_FAILURE_POLICIES:
            allowed = ", ".join(sorted(ENERGY_FAILURE_POLICIES))
            raise ValueError(f"energy_failure_policy must be one of: {allowed}")

        # Kiểm tra hạt giống ngẫu nhiên (seed) phải là số nguyên
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an integer")

        # Kiểm tra danh sách bán kính truyền thông phải là tuple không rỗng, chứa các số dương
        if not isinstance(self.communication_ranges_m, tuple):
            raise TypeError("communication_ranges_m must be a tuple")
        if not self.communication_ranges_m:
            raise ValueError("communication_ranges_m must not be empty")
        for radius in self.communication_ranges_m:
            _require_positive_number("communication range", radius)

        # Yêu cầu bắt buộc theo đề cương: phải bao phủ đầy đủ 3 kịch bản bán kính 250m, 300m và 350m
        if not REQUIRED_COMMUNICATION_RANGES_M.issubset(set(self.communication_ranges_m)):
            raise ValueError("communication_ranges_m must contain 250, 300, and 350")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SimulationConfig:
        """Tạo đối tượng SimulationConfig từ một từ điển (dictionary/mapping).

        Kiểm tra sự hiện diện đầy đủ của tất cả các trường cấu hình bắt buộc.
        """
        if not isinstance(data, Mapping):
            raise TypeError("configuration must be a mapping")

        required_fields = {
            "area_width_m",
            "area_height_m",
            "num_sensors",
            "num_sinks",
            "initial_energy_j",
            "packet_size_bytes",
            "packet_interval_s",
            "communication_ranges_m",
            "seed",
        }
        missing = sorted(required_fields.difference(data))
        if missing:
            raise ValueError(f"missing configuration fields: {', '.join(missing)}")

        ranges = data["communication_ranges_m"]
        if not isinstance(ranges, (list, tuple)):
            raise TypeError("communication_ranges_m must be a list or tuple")

        return cls(
            area_width_m=data["area_width_m"],
            area_height_m=data["area_height_m"],
            num_sensors=data["num_sensors"],
            num_sinks=data["num_sinks"],
            initial_energy_j=data["initial_energy_j"],
            packet_size_bytes=data["packet_size_bytes"],
            packet_interval_s=data["packet_interval_s"],
            communication_ranges_m=tuple(ranges),
            seed=data["seed"],
            payload_size_bytes=data.get("payload_size_bytes"),
            energy_failure_policy=data.get(
                "energy_failure_policy", "reject_without_debit"
            ),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> SimulationConfig:
        """Đọc và phân tích cú pháp tệp JSON (chuẩn mã hóa UTF-8) thành đối tượng cấu hình."""
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi cấu hình thành dictionary có thể chuyển tiếp thành chuỗi JSON."""
        data = asdict(self)
        data["communication_ranges_m"] = list(self.communication_ranges_m)
        return data
