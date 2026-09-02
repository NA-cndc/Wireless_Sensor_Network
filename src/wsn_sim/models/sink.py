"""Sink node domain model."""

from __future__ import annotations

from dataclasses import dataclass, field

from wsn_sim.models.packet import Packet


@dataclass(slots=True)
class Sink:
    """Represent an energy-unconstrained sink that deduplicates packets by ID."""

    node_id: str
    x: float
    y: float
    received_packet_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("node_id must not be empty")

    def receive(self, packet: Packet, received_at: float) -> bool:
        """Receive and deliver a packet unless its ID was already recorded.

        Args:
            packet: Packet arriving at this sink.
            received_at: Simulation timestamp of reception.

        Returns:
            ``True`` for a newly recorded packet and ``False`` for a duplicate.
        """
        if packet.packet_id in self.received_packet_ids:
            return False
        packet.mark_delivered(received_at)
        self.received_packet_ids.add(packet.packet_id)
        return True

    @property
    def received_packet_count(self) -> int:
        """Return the number of unique packet IDs received by this sink."""
        return len(self.received_packet_ids)
