"""Packet state and lifecycle model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class PacketStatus(str, Enum):
    """Supported lifecycle states for a packet."""

    CREATED = "CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    DROPPED = "DROPPED"
    NO_ROUTE = "NO_ROUTE"


@dataclass(slots=True)
class Packet:
    """Represent a packet and the minimal state needed to track its lifecycle."""

    packet_id: str
    source_id: str
    created_at: float
    size_bytes: int
    sequence_number: int = 0
    sink_id: str | None = None
    route: list[str] = field(default_factory=list)
    current_hop_index: int = 0
    status: PacketStatus = PacketStatus.CREATED
    delivered_at: float | None = None
    drop_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.packet_id:
            raise ValueError("packet_id must not be empty")
        if not self.source_id:
            raise ValueError("source_id must not be empty")
        if self.created_at < 0:
            raise ValueError("created_at must not be negative")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError("size_bytes must be an integer")
        if self.size_bytes <= 0:
            raise ValueError("size_bytes must be greater than zero")
        if self.sequence_number < 0:
            raise ValueError("sequence_number must not be negative")
        if self.route:
            route = list(self.route)
            self.route = []
            self.assign_route(route)
        if self.delivered_at is not None:
            self.mark_delivered(self.delivered_at)

    def assign_route(self, route: Sequence[str]) -> None:
        """Assign a non-empty route whose first node is the packet source.

        A valid assignment moves the packet from ``CREATED`` to ``IN_TRANSIT``.
        """
        route_nodes = list(route)
        if not route_nodes:
            raise ValueError("route must not be empty")
        if route_nodes[0] != self.source_id:
            raise ValueError("route must start at source_id")
        self.route = route_nodes
        self.current_hop_index = 0
        self.status = PacketStatus.IN_TRANSIT
        self.delivered_at = None
        self.drop_reason = None

    @property
    def hop_count(self) -> int:
        """Return the number of edges in the assigned route."""
        return max(0, len(self.route) - 1)

    @property
    def latency_s(self) -> float | None:
        """Return end-to-end latency when delivered, otherwise ``None``."""
        if self.delivered_at is None:
            return None
        return self.delivered_at - self.created_at

    def mark_delivered(self, delivered_at: float) -> None:
        """Mark delivery at a timestamp no earlier than packet creation."""
        if delivered_at < self.created_at:
            raise ValueError("delivered_at must not be earlier than created_at")
        self.delivered_at = delivered_at
        self.status = PacketStatus.DELIVERED
        self.drop_reason = None
        if self.route:
            self.current_hop_index = len(self.route) - 1

    def mark_dropped(self, reason: str, no_route: bool = False) -> None:
        """Mark the packet as dropped or explicitly lacking a route."""
        if not reason:
            raise ValueError("drop reason must not be empty")
        self.status = PacketStatus.NO_ROUTE if no_route else PacketStatus.DROPPED
        self.drop_reason = reason
        self.delivered_at = None
