import config
from topology import create_wsn_topology

def test_config_values():
    assert (config.NUM_SENSORS, config.NUM_SINKS, config.TX_RADIUS) == (450, 7, 300)

def test_random_seed_reproducibility(monkeypatch):
    monkeypatch.setattr(config, 'SEED', 42)
    first = create_wsn_topology()
    second = create_wsn_topology()
    assert list(first.nodes(data='pos')) == list(second.nodes(data='pos'))
    assert set(first.edges) == set(second.edges)
    assert first.number_of_nodes() == config.NUM_SENSORS + config.NUM_SINKS
    assert all((position is not None for _, position in first.nodes(data='pos')))
