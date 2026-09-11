"""Tests for verification engine exporters (ns-3, OMNeT++, Contiki-NG)."""

from pathlib import Path

from wsn_sim.exporters import (
    export_to_cooja,
    export_to_ns3_mobility,
    export_to_omnetpp_ned,
)
from wsn_sim.network import Network


def test_export_to_ns3_mobility(network: Network, tmp_path: Path) -> None:
    output_file = tmp_path / "mobility.tcl"
    result_path = export_to_ns3_mobility(network, output_file)

    assert result_path.exists()
    content = result_path.read_text(encoding="utf-8")
    assert "$node_(0) set X_" in content
    assert "$node_(10) set X_" in content


def test_export_to_omnetpp_ned(network: Network, tmp_path: Path) -> None:
    output_file = tmp_path / "network.ned"
    result_path = export_to_omnetpp_ned(network, output_file, network_name="TestWSN")

    assert result_path.exists()
    content = result_path.read_text(encoding="utf-8")
    assert "network TestWSN" in content
    assert "sensor_000: SensorNode" in content
    assert "sink_00: WirelessHost" in content


def test_export_to_cooja(network: Network, tmp_path: Path) -> None:
    output_file = tmp_path / "sim.csc"
    result_path = export_to_cooja(network, output_file)

    assert result_path.exists()
    content = result_path.read_text(encoding="utf-8")
    assert "<motetype_identifier>sink_mote</motetype_identifier>" in content
    assert "<motetype_identifier>sensor_mote</motetype_identifier>" in content
