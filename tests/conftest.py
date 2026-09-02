"""Shared pytest fixtures for the WSN simulation tests."""

from pathlib import Path

import pytest

from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def config(project_root: Path) -> SimulationConfig:
    return SimulationConfig.from_json(project_root / "configs" / "default.json")


@pytest.fixture()
def network(config: SimulationConfig) -> Network:
    return Network(config, communication_range_m=250)
