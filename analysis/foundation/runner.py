import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from wsn_sim.config import SimulationConfig

from .simulation import Simulation


CONFIG_PATH = Path(__file__).with_name("config.json")
COMPARISON_RANGE_M = 300.0
COMPARISON_ALGORITHMS = ("MHR", "EMHR", "Weighted_Dijkstra", "MMBCR", "GPSR")


def run_single_scenario(
    config: SimulationConfig, range_m: float, algorithm: str, duration_s: float, csv_dir: Path
) -> tuple[float, str]:
    simulation = Simulation(config, range_m, algorithm, csv_dir=csv_dir)
    simulation.run_for(duration_s)
    return range_m, algorithm


def run_project(config: SimulationConfig, duration_s: float, csv_dir: Path) -> None:
    range_scenarios = [(radius, "EMHR") for radius in config.communication_ranges_m]
    algorithm_scenarios = [(COMPARISON_RANGE_M, algorithm) for algorithm in COMPARISON_ALGORITHMS]
    scenarios = list(dict.fromkeys(range_scenarios + algorithm_scenarios))
    workers = min(len(scenarios), os.cpu_count() or 1)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(run_single_scenario, config, radius, algorithm, duration_s, csv_dir)
            for radius, algorithm in scenarios
        ]
        for future in as_completed(futures):
            radius, algorithm = future.result()
            print(f"Đã lưu CSV cho {algorithm} ở bán kính {radius:g} m")
