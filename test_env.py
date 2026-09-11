"""Kịch bản kiểm thử độc lập môi trường mạng và tính tái lập của Random Seed.

Có thể chạy trực tiếp bằng lệnh:
    python test_env.py
Hoặc chạy trong bộ pytest:
    python -m pytest tests/test_environment.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network


class TestEnvironment(unittest.TestCase):
    """Bộ kiểm thử xác thực các hằng số môi trường và tính tái lập 100% của Random Seed."""

    def setUp(self) -> None:
        """Hàm thiết lập ban đầu: Tự động nạp file cấu hình chuẩn 'configs/default.json'."""
        config_path = Path(__file__).resolve().parent / "configs" / "default.json"
        self.config = SimulationConfig.from_json(config_path)

    def test_config_values(self) -> None:
        """Kiểm tra toàn bộ các hằng số môi trường có đúng với đặc tả kỹ thuật của đề tài hay không."""
        self.assertEqual(self.config.num_sensors, 450)
        self.assertEqual(self.config.num_sinks, 7)
        self.assertEqual(self.config.area_width_m, 3000.0)
        self.assertEqual(self.config.area_height_m, 3000.0)
        self.assertIn(300.0, self.config.communication_ranges_m)
        self.assertEqual(self.config.initial_energy_j, 5.0)

    def test_random_seed_reproducibility(self) -> None:
        """Kiểm thử tính tái lập (Reproducibility): Sinh mạng 2 lần độc lập với cùng Seed phải giống hệt nhau."""
        net1 = Network(self.config, communication_range_m=300.0)
        coords1 = net1.coordinates()

        net2 = Network(self.config, communication_range_m=300.0)
        coords2 = net2.coordinates()

        self.assertEqual(coords1, coords2)
        self.assertEqual(set(net1.graph.edges()), set(net2.graph.edges()))
        print(
            f"[OK] Tái lập thành công: 457 nodes ({len(net1.sensors)} sensors + {len(net1.sinks)} sinks)"
        )

    def test_network_connectivity(self) -> None:
        """Kiểm tra độ phủ sóng và tỷ lệ liên thông: Phải có ít nhất 95% sensor tiếp cận được Sink."""
        net = Network(self.config, communication_range_m=300.0)
        conn = net.check_network_connectivity()

        self.assertTrue(conn["meets_95_percent_threshold"])
        print(
            f"[OK] Liên thông mạng: {conn['routable_sensors_count']}/{conn['total_sensors']} "
            f"sensors ({conn['routable_ratio'] * 100:.1f}%)"
        )


if __name__ == "__main__":
    unittest.main()
