"""Reproducible WSN node generation and connectivity graph construction."""

from __future__ import annotations

import networkx as nx

from analysis.foundation.config import SimulationConfig
from analysis.foundation.models import Sensor, Sink
from wsn_sim.topology import PhysicalTopology, generate_nodes, physical_graph, sink_connected_sensor_ids


class Network(PhysicalTopology):
    """Manage stationary nodes and a bidirectional NetworkX topology graph."""

    def __init__(
        self,
        config: SimulationConfig,
        communication_range_m: float | None = None,
        *,
        range_m: float | None = None,
    ) -> None:
        """Generate nodes from ``config.seed`` and build the first topology.

        Args:
            config: Validated simulation parameters.
            communication_range_m: Optional initial radio range. The first range
                in the configuration is used when omitted.
            range_m: Optional alias for ``communication_range_m``.
        """
        self.config = config
        self.topology_seed = config.seed
        self.sensors: dict[str, Sensor] = {}
        self.sinks: dict[str, Sink] = {}
        self.graph = nx.Graph()
        self.communication_range_m = 0.0
        self._generate_nodes()
        effective_range = (
            range_m if communication_range_m is None else communication_range_m
        )
        initial_range = (
            config.communication_ranges_m[0]
            if effective_range is None
            else effective_range
        )
        self.build_graph(initial_range)

    def _generate_nodes(self) -> None:
        self.sensors, self.sinks = generate_nodes(self.config, Sensor, Sink)

    def build_graph(
        self,
        communication_range_m: float | None = None,
        *,
        range_m: float | None = None,
    ) -> nx.Graph:
        """Build a fresh graph without modifying generated node coordinates.

        Args:
            communication_range_m: Positive Euclidean link threshold in metres.
            range_m: Optional alias for ``communication_range_m``.

        Returns:
            The newly built undirected :class:`networkx.Graph`.

        Raises:
            ValueError: If the communication range is not positive.
            TypeError: If neither communication_range_m nor range_m is provided.
        """
        effective_range = (
            range_m if communication_range_m is None else communication_range_m
        )
        if effective_range is None:
            raise TypeError(
                "build_graph() missing required argument: 'communication_range_m' or 'range_m'"
            )
        if effective_range <= 0:
            raise ValueError("communication_range_m must be greater than zero")

        self.graph = physical_graph(self.sensors, self.sinks, effective_range)
        self.communication_range_m = float(effective_range)
        return self.graph

    def routable_sensor_ids(self, *, alive_only: bool = False) -> list[str]:
        """Return sensors in connected components containing at least one sink."""
        return sink_connected_sensor_ids(self.graph, self.sensors, self.sinks, alive_only=alive_only)
