"""Check the official profile's topology and a small, exact TX/RX fixture."""

from argparse import ArgumentParser
import json
from pathlib import Path

import pandas as pd

from scripts.check_foundation import check_known_graph, check_reachability
from wsn_sim.config import SimulationConfig
from wsn_sim.storage import create_run_directory, create_run_manifest, save_csv, save_json


def main():
    root = Path(__file__).resolve().parents[1]
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42])
    parser.add_argument("--output", type=Path, default=root / "results/runs")
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds) or min(args.seeds) < 0:
        parser.error("seeds must be unique non-negative integers")
    config = SimulationConfig.from_json(root / "configs/default.json")
    known_graph = check_known_graph(config)
    reachability = check_reachability(config, args.seeds)
    output = create_run_directory(args.output, "foundation_check_10000s")
    passed = config.max_duration_s == 10000 and known_graph["matches_expected"] and reachability["coordinates_stable"]
    report = {"stage": 1, "checks_passed": passed, "known_graph": known_graph, "reachability": reachability,
              "legacy": {"performance_run": False}, "output_directory": str(output)}
    report_file = save_json(report, output / "foundation_check.json")
    reachability_file = save_csv(pd.DataFrame(reachability["rows"]), output / "reachability.csv")
    manifest_file = output / "run_manifest.json"
    save_json(create_run_manifest(config, [report_file, reachability_file, manifest_file], root), manifest_file)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
