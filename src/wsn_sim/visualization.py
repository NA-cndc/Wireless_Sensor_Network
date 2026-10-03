"""Headless Matplotlib topology visualization."""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import networkx as nx

from wsn_sim.network import Network

matplotlib.use("Agg")


def save_topology_plot(network: Network, path: str | Path) -> Path:
    """Render sensors, sinks, and links to a PNG and close the figure.

    Args:
        network: Network whose active graph is rendered.
        path: Target PNG path; parent directories are created automatically.

    Returns:
        The path of the saved image.
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    positions = {
        node_id: (data["x"], data["y"]) for node_id, data in network.graph.nodes(data=True)
    }
    sensor_positions = [positions[node_id] for node_id in network.sensors]
    sink_positions = [positions[node_id] for node_id in network.sinks]

    figure, axis = plt.subplots(figsize=(9, 9))
    try:
        nx.draw_networkx_edges(
            network.graph,
            positions,
            ax=axis,
            edge_color="gray",
            width=0.45,
            alpha=0.25,
        )
        axis.scatter(
            [position[0] for position in sensor_positions],
            [position[1] for position in sensor_positions],
            c="tab:blue",
            marker="o",
            s=15,
            label="Sensor",
            zorder=2,
        )
        axis.scatter(
            [position[0] for position in sink_positions],
            [position[1] for position in sink_positions],
            c="tab:red",
            marker="^",
            s=75,
            label="Sink",
            zorder=3,
        )
        axis.set_xlim(0, network.config.area_width_m)
        axis.set_ylim(0, network.config.area_height_m)
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("X coordinate (m)")
        axis.set_ylabel("Y coordinate (m)")
        axis.set_title(
            f"WSN topology (R={network.communication_range_m:g} m, seed={network.config.seed})"
        )
        axis.legend()
        axis.grid(alpha=0.2)
        figure.tight_layout()
        figure.savefig(output_path, dpi=150, bbox_inches="tight")
    finally:
        plt.close(figure)
    return output_path
