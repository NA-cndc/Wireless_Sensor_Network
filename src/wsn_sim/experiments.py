"""Trình điều phối thí nghiệm WSN: Chạy kịch bản đơn, đối chiếu cặp và ma trận 30 seed."""

from __future__ import annotations

import concurrent.futures
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.statistics import calculate_sample_statistics, compare_paired_experiments


def run_single_experiment(
    config: SimulationConfig,
    algorithm: str = "EMHR",
    range_m: float = 300.0,
    duration_s: float = 1000.0,
    seed: int | None = None,
    attacker_ratio: float = 0.0,
    drop_prob: float = 0.0,
    channel_loss_prob: float = 0.0,
    alpha_energy: float = 0.20,
    output_dir: str | Path | None = None,
    scenario_name: str | None = None,
) -> dict[str, Any]:
    """Chạy một phiên mô phỏng hoàn chỉnh cho một seed và cấu hình cụ thể."""
    effective_seed = config.seed if seed is None else int(seed)
    current_config = replace(config, seed=effective_seed)

    sim = Simulation(
        target=current_config,
        current_range_m=range_m,
        routing_algorithm=algorithm,
        alpha_energy=alpha_energy,
        attacker_ratio=attacker_ratio,
        drop_prob=drop_prob,
        channel_loss_prob=channel_loss_prob,
        quiet=True,
        seed=effective_seed,
    )

    sim.run_for(duration_s)
    metrics = sim.get_metrics()
    metrics["algorithm"] = algorithm
    metrics["range_m"] = range_m
    metrics["seed"] = effective_seed
    metrics["attacker_ratio"] = attacker_ratio
    metrics["drop_prob"] = drop_prob
    metrics["channel_loss_prob"] = channel_loss_prob

    if output_dir:
        scen = scenario_name or f"{algorithm}_R{int(range_m)}m_seed{effective_seed}"
        run_folder = Path(output_dir) / scen
        sim.export_results(run_folder)

    return metrics


def _batch_worker_task(args_tuple: tuple) -> dict[str, Any]:
    (
        config,
        algo,
        range_m,
        duration_s,
        seed_val,
        attacker_ratio,
        drop_prob,
        channel_loss_prob,
        out_path,
        scenario_name,
    ) = args_tuple
    return run_single_experiment(
        config=config,
        algorithm=algo,
        range_m=range_m,
        duration_s=duration_s,
        seed=seed_val,
        attacker_ratio=attacker_ratio,
        drop_prob=drop_prob,
        channel_loss_prob=channel_loss_prob,
        output_dir=out_path,
        scenario_name=scenario_name,
    )


def run_paired_batch(
    config: SimulationConfig,
    seeds: Sequence[int],
    range_m: float = 300.0,
    duration_s: float = 500.0,
    algorithms: Sequence[str] = ("MHR", "EMHR"),
    attacker_ratio: float = 0.0,
    drop_prob: float = 0.0,
    channel_loss_prob: float = 0.0,
    output_dir: str | Path = "results/experiments",
    max_workers: int = 1,
) -> dict[str, Any]:
    """Chạy ma trận so sánh cặp giữa các thuật toán trên cùng một tập seeds độc lập."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []

    task_args = [
        (
            config,
            algo,
            range_m,
            duration_s,
            s,
            attacker_ratio,
            drop_prob,
            channel_loss_prob,
            out_path,
            f"{algo}_seed{s}",
        )
        for s in seeds
        for algo in algorithms
    ]

    if max_workers > 1:
        with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(_batch_worker_task, arg): arg for arg in task_args
            }
            for fut in concurrent.futures.as_completed(future_to_task):
                records.append(fut.result())
    else:
        for arg in task_args:
            records.append(_batch_worker_task(arg))

    df = pd.DataFrame(records)
    batch_csv_path = out_path / "batch_summary.csv"
    df.to_csv(batch_csv_path, index=False, encoding="utf-8")

    stat_summary: dict[str, Any] = {}
    for algo in algorithms:
        algo_df = df[df["algorithm"] == algo].sort_values("seed")
        stat_summary[algo] = {
            "pdr_percent": calculate_sample_statistics(algo_df["pdr_percent"].tolist()),
            "throughput_bps": calculate_sample_statistics(algo_df["throughput_bps"].tolist()),
            "consumed_energy_j": calculate_sample_statistics(algo_df["consumed_energy_sensors_j"].tolist()),
            "jains_fairness": calculate_sample_statistics(algo_df["jains_fairness_index"].tolist()),
            "avg_hop_count": calculate_sample_statistics(algo_df["avg_hop_count"].tolist()),
        }

    paired_comparison: dict[str, Any] = {}
    if len(algorithms) == 2:
        algo1, algo2 = algorithms[0], algorithms[1]
        df1 = df[df["algorithm"] == algo1].set_index("seed").reindex(seeds)
        df2 = df[df["algorithm"] == algo2].set_index("seed").reindex(seeds)

        for col in ["pdr_percent", "throughput_bps", "consumed_energy_sensors_j", "jains_fairness_index"]:
            paired_comparison[f"{algo1}_vs_{algo2}_{col}"] = compare_paired_experiments(
                baseline_values=df1[col].tolist(),
                proposed_values=df2[col].tolist(),
            )

    result_report = {
        "algorithms": list(algorithms),
        "seeds_count": len(seeds),
        "range_m": range_m,
        "duration_s": duration_s,
        "single_algorithm_stats": stat_summary,
        "paired_comparison": paired_comparison,
        "batch_csv": str(batch_csv_path),
    }

    report_json_path = out_path / "statistical_analysis.json"
    with report_json_path.open("w", encoding="utf-8") as f:
        json.dump(result_report, f, indent=2, ensure_ascii=False)

    return result_report
