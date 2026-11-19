from __future__ import annotations
from dataclasses import dataclass, field
from wsn_sim.models.packet import Packet

@dataclass(slots=True)
class Sink:
    node_id: str
    x: float
    y: float
    received_packet_ids: set[str] = field(default_factory=set)
    retain_packet_ids: bool = field(default=True, kw_only=True)
    received_unique_packets: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError('node_id must not be empty')

    def receive(self, packet: Packet, received_at: float) -> bool:
        if packet.packet_id in self.received_packet_ids or packet.is_terminal:
            return False
        if packet.current_node_id != self.node_id:
            raise ValueError('packet has not reached this sink')
        if not packet.mark_delivered(received_at):
            return False
        self.received_unique_packets += 1
        if self.retain_packet_ids:
            self.received_packet_ids.add(packet.packet_id)
        return True

    @property
    def received_packet_count(self) -> int:
        return len(self.received_packet_ids) if self.retain_packet_ids else self.received_unique_packets
