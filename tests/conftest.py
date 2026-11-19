from dataclasses import replace
from pathlib import Path
import pytest
from wsn_sim.config import DetectorConfig, SimulationConfig
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network

@pytest.fixture(scope='session')
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]

@pytest.fixture(scope='session')
def config(project_root: Path) -> SimulationConfig:
    return SimulationConfig.from_json(project_root / 'configs/plan.json')

@pytest.fixture
def detector_config() -> DetectorConfig:
    return DetectorConfig(0.5, 5, 1, 1, 0.8, 2, 1, 10)

@pytest.fixture
def network(config: SimulationConfig) -> Network:
    return Network(config, communication_range_m=250)

@pytest.fixture
def network_factory(config):

    def make(sensors, edges=None, sinks=None, **changes):
        sinks = {'k': (100, 0)} if sinks is None else sinks
        changes.setdefault('config_profile', 'TEST_ONLY')
        cfg = replace(config, num_sensors=len(sensors), num_sinks=len(sinks), **changes)
        net = Network(cfg, sensors={node: Sensor(node, *xy, cfg.initial_energy_j) for node, xy in sensors.items()}, sinks={node: Sink(node, *xy) for node, xy in sinks.items()})
        if edges is not None:
            net.graph.remove_edges_from(list(net.graph.edges))
            for left, right in edges:
                net.graph.add_edge(left, right, distance_m=net.distance(left, right))
        return net
    return make
