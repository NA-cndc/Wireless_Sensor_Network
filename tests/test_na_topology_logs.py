import csv
from dataclasses import replace
from itertools import combinations
from math import dist

import numpy as np
import pytest

from analysis.foundation.config import SimulationConfig as FoundationConfig
from analysis.foundation.network import Network as FoundationNetwork
from analysis.foundation.runner import CONFIG_PATH
from analysis.foundation.simulation import Simulation as FoundationSimulation
from analysis.foundation.storage import save_simulation_run
from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network
from wsn_sim.recording import RunRecorder
from wsn_sim.simulation import Simulation
from wsn_sim.topology import topology_record


def test_topology_matches_na_for_multiple_seeds_and_ranges(project_root):
    foundation = FoundationConfig.from_json(CONFIG_PATH)
    security = SimulationConfig.from_json(project_root / "configs/default.json")
    sink_positions = (
        (1500, 1500), (500, 500), (2500, 500), (500, 2500),
        (2500, 2500), (500, 1500), (2500, 1500),
    )
    sensor_counts = set()
    for seed in (0, 36, 42, 51001):
        rng = np.random.default_rng(seed)
        count = int(rng.integers(400, 501))
        sensor_counts.add(count)
        coordinates = {
            f"sensor_{index:03d}": tuple(point)
            for index, point in enumerate(rng.uniform((0, 0), (3000, 3000), size=(count, 2)))
        }
        coordinates.update({f"sink_{index:02d}": point for index, point in enumerate(sink_positions)})
        for radius in (250, 300, 350):
            ground = FoundationNetwork(replace(foundation, seed=seed), radius)
            secured = Network(replace(security, seed=seed), radius)
            expected_edges = {
                frozenset((left, right))
                for left, right in combinations(coordinates, 2)
                if not (left.startswith("sink_") and right.startswith("sink_"))
                and dist(coordinates[left], coordinates[right]) <= radius
            }
            assert 400 <= count <= 500
            assert ground.coordinates() == secured.coordinates() == coordinates
            assert {frozenset(edge) for edge in ground.graph.edges} == expected_edges
            assert topology_record(ground) == topology_record(secured)
            assert topology_record(secured)["topology_seed"] == secured.config.stream_seeds["topology"]
    assert len(sensor_counts) > 1


@pytest.mark.parametrize("loss_time,expected", [(0, [0]), (15, [0, 10, 20])])
def test_foundation_log_stops_after_first_disconnected_sample(project_root, tmp_path, loss_time, expected):
    config = replace(
        FoundationConfig.from_json(CONFIG_PATH), num_sensors=2, num_sinks=1, duration_s=30,
    )
    network = FoundationNetwork(config)
    network.graph.remove_edges_from(list(network.graph.edges))
    if loss_time:
        network.graph.add_edge("sensor_000", "sink_00", distance_m=10)
    simulation = FoundationSimulation(network)

    def disconnect():
        yield simulation.env.timeout(loss_time)
        network.graph.remove_edge("sensor_000", "sink_00")

    if loss_time:
        simulation.env.process(disconnect())
    assert simulation.run_for() == 30
    path = save_simulation_run(simulation, tmp_path, project_root).with_suffix(".csv")
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert [float(row["Time_s"]) for row in rows] == expected
    assert int(rows[-1]["Alive_Nodes"]) == 2
    assert sum(int(row["Routable_Nodes"]) == 0 for row in rows) == 1
    assert simulation.summary()["log_end_s"] == expected[-1]
    assert simulation.summary()["generated_packets"] == 6


@pytest.mark.parametrize("mode", ["disconnected", "link_lost", "lnd", "eth", "isolation", "horizon"])
def test_security_log_does_not_control_simulation(network_factory, detector_config, tmp_path, mode):
    long_run = mode == "horizon"
    options = {"max_rounds": 1000 if long_run else 3}
    if mode == "isolation":
        options.update(detector=detector_config, routing_algorithm="S_EMHR")
    edges = [] if mode == "disconnected" else [("source", "relay"), ("relay", "k")]
    network = network_factory({"source": (120, 0), "relay": (110, 0)}, edges=edges, **options)
    recorder = RunRecorder(tmp_path, full_trace=True)
    simulation = Simulation(network.config, network=network, recorder=recorder)
    recorder.snapshot(simulation)
    if mode == "link_lost":
        simulation.set_link_state("relay", "k", available=False)
    elif mode == "lnd":
        simulation.run_for(5)
        for node in network.sensors.values():
            node.consume_energy(node.energy_j)
    elif mode == "eth":
        relay = network.sensors["relay"]
        relay.consume_energy(relay.energy_j - 0.5)
    elif mode == "isolation":
        simulation.detector.states["relay"].isolated_until = 100
        simulation.router.invalidate_cache()
    while simulation.env.now < network.config.max_duration_s and not simulation.stop_event.triggered:
        simulation.run_for(min(10, network.config.max_duration_s - simulation.env.now))
        recorder.snapshot(simulation)
    summary = recorder.snapshot(simulation) if mode == "lnd" else simulation.summary()
    recorder.close()
    with (tmp_path / "timeseries.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    times = [float(row["time_s"]) for row in rows]
    terminals = [row for row in rows if "0" in (row["alive_sensors"], row["physical_reachable_alive"])]
    if mode in {"disconnected", "link_lost", "lnd"}:
        assert terminals == rows[-1:]
        assert times == {"disconnected": [0], "link_lost": [0, 10], "lnd": [0, 5]}[mode]
    else:
        assert terminals == []
        assert times == list(range(0, int(network.config.max_duration_s) + 1, 10))
    if mode in {"eth", "isolation"}:
        assert int(rows[1]["routing_reachable_alive"]) < int(rows[1]["physical_reachable_alive"]) == 2
    assert summary["time_s"] == (5 if mode == "lnd" else network.config.max_duration_s)
    performance = summary["performance"]
    assert performance["generated"] == performance["delivered"] + performance["dropped"] + performance["pending_in_flight"]
    if long_run:
        assert summary["rounds"] == 1000
        assert performance["pending_in_flight"] == 2
        assert all(summary["lifetime"][name]["censored"] for name in ("FND", "HND", "LND"))
    elif mode in {"link_lost", "disconnected"}:
        assert performance["generated"] == 6
        assert summary["lifetime"]["functional_network_death"]["time_s"] == 0
