"""Persistence helpers for tabular results and reproducibility metadata."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from gzip import GzipFile
from importlib.metadata import PackageNotFoundError, version
from io import TextIOWrapper
import json
from math import isclose
from pathlib import Path
import platform
import subprocess
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Iterable

import pandas as pd

from wsn_sim.config import SimulationConfig

if TYPE_CHECKING:
    from wsn_sim.simulation import Simulation

RUNTIME_LIBRARIES = ("networkx", "simpy", "numpy", "pandas", "matplotlib", "scipy")


def scenario_stem(routing_algo: str, radius: float) -> str:
    return f"simulation_log_{routing_algo}_range_{radius:g}m"


def save_simulation_run(sim: Simulation, output_dir: Path, root: Path) -> Path:
    """Save a completed run under the existing time-series CSV name."""
    if sim.stop_reason is None:
        raise ValueError("simulation must be finalized before saving")
    summary = sim.summary()
    if summary["generated_packets"] != summary["delivered_packets"] + sum(summary["drop_reasons"].values()):
        raise RuntimeError("packet totals do not reconcile")
    if not isclose(summary["energy_consumed_j"], sum(summary["energy_ledger_j"].values()), abs_tol=1e-7):
        raise RuntimeError("energy ledger does not reconcile with residual energy")
    radius = sim.network.communication_range_m
    stem = scenario_stem(sim.routing_algo, radius)
    series_name = f"{stem}.csv"
    relay_name = f"{stem}_relays.csv"
    packet_name = f"{stem}_packets.csv.gz"
    manifest_name = f"{stem}.json"
    names = (series_name, relay_name, packet_name, manifest_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output_dir) as staging:
        stage = Path(staging)
        with (stage / series_name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(sim.samples[0]))
            writer.writeheader()
            writer.writerows(sim.samples)
        with (stage / relay_name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("sensor_id", "forwarded_packets", "generated_packets", "energy_residual_j"))
            writer.writerows(
                (sensor.node_id, sensor.forwarded_packets, sensor.generated_packets, sensor.energy_j)
                for sensor in sim.network.sensors.values()
            )
        with (stage / packet_name).open("wb") as compressed:
            with GzipFile(fileobj=compressed, mode="wb", compresslevel=1, mtime=0) as zipped:
                with TextIOWrapper(zipped, encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(("packet_id", "source_id", "sequence_number", "generated_s", "received_s",
                                     "payload_bytes", "actual_path", "status", "drop_reason", "tx_attempts", "cutoff_state"))
                    for packet in sim.traffic_gen.generated_packets:
                        actual = packet.route[:packet.current_hop_index + 1] or [packet.source_id]
                        writer.writerow((
                            packet.packet_id, packet.source_id, packet.packet_id.rsplit("_p", 1)[1],
                            packet.created_at - sim.started_at,
                            None if packet.delivered_at is None else packet.delivered_at - sim.started_at,
                            packet.size_bytes, ">".join(actual), packet.status.value, packet.drop_reason,
                            packet.tx_attempts, sim.traffic_gen.cutoff_state.get(packet.packet_id),
                        ))
        manifest = create_run_manifest(sim.config, names, root)
        manifest.update({
            "routing_algorithm": sim.routing_algo,
            "communication_range_m": radius,
            "topology_seed": sim.config.seed,
            "traffic_seed": sim.config.effective_traffic_seed,
            "channel_seed": sim.config.effective_channel_seed,
            "metrics": summary,
        })
        save_json(manifest, stage / manifest_name)
        for name in names:
            (stage / name).replace(output_dir / name)
    return output_dir / manifest_name


def save_topology_summary(frame: pd.DataFrame, path: str | Path) -> Path:
    """Save a topology DataFrame as index-free UTF-8 CSV.

    Parent directories are created automatically and the saved path is returned.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def save_json(data: dict[str, Any], path: str | Path) -> Path:
    """Write JSON using UTF-8 and return the created path."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file_handle:
        json.dump(data, file_handle, ensure_ascii=False, indent=2)
        file_handle.write("\n")
    return output_path


def _git_output(repository_root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _library_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for library in RUNTIME_LIBRARIES:
        try:
            versions[library] = version(library)
        except PackageNotFoundError:
            versions[library] = "not-installed"
    return versions


def create_run_manifest(
    config: SimulationConfig,
    generated_files: Iterable[str | Path],
    repository_root: str | Path,
) -> dict[str, Any]:
    """Create runtime, dependency, Git, and output reproducibility metadata.

    Args:
        config: Configuration used for the run.
        generated_files: Paths produced by the demo, including the manifest path.
        repository_root: Git working tree used to collect read-only metadata.

    Returns:
        A JSON-serializable manifest dictionary. Missing Git metadata is ``None``.
    """
    root = Path(repository_root).resolve()
    status = _git_output(root, "status", "--porcelain")
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "seed": config.seed,
        "configuration": config.to_dict(),
        "python_version": platform.python_version(),
        "library_versions": _library_versions(),
        "git_commit": _git_output(root, "rev-parse", "HEAD"),
        "git_branch": _git_output(root, "branch", "--show-current"),
        "working_tree_clean": status == "" if status is not None else None,
        "generated_files": [str(Path(path)) for path in generated_files],
    }
