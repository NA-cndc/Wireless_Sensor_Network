"""Root alias and backwards compatibility wrapper for wsn_sim.config."""

from pathlib import Path

from wsn_sim.config import SimulationConfig

_default_config_path = Path(__file__).resolve().parent / "configs" / "default.json"
_default_config = SimulationConfig.from_json(_default_config_path)

AREA_SIZE = int(_default_config.area_width_m)
NUM_SENSORS = _default_config.num_sensors
NUM_SINKS = _default_config.num_sinks
TX_RADIUS = int(_default_config.communication_ranges_m[1] if len(_default_config.communication_ranges_m) > 1 else 300)
SEED = _default_config.seed

__all__ = ["AREA_SIZE", "NUM_SENSORS", "NUM_SINKS", "TX_RADIUS", "SEED", "SimulationConfig"]