"""Module điều phối chính của mô phỏng WSN bằng SimPy (Hợp nhất hoàn chỉnh)."""

from __future__ import annotations

import csv
from collections.abc import Generator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import simpy

from wsn_sim.config import SimulationConfig
from wsn_sim.detection import TrustDetector
from wsn_sim.energy import RadioModel
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.traffic import TrafficGenerator


@dataclass(slots=True)
class SimulationResult:
    """Đóng gói kết quả đầu ra của phiên mô phỏng sự kiện rời rạc."""

    simulated_time_s: float
    nodes: int
    sensors: int
    sinks: int
    metrics: dict[str, Any] | None = None

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
    sim = Simulation(network, enable_traffic=False)
    sim_time = sim.run_for(duration_s)
    return SimulationResult(
        simulated_time_s=sim_time,
        nodes=network.graph.number_of_nodes(),
        sensors=len(network.sensors),
        sinks=len(network.sinks),
    )


class Simulation:
    """Quản lý toàn bộ vòng đời và tiến trình mô phỏng mạng cảm biến.

    Tương thích đồng thời hai kiểu gọi:
    1. Simulation(network, env=...) (từ demo, test_simulation)
    2. Simulation(config, current_range_m=..., env=...) (từ main đa tiến trình)
    """

    def __init__(
        self,
        target: Network | SimulationConfig,
        env: simpy.Environment | None = None,
        *,
        current_range_m: float | None = None,
        range_m: float | None = None,
        config: SimulationConfig | None = None,
        routing_algorithm: str = "EMHR",
        alpha_energy: float = 0.20,
        attacker_ratio: float = 0.0,
        drop_prob: float = 0.0,
        channel_loss_prob: float = 0.0,
        enable_traffic: bool = True,
        csv_log_path: str | Path | None = None,
        quiet: bool = True,
        seed: int | None = None,
    ) -> None:
        self.env = env if env is not None else simpy.Environment()
        self.quiet = quiet
        self.csv_log_path = Path(csv_log_path) if csv_log_path else None

        effective_range = range_m if current_range_m is None else current_range_m

        if isinstance(target, Network):
            self.network = target
            self.config = config if config is not None else target.config
            if effective_range is not None and effective_range != self.network.communication_range_m:
                self.network.build_graph(effective_range)
        elif isinstance(target, SimulationConfig):
            self.config = target
            r = effective_range if effective_range is not None else target.communication_ranges_m[0]
            self.network = Network(self.config, communication_range_m=r)
        else:
            raise TypeError(f"target must be Network or SimulationConfig, got {type(target)}")

        self.routing_algorithm = routing_algorithm
        self.alpha_energy = alpha_energy
        self.attacker_ratio = attacker_ratio
        self.drop_prob = drop_prob
        self.channel_loss_prob = channel_loss_prob

        self.router = RoutingEngine(
            self.network,
            algorithm=self.routing_algorithm,
            alpha_energy=self.alpha_energy,
        )
        self.radio = RadioModel()
        self.detector = TrustDetector()

        self.enable_traffic = enable_traffic
        if self.enable_traffic:
            self.traffic_gen = TrafficGenerator(
                env=self.env,
                network=self.network,
                router=self.router,
                radio=self.radio,
                config=self.config,
                attacker_ratio=self.attacker_ratio,
                drop_prob=self.drop_prob,
                channel_loss_prob=self.channel_loss_prob,
                detector=self.detector,
                traffic_seed=seed,
            )
            self.traffic_gen.start()
            if self.csv_log_path is not None:
                self.env.process(self._monitor_network())
        else:
            self.traffic_gen = None

    def smoke_process(self, timeout_s: float) -> Generator[simpy.Event, None, None]:
        """Tiến trình mẫu sinh sự kiện chờ timeout trong hàng đợi của SimPy."""
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        yield self.env.timeout(timeout_s)

    def run_for(self, duration_s: float) -> float:
        """Tua nhanh mô phỏng thêm một khoảng thời gian duration_s.

        Args:
            duration_s: Số giây muốn chạy mô phỏng.

        Returns:
            Thời gian tuyệt đối của hệ thống sau khi chạy xong (env.now).
        """
        if duration_s <= 0:
            raise ValueError("duration_s must be greater than zero")

        target_time = self.env.now + duration_s
        self.env.process(self.smoke_process(duration_s))
        self.env.run(until=target_time)

        if not self.quiet and self.enable_traffic:
            self._print_summary()

        return float(self.env.now)

    def _monitor_network(self) -> Generator[simpy.Event, None, None]:
        """Tiến trình giám sát: Ghi log chỉ số định kỳ ra file CSV."""
        if self.csv_log_path is None:
            return

        self.csv_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.csv_log_path.open(mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([
                "Time_s", "Alive_Nodes", "Total_Energy_J",
                "Generated_Packets", "Delivered_Packets", "Dropped_Packets", "Avg_Latency_s"
            ])

            while True:
                alive_nodes = len([s for s in self.network.sensors.values() if s.is_alive])
                total_energy = sum(s.energy_j for s in self.network.sensors.values())

                gen_count = len(self.traffic_gen.generated_packets) if self.traffic_gen else 0
                deliv_count = len(self.traffic_gen.delivered_packets) if self.traffic_gen else 0
                drop_count = len(self.traffic_gen.dropped_packets) if self.traffic_gen else 0

                if deliv_count > 0 and self.traffic_gen and self.traffic_gen.delivered_latencies:
                    avg_latency = sum(self.traffic_gen.delivered_latencies) / deliv_count
                else:
                    avg_latency = 0.0

                if not self.quiet:
                    print(
                        f"[{self.env.now:05.1f}s] Sống: {alive_nodes:3d} | "
                        f"Gửi: {gen_count} | Tới: {deliv_count} | Rớt: {drop_count} | Trễ: {avg_latency:.4f}s"
                    )

                writer.writerow([
                    round(self.env.now, 1),
                    alive_nodes,
                    round(total_energy, 4),
                    gen_count,
                    deliv_count,
                    drop_count,
                    round(avg_latency, 5),
                ])
                file.flush()

                if alive_nodes == 0:
                    break

                yield self.env.timeout(10.0)

    def _print_summary(self) -> None:
        """In báo cáo khi mô phỏng tạm dừng."""
        if not self.traffic_gen:
            return
        total_generated = len(self.traffic_gen.generated_packets)
        alive_nodes = len([s for s in self.network.sensors.values() if s.is_alive])

        print("-" * 40)
        print(f"[TẠM DỪNG] Tại giây thứ {self.env.now:.1f}")
        print(f" -> Cảm biến còn sống : {alive_nodes}/{self.config.num_sensors}")
        print(f" -> Gói tin đã sinh   : {total_generated}")
        print("-" * 40)

    def get_metrics(self) -> dict[str, Any]:
        """Tính toán và trả về toàn bộ bộ chỉ số của mô phỏng."""
        from wsn_sim.metrics import calculate_simulation_metrics

        if not self.traffic_gen:
            return {
                "simulated_time_s": float(self.env.now),
                "nodes": self.network.graph.number_of_nodes(),
                "sensors": len(self.network.sensors),
                "sinks": len(self.network.sinks),
            }
        return calculate_simulation_metrics(
            network=self.network,
            traffic_gen=self.traffic_gen,
            radio=self.radio,
            sim_time_s=float(self.env.now),
            router=self.router,
            detector=self.detector,
        )

    def export_results(self, output_dir: str | Path) -> dict[str, Path]:
        """Xuất toàn bộ dữ liệu raw CSV và JSON ra thư mục độc lập."""
        from wsn_sim.storage import create_run_manifest, save_json

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        saved_files: dict[str, Path] = {}

        cfg_path = out_path / "config.json"
        save_json(self.config.to_dict(), cfg_path)
        saved_files["config"] = cfg_path

        metrics = self.get_metrics()
        metrics_path = out_path / "metrics.json"
        save_json(metrics, metrics_path)
        saved_files["metrics"] = metrics_path

        nodes_csv_path = out_path / "nodes.csv"
        with nodes_csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "node_id", "type", "x", "y", "initial_energy_j", "energy_j",
                "is_alive", "generated_packets", "received_packets",
                "forwarded_packets", "dropped_packets", "tx_energy_total_j", "rx_energy_total_j"
            ])
            for s in self.network.sensors.values():
                writer.writerow([
                    s.node_id, "sensor", s.x, s.y, s.initial_energy_j, s.energy_j,
                    s.is_alive, s.generated_packets, s.received_packets,
                    s.forwarded_packets, s.dropped_packets, s.tx_energy_total_j, s.rx_energy_total_j
                ])
            for k in self.network.sinks.values():
                writer.writerow([
                    k.node_id, "sink", k.x, k.y, "unlimited", "unlimited",
                    True, 0, k.received_packet_count, 0, 0, 0.0, 0.0
                ])
        saved_files["nodes"] = nodes_csv_path

        packets_csv_path = out_path / "packets.csv"
        with packets_csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "packet_id", "sequence_number", "source_id", "sink_id",
                "created_at", "delivered_at", "latency_s", "hop_count",
                "status", "drop_reason", "drop_node_id", "route", "path"
            ])
            all_pkts = []
            if self.traffic_gen:
                all_pkts.extend(self.traffic_gen.delivered_packets)
                all_pkts.extend(self.traffic_gen.dropped_packets)
            all_pkts.sort(key=lambda p: (p.source_id, p.sequence_number, p.created_at))
            for p in all_pkts:
                writer.writerow([
                    p.packet_id, p.sequence_number, p.source_id, p.sink_id or "",
                    p.created_at, p.delivered_at if p.delivered_at is not None else "",
                    p.latency_s if p.latency_s is not None else "",
                    p.hop_count, p.status.value, p.drop_reason or "",
                    p.drop_node_id or "", "->".join(p.route), "->".join(p.path)
                ])
        saved_files["packets"] = packets_csv_path

        ledger_path = out_path / "energy_ledger.csv"
        with ledger_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "time_s", "packet_id", "sender_id", "receiver_id", "distance_m",
                "tx_energy_j", "rx_energy_j", "success", "reason"
            ])
            for entry in self.radio.energy_ledger:
                writer.writerow([
                    entry.get("time_s"), entry.get("packet_id"), entry.get("sender_id"),
                    entry.get("receiver_id"), entry.get("distance_m"),
                    entry.get("tx_energy_j"), entry.get("rx_energy_j"),
                    entry.get("success"), entry.get("reason")
                ])
        saved_files["energy_ledger"] = ledger_path

        manifest_path = out_path / "run_manifest.json"
        manifest = create_run_manifest(
            self.config,
            [p.name for p in saved_files.values()],
            Path.cwd(),
        )
        save_json(manifest, manifest_path)
        saved_files["manifest"] = manifest_path

        return saved_files