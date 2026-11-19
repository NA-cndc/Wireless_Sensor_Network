"""Reproduce the radius pilot and paired, benign MHR/EMHR experiments."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import json
from math import ceil, sqrt
import multiprocessing
import os
from pathlib import Path
from statistics import mean, stdev
import sys

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import ANALYSIS_RADIUS_M, run_single_scenario
from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network
from wsn_sim.storage import _git_output, save_json, save_topology_summary, scenario_stem

OUTPUT = ROOT / "results" / "study_10000s"
MINIMUM_ROUTABLE_FRACTION = 0.95


def paired_configs(config: SimulationConfig, count: int) -> list[SimulationConfig]:
    return [
        replace(config, seed=int(topology), traffic_seed=int(traffic), channel_seed=int(channel))
        for topology, traffic, channel in (
            child.generate_state(3, dtype=np.uint64) for child in np.random.SeedSequence(config.seed).spawn(count)
        )
    ]


def radius_pilot(configs: list[SimulationConfig], output: Path, commit: str | None) -> float:
    rows = []
    totals = {radius: 0 for radius in configs[0].communication_ranges_m}
    for pair, config in enumerate(configs, 1):
        network = Network(config)
        for radius in totals:
            if network.communication_range_m != radius:
                network.build_graph(radius)
            summary = network.topology_summary()
            passes = summary["routable_sensors"] >= ceil(MINIMUM_ROUTABLE_FRACTION * config.num_sensors)
            totals[radius] += passes
            rows.append({
                "pair": pair, **summary,
                "routable_fraction": summary["routable_sensors"] / config.num_sensors,
                "passes_95_percent": passes,
            })
    save_topology_summary(pd.DataFrame(rows), output / "pilot_topologies.csv")
    qualifying = [radius for radius, passes in totals.items() if 2 * passes > len(configs)]
    if ANALYSIS_RADIUS_M in qualifying:
        selected = ANALYSIS_RADIUS_M
    elif qualifying:
        selected = min(qualifying)
    else:
        selected = min(totals, key=lambda radius: (-totals[radius], radius))
    save_json({
        "git_commit": commit,
        "selected_radius_m": selected,
        "minimum_routable_fraction": MINIMUM_ROUTABLE_FRACTION,
        "selected_meets_majority_criterion": selected in qualifying,
        "results": [
            {"radius_m": radius, "topologies": len(configs), "passing": passes,
             "failing": len(configs) - passes, "passing_fraction": passes / len(configs)}
            for radius, passes in totals.items()
        ],
    }, output / "pilot_summary.json")
    return selected


def study_jobs(configs, radius, output):
    treatments = [
        (algo, loss, configs[0].emhr_alpha)
        for loss in (0.0, 0.01, 0.05) for algo in ("MHR", "EMHR")
    ] + [("EMHR", configs[0].channel_loss_probability, alpha) for alpha in (0.10, 0.30)]
    for pair, config in enumerate(configs, 1):
        for algo, loss, alpha in dict.fromkeys(treatments):
            treatment = f"{algo}_loss_{loss:g}" + (f"_alpha_{alpha:g}" if algo == "EMHR" else "")
            directory = output / "runs" / f"pair_{pair:02d}" / treatment
            settings = replace(config, channel_loss_probability=loss, emhr_alpha=alpha)
            yield pair, treatment, (radius, algo, settings.to_dict(), directory)


def read_completed(job, commit):
    radius, algo, config, directory = job
    path = directory / f"{scenario_stem(algo, radius)}.json"
    if not path.is_file():
        return None
    run = json.loads(path.read_text(encoding="utf-8"))
    if (
        run["git_commit"] != commit or run["configuration"] != config
        or run["routing_algorithm"] != algo or run["communication_range_m"] != radius
        or run["metrics"]["stop_reason"] not in {"duration_limit", "lnd"}
        or not all((directory / name).is_file() for name in run["generated_files"])
    ):
        return None
    return path


def metric_values(run):
    metrics = run["metrics"]
    values = {
        field: metrics[field] for field in (
            "elapsed_s", "rounds", "generated_packets", "delivered_packets", "delivered_payload_bits",
            "alive_sensors", "routable_sensors", "pdr_percent", "throughput_bps", "goodput_bps",
            "mean_offered_bps", "energy_consumed_j", "energy_j_per_delivered_bit", "mean_hops",
            "mean_end_to_end_latency_s", "relay_load_jain", "route_changes", "data_tx_attempts",
        )
    }
    values.update({f"drop_{reason}": count for reason, count in metrics["drop_reasons"].items()})
    for label, milestone in metrics["milestones"].items():
        values[f"{label}_s"] = milestone["time_s"]
        values[f"{label}_payload_bits"] = milestone["payload_bits"]
    return values


def estimate(values, total):
    n = len(values)
    average = mean(values) if n else None
    sd = stdev(values) if n >= 2 else None
    margin = None if sd is None else stats.t.ppf(0.975, n - 1) * sd / sqrt(n)
    return {
        "n": n, "omitted": total - n, "mean": average, "sample_sd": sd,
        "ci95_low": None if margin is None else average - margin,
        "ci95_high": None if margin is None else average + margin,
    }


def compare(control, experiment):
    differences = [b - a for a, b in zip(control, experiment)]
    out = estimate(differences, len(differences))
    baseline = mean(control) if control else None
    out["percent_change"] = 100 * out["mean"] / baseline if baseline else None
    sd = out["sample_sd"]
    out["cohen_dz"] = out["mean"] / sd if sd else None
    out.update(test=None, p_value=None)
    if len(differences) >= 3:
        if not any(differences):
            out.update(test="all_differences_zero", p_value=1.0)
        elif sd and stats.shapiro(differences).pvalue >= 0.05:
            out.update(test="paired_t", p_value=float(stats.ttest_rel(experiment, control).pvalue))
        else:
            out.update(test="wilcoxon_signed_rank", p_value=float(stats.wilcoxon(differences).pvalue))
    return out


def report(jobs, output, commit, config):
    availability = []
    by_treatment = {}
    metric_names = ()
    for pair, treatment, job in jobs:
        path = read_completed(job, commit)
        by_treatment.setdefault(treatment, {})
        if path:
            values = metric_values(json.loads(path.read_text(encoding="utf-8")))
            by_treatment[treatment][pair] = values
            metric_names = tuple(values)
        availability.append({
            "pair": pair, "treatment": treatment, "completed": path is not None,
            "manifest": str(path.relative_to(output)).replace(os.sep, "/") if path else None,
        })
    save_topology_summary(pd.DataFrame(availability), output / "run_index.csv")
    if not metric_names:
        return
    rows = []
    planned_pairs = len({pair for pair, _, _ in jobs})
    for treatment, paired in by_treatment.items():
        for metric in metric_names:
            values = [record[metric] for record in paired.values() if record[metric] is not None]
            rows.append({"treatment": treatment, "metric": metric, "runs_completed": len(paired),
                         **estimate(values, planned_pairs)})
    save_topology_summary(pd.DataFrame(rows), output / "summary.csv")
    base_alpha, base_loss = config.emhr_alpha, config.channel_loss_probability
    comparisons = [(f"MHR_loss_{loss:g}", f"EMHR_loss_{loss:g}_alpha_{base_alpha:g}") for loss in (0, 0.01, 0.05)]
    comparisons += [(f"EMHR_loss_{base_loss:g}_alpha_{base_alpha:g}", f"EMHR_loss_{base_loss:g}_alpha_{alpha:g}")
                    for alpha in (0.10, 0.30) if alpha != base_alpha]
    rows = []
    for baseline, treatment in comparisons:
        control, experimental = by_treatment[baseline], by_treatment[treatment]
        shared = sorted(control.keys() & experimental.keys())
        for metric in metric_names:
            pairs = [(control[seed][metric], experimental[seed][metric]) for seed in shared
                     if control[seed][metric] is not None and experimental[seed][metric] is not None]
            stats_row = compare([a for a, _ in pairs], [b for _, b in pairs])
            stats_row["omitted"] = planned_pairs - len(pairs)
            rows.append({"control": baseline, "treatment": treatment, "metric": metric,
                         "runs_paired": len(shared), **stats_row})
    save_topology_summary(pd.DataFrame(rows), output / "paired_differences.csv")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--pilot-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--source-commit", help="Git revision of existing runs for --report-only")
    args = parser.parse_args()
    if args.seeds < 1 or args.workers < 1:
        parser.error("--seeds and --workers must be positive")
    if args.source_commit and not args.report_only:
        parser.error("--source-commit requires --report-only")
    config = SimulationConfig.from_json(ROOT / "configs" / "default.json")
    revision = args.source_commit or "HEAD"
    commit = _git_output(ROOT, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
    if args.source_commit and commit is None:
        parser.error("--source-commit must identify a commit in this repository")
    configs = paired_configs(config, args.seeds)
    selected = radius_pilot(configs, args.output, commit)
    if args.pilot_only:
        return
    jobs = list(study_jobs(configs, selected, args.output))
    if not args.report_only:
        remaining = [job for _, _, job in jobs if read_completed(job, commit) is None]
        print(f"Running {len(remaining)} of {len(jobs)} scenarios at R={selected:g} m", flush=True)
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(run_single_scenario, *job) for job in remaining]
            for result in futures:
                result.result()
    report(jobs, args.output, commit, config)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
