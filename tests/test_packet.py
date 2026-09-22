"""Tests for Packet lifecycle state."""

import pytest

from wsn_sim.models import Packet, PacketStatus


def make_packet() -> Packet:
    return Packet("packet_001", "sensor_000", created_at=2.0, size_bytes=128)


def test_route_starts_at_source_and_counts_edges() -> None:
    packet = make_packet()
    packet.assign_route(["sensor_000", "sensor_001", "sink_00"])

    assert packet.status is PacketStatus.IN_TRANSIT
    assert packet.hop_count == 2


def test_reject_route_not_starting_at_source() -> None:
    with pytest.raises(ValueError, match="source_id"):
        make_packet().assign_route(["sensor_001", "sink_00"])


def test_delivery_status_and_latency() -> None:
    packet = make_packet()
    packet.assign_route(["sensor_000", "sink_00"])
    packet.mark_delivered(7.5)

    assert packet.status is PacketStatus.DELIVERED
    assert packet.latency_s == pytest.approx(5.5)
    assert packet.current_hop_index == 1


def test_dropped_and_no_route_are_distinct() -> None:
    dropped = make_packet()
    dropped.mark_dropped("energy depleted")
    no_route = Packet("packet_002", "sensor_000", 2.0, 128)
    no_route.mark_dropped("no sink component", no_route=True)

    assert dropped.status is PacketStatus.DROPPED
    assert no_route.status is PacketStatus.NO_ROUTE
    assert dropped.drop_reason == "energy depleted"
    assert no_route.drop_reason == "no sink component"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"created_at": -1.0, "size_bytes": 128},
        {"created_at": 0.0, "size_bytes": 0},
    ],
)
def test_reject_invalid_creation_values(kwargs: dict[str, float | int]) -> None:
    with pytest.raises(ValueError):
        Packet("packet_bad", "sensor_000", **kwargs)


def test_reject_delivery_before_creation() -> None:
    with pytest.raises(ValueError, match="earlier"):
        make_packet().mark_delivered(1.0)
