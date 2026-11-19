import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from .config import SimulationConfig
from .simulation import Simulation
from .storage import save_simulation_run


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).with_name("config.json")
ANALYSIS_RADIUS_M = 300.0
STAGE2_ALGORITHMS = ("MHR", "EMHR", "Weighted_Dijkstra", "MMBCR", "GPSR")


def project_scenarios(config: SimulationConfig) -> list[tuple[float, str]]:
    range_scenarios = [(radius, "EMHR") for radius in config.communication_ranges_m]
    algorithm_scenarios = [(ANALYSIS_RADIUS_M, algorithm) for algorithm in STAGE2_ALGORITHMS]
    return list(dict.fromkeys(range_scenarios + algorithm_scenarios))


def run_single_scenario(
    radius: float, algorithm: str, config_data: dict, output: Path
) -> tuple[float, str]:
    config = SimulationConfig.from_dict(config_data)
    simulation = Simulation(config, current_range_m=radius, routing_algo=algorithm)
    simulation.run_for()
    save_simulation_run(simulation, output, PROJECT_ROOT)
    return radius, algorithm


def run_project(config: SimulationConfig, output: Path, workers: int | None = None) -> None:
    scenarios = project_scenarios(config)
    worker_count = min(len(scenarios), workers or os.cpu_count() or 1)
    config_data = config.to_dict()
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(run_single_scenario, radius, algorithm, config_data, output)
            for radius, algorithm in scenarios
        ]
        for future in as_completed(futures):
            radius, algorithm = future.result()
            print(f"Đã lưu CSV cho {algorithm} ở bán kính {radius:g} m")
