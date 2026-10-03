"""File chạy chính thức của Đồ án WSN (Hỗ trợ CLI đa năng và Đa tiến trình).

Ví dụ sử dụng:
    python main.py                       # Chạy mô phỏng mặc định 3 bán kính (Đa tiến trình)
    python main.py --help                # Xem hướng dẫn các tùy chọn CLI
    python main.py --mode smoke          # Chạy kiểm tra nhanh 50 giây
    python main.py --mode pilot          # Chạy pilot 3 bán kính (250m, 300m, 350m)
    python main.py --mode research --seeds 30  # Chạy ma trận 30 seed so sánh MHR vs EMHR
"""

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
from wsn_sim.experiments import run_paired_batch, run_single_experiment
from wsn_sim.simulation import Simulation


def run_single_range_worker(range_m: float, config_dict: dict, duration_s: float, output_dir: str) -> dict:
    """Worker độc lập cho một tiến trình CPU mô phỏng một bán kính."""
    cfg = SimulationConfig.from_dict(config_dict)
    out_folder = Path(output_dir) / f"EMHR_R{int(range_m)}m_seed{cfg.seed}"

    sim = Simulation(
        target=cfg,
        current_range_m=range_m,
        routing_algorithm="EMHR",
        quiet=True,
    )
    sim.run_for(duration_s)
    saved = sim.export_results(out_folder)
    metrics = sim.get_metrics()
    metrics["range_m"] = range_m
    metrics["output_dir"] = str(out_folder)
    return metrics


def run_default_project(duration_s: float = 1000.0, output_dir: str = "results/experiments"):
    """Chạy mô phỏng song song 3 bán kính bằng multiprocessing."""
    print("=" * 70)
    print(" KHỞI ĐỘNG HỆ THỐNG MÔ PHỎNG WSN - ĐẠI HỌC TÔN ĐỨC THẮNG")
    print(" Chế độ: ĐA TIẾN TRÌNH (MULTIPROCESSING) - BÁN KÍNH PILOT [250, 300, 350] m")
    print("=" * 70)

    cfg_path = Path("configs/default.json")
    with cfg_path.open("r", encoding="utf-8") as f:
        config_data = json.load(f)

    ranges = config_data.get("communication_ranges_m", [250.0, 300.0, 350.0])
    print(f"[HỆ THỐNG] Đang phân bổ {len(ranges)} kịch bản bán kính vào các nhân CPU...")

    workers = min(len(ranges), multiprocessing.cpu_count() or 1)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_single_range_worker, r, config_data, duration_s, output_dir): r
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
                    f" PDR: {metrics['pdr_percent']}%,"
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
        description="Bộ công cụ mô phỏng mạng cảm biến vô tuyến WSN (MHR, EMHR, S-EMHR)"
    )
    parser.add_argument(
        "--mode",
        choices=["default", "smoke", "pilot", "research", "single"],
        default="default",
        help="Chế độ chạy: default (3 bán kính pilot), smoke (50s test nhanh), pilot, research (30 seeds), single",
    )
    parser.add_argument(
        "--algorithm",
        choices=["MHR", "EMHR", "MHR-SF", "S-EMHR", "ALL"],
        default="EMHR",
        help="Thuật toán định tuyến lựa chọn (mặc định: EMHR)",
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
        default=1000.0,
        help="Thời lượng mô phỏng (giây). Với chế độ smoke mặc định là 50.0.",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=30,
        help="Số lượng seed độc lập khi chạy chế độ research (mặc định: 30)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed ngẫu nhiên khi chạy chế độ single/smoke (mặc định: 42)",
    )
    parser.add_argument(
        "--attack-ratio",
        type=float,
        default=0.0,
        help="Tỷ lệ sensor tấn công Selective Forwarding (ví dụ: 0.02, 0.05, 0.10)",
    )
    parser.add_argument(
        "--drop-prob",
        type=float,
        default=0.0,
        help="Xác suất hủy gói khi làm relay của node tấn công (ví dụ: 0.25, 0.50, 0.75)",
    )
    parser.add_argument(
        "--channel-loss",
        type=float,
        default=0.0,
        help="Xác suất mất gói tự nhiên của liên kết (ví dụ: 0.01, 0.05)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=multiprocessing.cpu_count() or 1,
        help="Số nhân CPU chạy song song",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results/experiments",
        help="Thư mục lưu trữ kết quả đầu ra CSV/JSON",
    )
    return parser


def main():
    multiprocessing.freeze_support()
    parser = build_parser()

    if len(sys.argv) == 1:
        run_default_project()
        return

    args = parser.parse_args()
    config = SimulationConfig.from_json("configs/default.json")

    if args.mode == "default":
        run_default_project(duration_s=args.duration, output_dir=args.output_dir)

    elif args.mode == "smoke":
        dur = 50.0 if args.duration == 1000.0 else args.duration
        print(f"[SMOKE] Chạy thử nghiệm nhanh trong {dur}s với seed={args.seed}...")
        metrics = run_single_experiment(
            config=config,
            algorithm=args.algorithm if args.algorithm != "ALL" else "EMHR",
            range_m=args.radius,
            duration_s=dur,
            seed=args.seed,
            output_dir=args.output_dir,
            scenario_name=f"smoke_{args.algorithm}_seed{args.seed}",
        )
        print(f"[SMOKE OK] Gói sinh: {metrics['generated_packets']}, Gói nhận: {metrics['delivered_packets']}, PDR: {metrics['pdr_percent']}%")

    elif args.mode == "single":
        print(f"[SINGLE] Chạy mô phỏng {args.algorithm} (R={args.radius}m, {args.duration}s, seed={args.seed})...")
        metrics = run_single_experiment(
            config=config,
            algorithm=args.algorithm if args.algorithm != "ALL" else "EMHR",
            range_m=args.radius,
            duration_s=args.duration,
            seed=args.seed,
            attacker_ratio=args.attack_ratio,
            drop_prob=args.drop_prob,
            channel_loss_prob=args.channel_loss,
            output_dir=args.output_dir,
        )
        print(f"[SINGLE OK] PDR: {metrics['pdr_percent']}%, Throughput: {metrics['throughput_bps']} bps")

    elif args.mode == "pilot":
        run_default_project(duration_s=args.duration, output_dir=args.output_dir)

    elif args.mode == "research":
        seeds_list = [42 + i for i in range(args.seeds)]
        algos = ("MHR", "EMHR") if args.algorithm in ("ALL", "EMHR") else (args.algorithm,)
        print(f"[RESEARCH] Chạy ma trận {len(seeds_list)} seed độc lập so sánh {algos}...")
        report = run_paired_batch(
            config=config,
            seeds=seeds_list,
            range_m=args.radius,
            duration_s=args.duration,
            algorithms=algos,
            attacker_ratio=args.attack_ratio,
            drop_prob=args.drop_prob,
            channel_loss_prob=args.channel_loss,
            output_dir=args.output_dir,
            max_workers=args.workers,
        )
        print(f"[RESEARCH OK] Đã hoàn thành {len(seeds_list)} seed. Phân tích thống kê đã ghi ra: {report['batch_csv']}")


if __name__ == "__main__":
    main()
