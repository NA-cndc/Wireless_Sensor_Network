from __future__ import annotations
from dataclasses import MISSING, asdict, dataclass, fields
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping
from wsn_sim.randomness import stable_seed
REQUIRED_COMMUNICATION_RANGES_M = {250.0, 300.0, 350.0}
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / 'configs/plan.json'

def _read_json_config(path: Path, parents: frozenset[Path]=frozenset()) -> dict[str, Any]:
    path = path.resolve()
    if path in parents:
        raise ValueError(f'configuration inheritance cycle: {path}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise TypeError('configuration must be a mapping')
    if 'extends' not in data:
        return data
    parent = data.pop('extends')
    if not isinstance(parent, str) or not parent.strip():
        raise TypeError('extends must be a non-empty configuration path')
    return {**_read_json_config(path.parent / parent, parents | {path}), **data}

def require_number(name: str, value: object, minimum: float=0, *, strict: bool=True) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f'{name} must be a number')
    if not isfinite(value) or (value <= minimum if strict else value < minimum):
        raise ValueError(f'invalid {name}: {value}')

def require_integer(name: str, value: object, minimum: int=1) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f'{name} must be an integer')
    if value < minimum:
        raise ValueError(f'{name} must be at least {minimum}')

def require_probability(name: str, value: object) -> None:
    require_number(name, value, strict=False)
    if value > 1:
        raise ValueError(f'{name} must not exceed one')

@dataclass(frozen=True, slots=True)
class DetectorConfig:
    beta_trust: float
    window_size_s: float
    forwarding_timeout_s: float
    min_observations: int
    trust_threshold: float
    consecutive_bad_windows: int
    initial_trust: float
    isolation_duration_s: float
    calibration_status: str = 'TEST_ONLY'

    def __post_init__(self) -> None:
        require_probability('beta_trust', self.beta_trust)
        if self.beta_trust in (0, 1):
            raise ValueError('beta_trust must be strictly between zero and one')
        for name in ('window_size_s', 'forwarding_timeout_s', 'isolation_duration_s'):
            require_number(name, getattr(self, name))
        for name in ('min_observations', 'consecutive_bad_windows'):
            require_integer(name, getattr(self, name))
        for name in ('trust_threshold', 'initial_trust'):
            require_probability(name, getattr(self, name))
        if self.calibration_status not in {'TEST_ONLY', 'CALIBRATED'}:
            raise ValueError('calibration_status must be TEST_ONLY or CALIBRATED')

