"""Configuration loading and validation for WSN experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping


REQUIRED_COMMUNICATION_RANGES_M = {250.0, 300.0, 350.0}


def _require_positive_number(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _require_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Store and validate all parameters used by the initial simulation."""

    area_width_m: float
    area_height_m: float
    num_sensors: int
    num_sinks: int
    initial_energy_j: float
    packet_size_bytes: int
    packet_interval_s: float
    communication_ranges_m: tuple[float, ...]
    seed: int

    def __post_init__(self) -> None:
        """Validate types, positive values, and required communication ranges."""
        _require_positive_number("area_width_m", self.area_width_m)
        _require_positive_number("area_height_m", self.area_height_m)
        _require_positive_integer("num_sensors", self.num_sensors)
        _require_positive_integer("num_sinks", self.num_sinks)
        _require_positive_number("initial_energy_j", self.initial_energy_j)
        _require_positive_integer("packet_size_bytes", self.packet_size_bytes)
        _require_positive_number("packet_interval_s", self.packet_interval_s)

        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise TypeError("seed must be an integer")
        if not isinstance(self.communication_ranges_m, tuple):
            raise TypeError("communication_ranges_m must be a tuple")
        if not self.communication_ranges_m:
            raise ValueError("communication_ranges_m must not be empty")
        for radius in self.communication_ranges_m:
            _require_positive_number("communication range", radius)
        if not REQUIRED_COMMUNICATION_RANGES_M.issubset(
            set(self.communication_ranges_m)
        ):
            raise ValueError(
                "communication_ranges_m must contain 250, 300, and 350"
            )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SimulationConfig":
        """Create a validated configuration from a mapping.

        Args:
            data: Mapping containing every configuration field.

        Returns:
            A validated immutable configuration.

        Raises:
            TypeError: If the input or range collection has an invalid type.
            ValueError: If a required field is missing or has an invalid value.
        """
        if not isinstance(data, Mapping):
            raise TypeError("configuration must be a mapping")

        required_fields = {
            "area_width_m",
            "area_height_m",
            "num_sensors",
            "num_sinks",
            "initial_energy_j",
            "packet_size_bytes",
            "packet_interval_s",
            "communication_ranges_m",
            "seed",
        }
        missing = sorted(required_fields.difference(data))
        if missing:
            raise ValueError(f"missing configuration fields: {', '.join(missing)}")

        ranges = data["communication_ranges_m"]
        if not isinstance(ranges, (list, tuple)):
            raise TypeError("communication_ranges_m must be a list or tuple")

        return cls(
            area_width_m=data["area_width_m"],
            area_height_m=data["area_height_m"],
            num_sensors=data["num_sensors"],
            num_sinks=data["num_sinks"],
            initial_energy_j=data["initial_energy_j"],
            packet_size_bytes=data["packet_size_bytes"],
            packet_interval_s=data["packet_interval_s"],
            communication_ranges_m=tuple(ranges),
            seed=data["seed"],
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "SimulationConfig":
        """Load a UTF-8 JSON file and return a validated configuration.

        Args:
            path: Location of the JSON configuration file.

        Returns:
            A validated :class:`SimulationConfig` instance.
        """
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as file_handle:
            data = json.load(file_handle)
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the configuration."""
        data = asdict(self)
        data["communication_ranges_m"] = list(self.communication_ranges_m)
        return data
