import numpy as np

from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network as SimulationNetwork


class Network(SimulationNetwork):
    """Generate the topology used for the two-stage comparison on main."""

    def _generate_nodes(self) -> None:
        config = self.config
        rng = np.random.default_rng(config.seed)
        count = int(rng.integers(max(1, config.num_sensors - 50), config.num_sensors + 51))
        bounds = (config.area_width_m, config.area_height_m)
        coordinates = rng.uniform((0.0, 0.0), bounds, size=(count, 2))
        for index, (x, y) in enumerate(coordinates):
            node_id = f"sensor_{index:03d}"
            self.sensors[node_id] = Sensor(node_id, float(x), float(y), config.initial_energy_j)

        sink_positions = (
            (1500.0, 1500.0), (500.0, 500.0), (2500.0, 500.0),
            (500.0, 2500.0), (2500.0, 2500.0), (500.0, 1500.0),
            (2500.0, 1500.0),
        )
        for index in range(config.num_sinks):
            if index < len(sink_positions):
                x, y = sink_positions[index]
            else:
                x, y = rng.uniform((0.0, 0.0), bounds)
            node_id = f"sink_{index:02d}"
            self.sinks[node_id] = Sink(node_id, float(x), float(y))
