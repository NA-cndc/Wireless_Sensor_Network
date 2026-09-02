"""Tests for configuration loading and validation."""

from dataclasses import replace
from pathlib import Path

import pytest

from wsn_sim.config import SimulationConfig


def test_load_default_configuration(project_root: Path) -> None:
    config = SimulationConfig.from_json(project_root / "configs" / "default.json")

    assert (config.area_width_m, config.area_height_m) == (3000, 3000)
    assert config.num_sensors == 450
    assert config.num_sinks == 7
    assert config.communication_ranges_m == (250, 300, 350)
    assert config.seed == 42


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("area_width_m", 0),
        ("area_height_m", -1),
        ("num_sensors", 0),
        ("num_sinks", -1),
        ("initial_energy_j", 0),
        ("packet_size_bytes", -128),
        ("packet_interval_s", 0),
    ],
)
def test_reject_non_positive_configuration_values(
    config: SimulationConfig,
    field: str,
    invalid_value: int,
) -> None:
    with pytest.raises(ValueError):
        replace(config, **{field: invalid_value})


def test_reject_missing_required_range(config: SimulationConfig) -> None:
    with pytest.raises(ValueError, match="250, 300, and 350"):
        replace(config, communication_ranges_m=(250, 300))


def test_reject_non_integer_seed(config: SimulationConfig) -> None:
    with pytest.raises(TypeError, match="seed"):
        replace(config, seed=42.5)
