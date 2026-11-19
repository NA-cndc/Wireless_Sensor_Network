from dataclasses import replace
import networkx as nx
import config
from wsn_sim.network import Network

def create_wsn_topology() -> nx.Graph:
    parameters = replace(config.DEFAULT_CONFIG, seed=config.SEED, num_sensors=config.NUM_SENSORS, num_sinks=config.NUM_SINKS, area_width_m=config.AREA_SIZE, area_height_m=config.AREA_SIZE)
    network = Network(parameters, config.TX_RADIUS)
    mapping = {node: index for index, node in enumerate(network.graph, 1)}
    graph = nx.relabel_nodes(network.graph, mapping)
    for _, data in graph.nodes(data=True):
        data.update(pos=(data['x'], data['y']), type=data['node_type'])
    for _, _, data in graph.edges(data=True):
        data['distance'] = data['distance_m']
    return graph
