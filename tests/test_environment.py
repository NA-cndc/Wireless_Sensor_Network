"""Environment initialization and reproducibility test suite.

Verifies:
1. Environment configuration parameters match the 450-sensor, 7-sink specification.
2. Random seed determinism and 100% reproducibility across distinct runs.
3. Network connectivity, reachability, and absence of excessive isolated nodes.
4. Logging and CSV persistence mechanisms.
"""

from pathlib import Path

from wsn_sim.config import SimulationConfig
from wsn_sim.logger import save_to_csv, setup_logger
from wsn_sim.network import Network


def test_environment_config_values(config: SimulationConfig) -> None:
    """Verify default configuration parameters meet the experiment design."""
    assert config.num_sensors == 450
    assert config.num_sinks == 7
    assert config.area_width_m == 3000.0
    assert config.area_height_m == 3000.0
    assert 300.0 in config.communication_ranges_m
    assert config.initial_energy_j == 5.0
    assert config.packet_size_bytes == 128
    assert config.packet_interval_s == 10.0


def test_random_seed_reproducibility(config: SimulationConfig) -> None:
    """Verify that using the same seed produces identical node coordinates and graphs."""
    net1 = Network(config, communication_range_m=300.0)
    net2 = Network(config, communication_range_m=300.0)

    # Assert exact coordinate equivalence for all 457 nodes
    coords1 = net1.coordinates()
    coords2 = net2.coordinates()
    assert coords1 == coords2

    # Assert identical edges
    assert set(net1.graph.edges()) == set(net2.graph.edges())


def test_virtual_super_sink_and_connectivity(config: SimulationConfig) -> None:
    """Verify virtual super-sink construction and connectivity verification."""
    net = Network(config, communication_range_m=300.0)
    v_graph = net.build_virtual_super_sink_graph("virtual_super_sink")

    assert "virtual_super_sink" in v_graph
    # Verify virtual super sink connects to all 7 sinks with distance 0
    for sink_id in net.sinks:
        assert v_graph.has_edge("virtual_super_sink", sink_id)
        assert v_graph.edges["virtual_super_sink", sink_id]["distance_m"] == 0.0

    # Connectivity check
    conn = net.check_network_connectivity()
    assert conn["total_sensors"] == 450
    assert conn["total_sinks"] == 7
    assert conn["meets_95_percent_threshold"] is True
    assert conn["routable_ratio"] >= 0.95


def test_logging_and_csv_persistence(tmp_path: Path) -> None:
    """Verify logger setup and CSV persistence functions."""
    log_file = tmp_path / "test.log"
    logger = setup_logger("Test_Logger", log_file=log_file)
    assert logger is not None
    logger.info("Test message")
    assert log_file.exists()

    csv_file = tmp_path / "test_output.csv"
    headers = ["timestamp", "seed", "nodes", "edges"]
    row = ["2026-09-11 12:00:00", 42, 457, 3019]

    save_to_csv(csv_file, headers, row)
    assert csv_file.exists()
    content = csv_file.read_text(encoding="utf-8")
    assert "timestamp,seed,nodes,edges" in content
    assert "42,457,3019" in content