@dataclass(frozen=True, slots=True)
class SimulationConfig:
    area_width_m: float
    area_height_m: float
    num_sensors: int
    num_sinks: int
    initial_energy_j: float
    packet_size_bytes: int
    packet_interval_s: float
    communication_ranges_m: tuple[float, ...]
    seed: int
    communication_range_m: float = 300.0
    energy_threshold_ratio: float = 0.2
    energy_epsilon_j: float = 1e-12
    max_rounds: int = 10000
    routing_algorithm: str = 'EMHR'
    wire_size_bytes: int | None = None
    bandwidth_bps: float = 250000.0
    attacker_ratio: float = 0.0
    attacker_ids: tuple[str, ...] | None = None
    attacker_selection: str = 'random'
    p_drop: float = 0.5
    channel_loss_probability: float = 0.0
    detector: DetectorConfig | None = None
    config_profile: str = 'CUSTOM'

    def __post_init__(self) -> None:
        for name in ('area_width_m', 'area_height_m', 'initial_energy_j', 'packet_interval_s', 'communication_range_m', 'energy_epsilon_j', 'bandwidth_bps'):
            require_number(name, getattr(self, name))
        for name in ('num_sensors', 'num_sinks', 'packet_size_bytes', 'max_rounds'):
            require_integer(name, getattr(self, name))
        require_integer('seed', self.seed, 0)
        for name in ('energy_threshold_ratio', 'attacker_ratio', 'p_drop', 'channel_loss_probability'):
            require_probability(name, getattr(self, name))
        if not isinstance(self.communication_ranges_m, tuple):
            raise TypeError('communication_ranges_m must be a tuple')
        for radius in self.communication_ranges_m:
            require_number('communication range', radius)
        if not REQUIRED_COMMUNICATION_RANGES_M.issubset(self.communication_ranges_m):
            raise ValueError('communication_ranges_m must contain 250, 300, and 350')
        if self.wire_size_bytes is not None:
            require_integer('wire_size_bytes', self.wire_size_bytes, self.packet_size_bytes)
        if self.attacker_ids is not None:
            if not isinstance(self.attacker_ids, tuple) or any((not isinstance(node, str) or not node for node in self.attacker_ids)):
                raise TypeError('attacker_ids must be a tuple of non-empty sensor IDs')
            if len(set(self.attacker_ids)) != len(self.attacker_ids):
                raise ValueError('attacker_ids must not contain duplicates')
        if not isinstance(self.attacker_selection, str):
            raise TypeError('attacker_selection must be a string')
        if self.attacker_selection not in {'random', 'near_sink'}:
            raise ValueError('attacker_selection must be random or near_sink')
        if self.detector is not None and (not isinstance(self.detector, DetectorConfig)):
            raise TypeError('detector must be a DetectorConfig')
        if self.routing_algorithm not in {'MHR', 'EMHR', 'S_EMHR'}:
            raise ValueError('routing_algorithm must be MHR, EMHR, or S_EMHR')
        if self.routing_algorithm == 'S_EMHR' and self.detector is None:
            raise ValueError('S_EMHR needs explicit detector calibration or TEST_ONLY settings')
        if not isinstance(self.config_profile, str):
            raise TypeError('config_profile must be a string')
        if self.config_profile not in {'PLAN', 'LEGACY_ENERGY_REGRESSION', 'TEST_ONLY', 'CUSTOM'}:
            raise ValueError('invalid config_profile')

    @property
    def energy_threshold_j(self) -> float:
        return self.initial_energy_j * self.energy_threshold_ratio

    @property
    def energy_configuration(self) -> dict[str, float]:
        return {'initial_energy_j': self.initial_energy_j, 'energy_threshold_ratio': self.energy_threshold_ratio, 'energy_threshold_j': self.energy_threshold_j}

    @property
    def transmission_size_bytes(self) -> int:
        return self.packet_size_bytes if self.wire_size_bytes is None else self.wire_size_bytes

    @property
    def max_duration_s(self) -> float:
        return self.max_rounds * self.packet_interval_s

    @property
    def stream_seeds(self) -> dict[str, int]:
        return {name: self.seed if name == 'topology' else stable_seed(self.seed, name) for name in ('topology', 'traffic', 'routing', 'attacker_selection', 'attack_decision', 'channel_loss')}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SimulationConfig:
        if not isinstance(data, Mapping):
            raise TypeError('configuration must be a mapping')
        values = dict(data)
        for name in ('communication_ranges_m', 'attacker_ids'):
            if name in values and values[name] is not None:
                if not isinstance(values[name], (list, tuple)):
                    raise TypeError(f'{name} must be a list or tuple')
                values[name] = tuple(values[name])
        if values.get('detector') is not None:
            values['detector'] = DetectorConfig(**values['detector'])
        config_fields = {item.name: item for item in fields(cls)}
        unknown = set(values) - config_fields.keys()
        if unknown:
            raise ValueError(f"unknown configuration fields: {', '.join(sorted(unknown))}")
        missing = {name for name, item in config_fields.items() if name not in values and item.default is MISSING and (item.default_factory is MISSING)}
        if missing:
            raise ValueError(f"missing configuration fields: {', '.join(sorted(missing))}")
        return cls(**values)

    @classmethod
    def from_json(cls, path: str | Path) -> SimulationConfig:
        return cls.from_dict(_read_json_config(Path(path)))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for name in ('communication_ranges_m', 'attacker_ids'):
            if data[name] is not None:
                data[name] = list(data[name])
        return data
