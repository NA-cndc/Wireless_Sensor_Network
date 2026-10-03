"""Root compatibility wrapper for network topology generation and visualization.

Quy về package src/wsn_sim làm nguồn logic chính để bảo đảm tính nhất quán.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import networkx as nx

import config
from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network
from wsn_sim.visualization import save_topology_plot


def create_wsn_topology(
    seed: int | None = None,
    range_m: float | None = None,
    include_virtual_sink: bool = True,
) -> nx.Graph:
    """Sinh topology mạng cảm biến WSN dựa trên logic chuẩn của wsn_sim.network.Network."""
    s = seed if seed is not None else config.SEED
    r = range_m if range_m is not None else float(config.TX_RADIUS)

    cfg = SimulationConfig(
        area_width_m=float(config.AREA_SIZE),
        area_height_m=float(config.AREA_SIZE),
        num_sensors=config.NUM_SENSORS,
        num_sinks=config.NUM_SINKS,
        initial_energy_j=5.0,
        packet_size_bytes=128,
        packet_interval_s=10.0,
        communication_ranges_m=(250.0, 300.0, 350.0),
        seed=s,
    )
    net = Network(cfg, communication_range_m=r)

    if include_virtual_sink:
        return net.build_virtual_super_sink_graph("virtual_sink")
    return net.graph


def visualize_network(G: nx.Graph, output_file: str | Path | None = None) -> None:
    """Vẽ topology mạng cảm biến."""
    if output_file:
        plt.figure(figsize=(9, 9))
    else:
        plt.figure(figsize=(9, 9))

    pos = {node: (data.get("x", 0.0), data.get("y", 0.0)) for node, data in G.nodes(data=True)}
    sensors = [n for n, d in G.nodes(data=True) if d.get("node_type") == "sensor" or str(n).startswith("sensor_")]
    sinks = [n for n, d in G.nodes(data=True) if d.get("node_type") == "sink" or str(n).startswith("sink_")]

    nx.draw_networkx_edges(G, pos, alpha=0.2, edge_color="gray", width=0.5)
    nx.draw_networkx_nodes(G, pos, nodelist=sensors, node_color="tab:blue", node_size=15, label="Sensor")
    nx.draw_networkx_nodes(G, pos, nodelist=sinks, node_color="tab:red", node_size=80, node_shape="^", label="Sink")

    plt.title(f"WSN Topology ({len(sensors)} Sensors, {len(sinks)} Sinks)")
    plt.legend()
    plt.grid(True, linestyle="--", alpha=0.4)

    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_file, dpi=150, bbox_inches="tight")
        plt.close()
    else:
        plt.show()


def check_network_connectivity(G: nx.Graph) -> dict[str, Any]:
    """Kiểm tra các node cô lập và tính liên thông của mạng."""
    g_phys = G.copy()
    if g_phys.has_node("virtual_sink"):
        g_phys.remove_node("virtual_sink")
    if g_phys.has_node(0):
        g_phys.remove_node(0)

    isolated_nodes = list(nx.isolates(g_phys))
    components = list(nx.connected_components(g_phys))

    return {
        "isolated_nodes_count": len(isolated_nodes),
        "connected_components_count": len(components),
        "largest_component_size": max((len(c) for c in components), default=0),
    }


__all__ = [
    "create_wsn_topology",
    "visualize_network",
    "check_network_connectivity",
]