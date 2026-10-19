"""Persistence helpers for tabular results and reproducibility metadata."""

from __future__ import annotations

import json
import hashlib
import platform
import subprocess
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from wsn_sim.config import SimulationConfig

RUNTIME_LIBRARIES = ("networkx", "simpy", "numpy", "pandas", "matplotlib")
SOURCE_HASH_ROOTS = ("src", "scripts", "configs", "tests")


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
        json.dump(data, file_handle, ensure_ascii=False, indent=2, allow_nan=False)
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


def _source_tree_sha256(repository_root: Path) -> str:
    """Hash reproducibility-relevant source/config/test bytes in stable order."""
    digest = hashlib.sha256()
    files = [repository_root / "pyproject.toml"]
    for directory in SOURCE_HASH_ROOTS:
        root = repository_root / directory
        if root.exists():
            files.extend(path for path in root.rglob("*") if path.is_file())
    for path in sorted(files, key=lambda item: item.relative_to(repository_root).as_posix()):
        relative = path.relative_to(repository_root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def create_run_manifest(
    config: SimulationConfig,
    generated_files: Iterable[str | Path],
    repository_root: str | Path,
    run_metadata: dict[str, Any] | None = None,
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
    manifest = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "seed": config.seed,
        "configuration": config.to_dict(),
        "python_version": platform.python_version(),
        "library_versions": _library_versions(),
        "git_commit": _git_output(root, "rev-parse", "HEAD"),
        "source_tree_sha256": _source_tree_sha256(root),
        "git_branch": _git_output(root, "branch", "--show-current"),
        "working_tree_clean": status == "" if status is not None else None,
        "working_tree_changes": status.splitlines() if status else [],
        "generated_files": [str(Path(path)) for path in generated_files],
    }
    if run_metadata:
        manifest.update(run_metadata)
    return manifest
