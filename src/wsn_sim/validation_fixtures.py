'''Deterministic network fixtures used to validate exported WSN metrics.'''

from __future__ import annotations

import networkx as nx

from wsn_sim.config import SimulationConfig
from wsn_sim.energy import RadioModel
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network


def build_real_traffic_lifetime_network(config: SimulationConfig) -> Network:
    '''Build the four-sensor known-answer lifetime fixture.

    Each sensor is one 50 m hop from the sink and starts with enough energy for
    exactly one through four 128-byte transmissions under the configured radio
    model. The caller must provide the 128-byte, 10-second traffic configuration
    used by the lifetime validation scenario.
    '''
    if config.num_sensors != 4 or config.num_sinks != 1:
        raise ValueError('lifetime fixture requires four sensors and one sink')
    if config.packet_size_bytes != 128 or config.packet_interval_s != 10.0:
        raise ValueError(
            'lifetime fixture requires 128-byte packets at a 10-second interval'
        )

    radio = RadioModel()
    tx_cost_j = radio.compute_tx_energy(config.packet_size_bytes * 8, 50.0)
    network = Network(config, communication_range_m=100.0)
    sink = Sink('sink_00', 0.0, 0.0)
    network.sensors = {
        'S1': Sensor('S1', 50.0, 0.0, 1 * tx_cost_j),
        'S2': Sensor('S2', 0.0, 50.0, 2 * tx_cost_j),
        'S3': Sensor('S3', -50.0, 0.0, 3 * tx_cost_j),
        'S4': Sensor('S4', 0.0, -50.0, 4 * tx_cost_j),
    }
    network.sinks = {sink.node_id: sink}
    network.graph = nx.Graph()
    network.graph.add_node(sink.node_id, node_type='sink', x=sink.x, y=sink.y)
    for sensor in network.sensors.values():
        network.graph.add_node(
            sensor.node_id,
            node_type='sensor',
            x=sensor.x,
            y=sensor.y,
        )
        network.graph.add_edge(
            sensor.node_id,
            sink.node_id,
            distance_m=50.0,
            weight=50.0,
        )
    network.communication_range_m = 100.0
    return network
