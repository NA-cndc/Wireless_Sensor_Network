from __future__ import annotations
from datetime import datetime, timezone
import csv
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import subprocess
from uuid import uuid4
from typing import Any, Iterable
import pandas as pd
from wsn_sim.config import SimulationConfig
from wsn_sim.metrics import METRIC_SCHEMA
from wsn_sim.randomness import randomness_metadata
RUNTIME_LIBRARIES = ('networkx', 'simpy', 'numpy', 'pandas', 'matplotlib', 'scipy')

def save_csv(frame: pd.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, encoding='utf-8')
    return output_path
save_topology_summary = save_csv

def append_csv_row(filename: str | Path, headers, data_row) -> None:
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open('a', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        if write_header:
            writer.writerow(headers)
        writer.writerow(data_row)

def save_json(data: dict[str, Any], path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8') as file_handle:
        json.dump(data, file_handle, ensure_ascii=False, indent=2, allow_nan=False)
        file_handle.write('\n')
    return output_path

def _git_output(repository_root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(['git', '-C', str(repository_root), *arguments], cwd=repository_root, check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()

def _library_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for library in RUNTIME_LIBRARIES:
        try:
            versions[library] = version(library)
        except PackageNotFoundError:
            versions[library] = 'not-installed'
    return versions

def create_run_manifest(config: SimulationConfig, generated_files: Iterable[str | Path], repository_root: str | Path) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    status = _git_output(root, 'status', '--porcelain')
    return {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'metric_schema': METRIC_SCHEMA, 'seed': config.seed, 'stream_seeds': config.stream_seeds, 'randomness': randomness_metadata(), 'energy_threshold_j': config.energy_threshold_j, 'energy_configuration': config.energy_configuration, 'config_profile': config.config_profile, 'configuration': config.to_dict(), 'python_version': platform.python_version(), 'library_versions': _library_versions(), 'git_commit': _git_output(root, 'rev-parse', 'HEAD'), 'git_branch': _git_output(root, 'branch', '--show-current'), 'working_tree_clean': status == '' if status is not None else None, 'generated_files': [str(Path(path)) for path in generated_files]}

def create_run_directory(output_root: str | Path, prefix: str='run') -> Path:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = Path(output_root) / f'{prefix}_{stamp}_{uuid4().hex[:8]}'
    directory.mkdir(parents=True, exist_ok=False)
    return directory

def save_detector_outputs(detector, directory: str | Path) -> list[Path]:
    directory = Path(directory)
    files = [save_json(detector.summary(), directory / 'detector_summary.json')]
    tables = {'detector_windows.csv': detector.windows, 'detector_events.csv': detector.events, 'detector_observations.csv': detector.observation_records(), 'detector_excluded.csv': detector.exclusions}
    for name, rows in tables.items():
        if rows:
            files.append(save_csv(pd.DataFrame(rows), directory / name))
    return files

def save_simulation(simulation, directory: str | Path, repository_root: str | Path, extra_outputs: dict[str, dict] | None=None) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files = [save_json(simulation.summary(), directory / 'summary.json')]
    tables = {'events.csv': simulation.traffic_gen.events, 'reroutes.csv': simulation.traffic_gen.reroutes, 'reroute_decisions.csv': simulation.traffic_gen.reroute_decisions, 'energy_events.csv': simulation.energy_events, 'network_events.csv': simulation.network_events, 'lifetime_events.csv': simulation.lifetime.events, 'reachability_events.csv': simulation.lifetime.reachability_events, 'packets.csv': [{'packet_id': packet.packet_id, 'source_id': packet.source_id, 'created_at': packet.created_at, 'delivered_at': packet.delivered_at, 'status': packet.status.value, 'reason': packet.drop_reason, 'payload_size_bytes': packet.size_bytes, 'wire_size_bytes': packet.wire_size_bytes, 'planned_route': ' -> '.join(packet.planned_route), 'planned_hops': packet.planned_hop_count, 'actual_path': ' -> '.join(packet.actual_path), 'actual_hops': packet.actual_hop_count, 'latency_s': packet.latency_s} for packet in simulation.traffic_gen.generated_packets]}
    if simulation.detector is not None:
        files.extend(save_detector_outputs(simulation.detector, directory))
    for name, rows in tables.items():
        if rows:
            files.append(save_csv(pd.DataFrame(rows), directory / name))
    for name, data in (extra_outputs or {}).items():
        files.append(save_json(data, directory / name))
    manifest_path = directory / 'run_manifest.json'
    manifest = create_run_manifest(simulation.config, [*files, manifest_path], repository_root)
    manifest['attack'] = simulation.traffic_gen.attack.to_dict()
    manifest['communication_range_m'] = simulation.network.communication_range_m
    manifest['coordinates'] = simulation.network.coordinates()
    manifest['physical_edges'] = sorted((sorted(edge) for edge in simulation.network.graph.edges))
    manifest['observer'] = None if simulation.detector is None else simulation.detector.model_metadata()
    save_json(manifest, manifest_path)
    return directory
