"""Minimal SimPy integration for environment smoke testing."""

from __future__ import annotations

from collections.abc import Generator

import simpy

from wsn_sim.network import Network


class Simulation:
    """Own a SimPy environment for a given WSN topology."""

    def __init__(
        self,
        network: Network,
        env: simpy.Environment | None = None,
    ) -> None:
        """Create a simulation using a supplied or fresh SimPy environment."""
        self.network = network
        self.env = env if env is not None else simpy.Environment()

    def smoke_process(self, timeout_s: float) -> Generator[simpy.Event, None, None]:
        """Yield one timeout event to verify that SimPy scheduling works."""
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than zero")
        yield self.env.timeout(timeout_s)

    def run_for(self, duration_s: float) -> float:
        """Run the smoke process for a relative duration.

        Args:
            duration_s: Positive amount of simulated time to advance.

        Returns:
            The resulting absolute SimPy time.
        """
        process = self.env.process(self.smoke_process(duration_s))
        self.env.run(until=process)
        return float(self.env.now)
