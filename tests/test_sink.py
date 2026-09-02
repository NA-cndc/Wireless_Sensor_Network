"""Tests for unlimited-energy, duplicate-safe sinks."""

from wsn_sim.models import Packet, PacketStatus, Sink


def test_sink_receives_packet_and_marks_delivery() -> None:
    sink = Sink("sink_00", 1.0, 2.0)
    packet = Packet("packet_001", "sensor_000", 0.0, 128)

    assert sink.receive(packet, received_at=3.0)
    assert packet.status is PacketStatus.DELIVERED
    assert packet.delivered_at == 3.0
    assert sink.received_packet_count == 1


def test_sink_deduplicates_packet_id() -> None:
    sink = Sink("sink_00", 1.0, 2.0)
    first = Packet("packet_001", "sensor_000", 0.0, 128)
    duplicate = Packet("packet_001", "sensor_001", 1.0, 128)

    assert sink.receive(first, received_at=3.0)
    assert not sink.receive(duplicate, received_at=4.0)
    assert sink.received_packet_count == 1


def test_sink_has_no_energy_state() -> None:
    assert not hasattr(Sink("sink_00", 1.0, 2.0), "energy_j")
