"""Shared pytest fixtures for the WSN simulation tests."""

import os
from pathlib import Path
import shutil

import pytest

from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network

for _git_dir in [Path(r"D:\ProgramFiles\Git\cmd"), Path(r"C:\Program Files\Git\cmd")]:
    if _git_dir.exists() and not shutil.which("git"):
        os.environ["PATH"] = str(_git_dir) + os.pathsep + os.environ.get("PATH", "")



@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def config(project_root: Path) -> SimulationConfig:
    return SimulationConfig.from_json(project_root / "configs" / "default.json")


@pytest.fixture()
def network(config: SimulationConfig) -> Network:
    return Network(config, communication_range_m=250)