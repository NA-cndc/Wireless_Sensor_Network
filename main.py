import os
import sys
import json
import concurrent.futures
import multiprocessing
from pathlib import Path

# Cấu hình UTF-8 cho console trên Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

for path_dir in (str(PROJECT_ROOT), str(SRC_DIR)):
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

from wsn_sim.config import SimulationConfig
from wsn_sim.simulation import Simulation


def run_single_scenario(range_m: float, routing_algo: str, config_data: dict) -> tuple:
    print(f"\n[CORE Khởi động] >>> Bán kính {range_m}m | Thuật toán {routing_algo} <<<")
    cfg = SimulationConfig.from_dict(config_data)
    sim = Simulation(cfg, current_range_m=range_m, routing_algo=routing_algo)
    sim.run_for(5000.0)
    return range_m, routing_algo


def run_project():
    print("=" * 70)
    print(" KHỞI ĐỘNG HỆ THỐNG MÔ PHỎNG 2 GIAI ĐOẠN (WSN ROUTING)")
    print(" Chế độ: ĐA TIẾN TRÌNH (MULTIPROCESSING) TỐI ƯU TỐC ĐỘ")
    print("=" * 70)

    config_file = PROJECT_ROOT / "configs" / "default.json"
    with open(config_file, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    ranges = config_data.get("communication_ranges_m", [250.0, 300.0, 350.0])
    stage2_algos = ["MHR", "EMHR", "Weighted_Dijkstra", "MMBCR", "GPSR"]

    # Giai đoạn 1: Chạy EMHR trên cả 3 bán kính để chọn R=300m
    stage1_scenarios = [(float(r), "EMHR") for r in ranges]
    # Giai đoạn 2: Chạy đủ 5 thuật toán tại R=300m
    stage2_scenarios = [(300.0, algo) for algo in stage2_algos]

    scenarios = list(dict.fromkeys(stage1_scenarios + stage2_scenarios))
    optimal_workers = min(len(scenarios), os.cpu_count() or 4)

    print(f"[HỆ THỐNG] Đang phân bổ {len(scenarios)} kịch bản vào {optimal_workers} nhân CPU...")
    with concurrent.futures.ProcessPoolExecutor(max_workers=optimal_workers) as executor:
        futures = [executor.submit(run_single_scenario, r, algo, config_data) for r, algo in scenarios]
        for future in concurrent.futures.as_completed(futures):
            completed_range, completed_algo = future.result()
            print(f"\n[HOÀN THÀNH] Ghi xong file CSV: {completed_algo} - {completed_range}m!")

    print("\n" + "=" * 70)
    print(" TOÀN BỘ MÔ PHỎNG ĐÃ HOÀN TẤT SIÊU TỐC!")
    print("=" * 70)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    run_project()