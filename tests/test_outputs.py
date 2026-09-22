"""Tests for pandas, JSON, and Matplotlib outputs."""

import json
from pathlib import Path

import pandas as pd

from wsn_sim.config import SimulationConfig
from wsn_sim.metrics import TOPOLOGY_SUMMARY_COLUMNS, topology_summary_frame
from wsn_sim.network import Network
from wsn_sim.storage import create_run_manifest, save_json, save_topology_summary
from wsn_sim.visualization import save_topology_plot


def test_csv_has_expected_columns_and_no_index(tmp_path: Path) -> None:
    frame = topology_summary_frame(
        [
            {
                "seed": 42,
                "communication_range_m": 250,
                "sensors": 450,
                "sinks": 7,
                "nodes": 457,
                "edges": 1,
                "routable_sensors": 2,
                "isolated_sensors": 3,
            }
        ]
    )

    path = save_topology_summary(frame, tmp_path / "nested" / "summary.csv")
    loaded = pd.read_csv(path)

    assert path.exists()
    assert list(loaded.columns) == TOPOLOGY_SUMMARY_COLUMNS
    assert "Unnamed: 0" not in loaded.columns


def test_plot_is_created_and_nonempty(network: Network, tmp_path: Path) -> None:
    path = save_topology_plot(network, tmp_path / "plots" / "topology.png")

    assert path.exists()
    assert path.stat().st_size > 0


def test_manifest_round_trip(
    config: SimulationConfig,
    project_root: Path,
    tmp_path: Path,
) -> None:
    manifest = create_run_manifest(
        config,
        ["results/csv/topology_summary.csv"],
        project_root,
    )
    path = save_json(manifest, tmp_path / "manifest" / "run.json")

    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["seed"] == 42
    assert loaded["git_branch"] == "XB"
    assert set(loaded["library_versions"]) == {
        "networkx",
        "simpy",
        "numpy",
        "pandas",
        "matplotlib",
    }
