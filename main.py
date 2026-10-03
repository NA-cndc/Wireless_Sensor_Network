"""File chạy chính thức của mô phỏng WSN giai đoạn chuyển tiếp multi-hop."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import multiprocessing
from pathlib import Path
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from wsn_sim.config import SimulationConfig
from wsn_sim.simulation import Simulation


def run_single_range_worker(range_m: float, config_dict: dict, duration_s: float, output_dir: str, algorithm: str = "EMHR") -> dict:
    """Worker độc lập cho một tiến trình CPU mô phỏng một bán kính."""
    cfg = SimulationConfig.from_dict(config_dict)
    out_folder = Path(output_dir) / f"{algorithm}_R{int(range_m)}m_seed{cfg.seed}"

    sim = Simulation(
        target=cfg,
        current_range_m=range_m,
        routing_algorithm=algorithm,
        quiet=True,
    )
    sim.run_for(duration_s)
    sim.export_results(out_folder)
    metrics = sim.get_metrics()
    metrics["range_m"] = range_m
    metrics["output_dir"] = str(out_folder)
    return metrics


def run_default_project(duration_s: float = 100.0, output_dir: str = "results/simulation", algorithm: str = "EMHR"):
    """Chạy mô phỏng song song 3 bán kính bằng multiprocessing."""
    print("=" * 70)
    print(" KHỞI ĐỘNG HỆ THỐNG MÔ PHỎNG WSN - CHUYỂN TIẾP MULTI-HOP")
    print(f" Thuật toán: {algorithm} | Bán kính: [250, 300, 350] m | Thời lượng: {duration_s}s")
    print("=" * 70)

    cfg_path = Path("configs/default.json")
    with cfg_path.open("r", encoding="utf-8") as f:
        config_data = json.load(f)

    ranges = config_data.get("communication_ranges_m", [250.0, 300.0, 350.0])

    workers = min(len(ranges), multiprocessing.cpu_count() or 1)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_single_range_worker, r, config_data, duration_s, output_dir, algorithm): r
            for r in ranges
        }
        for future in concurrent.futures.as_completed(futures):
            r = futures[future]
            try:
                metrics = future.result()
                print(
                    f"\n[HOÀN THÀNH] Bán kính {r}m:"
                    f" Gói đã sinh: {metrics['generated_packets']},"
                    f" Gói đến đích: {metrics['delivered_packets']},"
                    f" Gói bị hủy: {metrics['dropped_packets']},"
                    f" Năng lượng tiêu thụ: {metrics['consumed_energy_sensors_j']} J"
                )
                print(f" -> Kết quả đã lưu tại: {metrics['output_dir']}")
            except Exception as exc:
                print(f"[LỖI] Kịch bản bán kính {r}m gặp sự cố: {exc}")

    print("\n" + "=" * 70)
    print(" TOÀN BỘ MÔ PHỎNG ĐÃ HOÀN TẤT!")
    print(f" Hãy kiểm tra thư mục '{output_dir}' để lấy toàn bộ dữ liệu CSV, JSON và Log.")
    print("=" * 70)


def build_parser() -> argparse.ArgumentParser:
    """Xây dựng bộ phân tích tham số dòng lệnh CLI."""
    parser = argparse.ArgumentParser(
        description="Bộ công cụ mô phỏng mạng cảm biến vô tuyến WSN (MHR, EMHR) giai đoạn multi-hop"
    )
    parser.add_argument(
        "--mode",
        choices=["default", "smoke", "single"],
        default="default",
        help="Chế độ chạy: default (3 bán kính song song), smoke (30s test nhanh), single (1 kịch bản)",
    )
    parser.add_argument(
        "--algorithm",
        choices=["MHR", "EMHR"],
        default="EMHR",
        help="Thuật toán định tuyến lựa chọn (MHR hoặc EMHR, mặc định: EMHR)",
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=300.0,
        help="Bán kính truyền thông vô tuyến R tính bằng mét (mặc định: 300.0)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=100.0,
        help="Thời lượng mô phỏng tính bằng giây (mặc định: 100.0)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Hạt giống ngẫu nhiên (mặc định: 42)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results/simulation",
        help="Thư mục xuất kết quả (mặc định: results/simulation)",
    )
    return parser


def main() -> None:
    """Điểm nhập chính điều phối toàn bộ các kịch bản mô phỏng."""
    parser = build_parser()
    args = parser.parse_args()

    algo = args.algorithm.upper()

    if args.mode == "smoke":
        smoke_duration = min(args.duration, 30.0) if args.duration != 100.0 else 30.0
        print(f"[SMOKE] Khởi chạy mô phỏng kiểm tra nhanh {smoke_duration}s với thuật toán {algo}...")
        cfg = SimulationConfig.from_json("configs/default.json")
        cfg_dict = cfg.to_dict()
        cfg_dict["seed"] = args.seed
        out_dir = str(Path(args.output_dir) / "smoke")
        metrics = run_single_range_worker(args.radius, cfg_dict, smoke_duration, out_dir, algo)
        print(f"[SMOKE HOÀN THÀNH] Kết quả đã lưu tại: {metrics['output_dir']}")
        print(json.dumps(metrics, indent=2, ensure_ascii=False))

    elif args.mode == "single":
        print(f"[SINGLE] Chạy kịch bản đơn lẻ: Algo={algo}, R={args.radius}m, Seed={args.seed}, Time={args.duration}s")
        cfg = SimulationConfig.from_json("configs/default.json")
        cfg_dict = cfg.to_dict()
        cfg_dict["seed"] = args.seed
        metrics = run_single_range_worker(args.radius, cfg_dict, args.duration, args.output_dir, algo)
        print(f"[SINGLE HOÀN THÀNH] Kết quả đã lưu tại: {metrics['output_dir']}")
        print(json.dumps(metrics, indent=2, ensure_ascii=False))

    else:
        run_default_project(duration_s=args.duration, output_dir=args.output_dir, algorithm=algo)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
