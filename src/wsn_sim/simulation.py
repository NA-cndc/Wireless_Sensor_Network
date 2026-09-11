"""Tích hợp công cụ mô phỏng sự kiện rời rạc SimPy cho mạng WSN."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import asdict, dataclass
from typing import Any

import simpy

from wsn_sim.network import Network


@dataclass(slots=True)
class SimulationResult:
    """Đóng gói kết quả đầu ra của phiên mô phỏng sự kiện rời rạc."""

    simulated_time_s: float  # Mốc thời gian mô phỏng kết thúc (giây)
    nodes: int  # Tổng số node trong mạng (457 nodes)
    sensors: int  # Tổng số nút cảm biến Sensor (450)
    sinks: int  # Tổng số trạm thu thập Sink (7)

    def to_dict(self) -> dict[str, Any]:
        """Chuyển đổi đối tượng kết quả thành dictionary để hiển thị JSON hoặc lưu file."""
        return asdict(self)


def run_smoke_simulation(network: Network, duration_s: float) -> SimulationResult:
    """Hàm tiện ích nhanh khởi tạo và thực thi mô phỏng SimPy trong duration_s giây.

    Args:
        network: Đối tượng mạng Network chứa topology các sensor và sink.
        duration_s: Thời lượng mô phỏng cần chạy (giây).

    Returns:
        Đối tượng SimulationResult chứa các chỉ số kết quả.
    """
    sim = Simulation(network)
    sim_time = sim.run_for(duration_s)
    return SimulationResult(
        simulated_time_s=sim_time,
        nodes=network.graph.number_of_nodes(),
        sensors=len(network.sensors),
        sinks=len(network.sinks),
    )


class Simulation:
    """Quản lý môi trường mô phỏng SimPy cho một topology mạng cảm biến nhất định."""

    def __init__(
        self,
        network: Network,
        env: simpy.Environment | None = None,
    ) -> None:
        """Khởi tạo phiên mô phỏng.

        Args:
            network: Đối tượng Network cần mô phỏng.
            env: Môi trường SimPy có sẵn hoặc khởi tạo môi trường simpy.Environment() mới.
        """
        self.network = network
        # Khởi tạo động cơ mô phỏng sự kiện rời rạc (Discrete-Event Simulator) của SimPy
        self.env = env if env is not None else simpy.Environment()

    def smoke_process(self, timeout_s: float) -> Generator[simpy.Event, None, None]:
        """Tiến trình mẫu (Generator) sinh sự kiện chờ timeout trong hàng đợi của SimPy.

        Sử dụng yield env.timeout() để nhường quyền điều khiển cho bộ lập lịch của SimPy
        nhảy mốc thời gian ảo tiến về phía trước một cách chính xác mà không tốn tài nguyên CPU.
        """
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        yield self.env.timeout(timeout_s)

    def run_for(self, duration_s: float) -> float:
        """Thúc đẩy đồng hồ mô phỏng SimPy tiến lên một khoảng thời gian duration_s.

        Args:
            duration_s: Khoảng thời gian mô phỏng tương đối (giây).

        Returns:
            Mốc thời gian hiện tại tuyệt đối của môi trường SimPy (env.now).
        """
        # Đăng ký tiến trình vào hàng đợi sự kiện của SimPy
        process = self.env.process(self.smoke_process(duration_s))
        # Kích hoạt vòng lặp xử lý sự kiện cho đến khi tiến trình kết thúc
        self.env.run(until=process)
        return float(self.env.now)
