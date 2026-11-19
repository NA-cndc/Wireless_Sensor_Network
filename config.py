from wsn_sim.config import DEFAULT_CONFIG_PATH, SimulationConfig
DEFAULT_CONFIG = SimulationConfig.from_json(DEFAULT_CONFIG_PATH)
AREA_SIZE = DEFAULT_CONFIG.area_width_m
NUM_SENSORS = DEFAULT_CONFIG.num_sensors
NUM_SINKS = DEFAULT_CONFIG.num_sinks
TX_RADIUS = DEFAULT_CONFIG.communication_range_m
SEED = DEFAULT_CONFIG.seed
