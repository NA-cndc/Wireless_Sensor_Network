"""Tests for the minimal SimPy integration."""

import simpy

from wsn_sim.network import Network
from wsn_sim.simulation import Simulation


def test_environment_initializes_and_advances(network: Network) -> None:
    environment = simpy.Environment()
    simulation = Simulation(network, environment)

    now = simulation.run_for(2.5)

    assert simulation.env is environment
    assert now == 2.5
    assert environment.now == 2.5


def test_multiple_runs_use_relative_time(network: Network) -> None:
    simulation = Simulation(network)

    simulation.run_for(1.0)
    now = simulation.run_for(2.0)

    assert now == 3.0
