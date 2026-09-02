"""End-to-end demo integration test."""

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd


def test_demo_generates_all_required_outputs(project_root: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_demo.py"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    csv_path = project_root / "results" / "csv" / "topology_summary.csv"
    manifest_path = project_root / "results" / "run_manifest.json"
    figure_paths = [
        project_root / "results" / "figures" / f"topology_R{radius}.png"
        for radius in (250, 300, 350)
    ]

    assert "sensors=450" in result.stdout
    assert "sinks=7" in result.stdout
    assert csv_path.exists()
    assert len(pd.read_csv(csv_path)) == 3
    assert all(path.exists() and path.stat().st_size > 0 for path in figure_paths)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["seed"] == 42
    assert len(manifest["generated_files"]) == 5
