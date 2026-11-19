from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Sequence

class PacketStatus(str, Enum):
    CREATED = 'CREATED'
    IN_TRANSIT = 'IN_TRANSIT'
    DELIVERED = 'DELIVERED'
    DROPPED = 'DROPPED'
    NO_ROUTE = 'NO_ROUTE'

@dataclass(slots=True)
class Packet:
    packet_id: str
    source_id: str
    created_at: float
    size_bytes: int
    wire_size_bytes: int | None = field(default=None, kw_only=True)
    route: list[str] = field(default_factory=list)
    actual_path: list[str] = field(default_factory=list, init=False)
    status: PacketStatus = field(default=PacketStatus.CREATED, init=False)
    delivered_at: float | None = field(default=None, init=False)
    drop_reason: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not self.packet_id or not self.source_id:
            raise ValueError('packet_id and source_id must not be empty')
        if not isfinite(self.created_at) or self.created_at < 0:
            raise ValueError('created_at must be finite and non-negative')
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError('size_bytes must be an integer')
        if self.size_bytes <= 0:
            raise ValueError('size_bytes must be greater than zero')
        if self.wire_size_bytes is None:
            self.wire_size_bytes = self.size_bytes
        if isinstance(self.wire_size_bytes, bool) or not isinstance(self.wire_size_bytes, int):
            raise TypeError('wire_size_bytes must be an integer')
        if self.wire_size_bytes < self.size_bytes:
            raise ValueError('wire_size_bytes must cover the payload')
        self.actual_path = [self.source_id]
        if self.route:
            self.assign_route(self.route)

    @property
    def is_terminal(self) -> bool:
        return self.status in {PacketStatus.DELIVERED, PacketStatus.DROPPED, PacketStatus.NO_ROUTE}

    @property
    def current_node_id(self) -> str:
        return self.actual_path[-1]

    @property
    def current_hop_index(self) -> int:
        return len(self.actual_path) - 1

    @property
    def planned_route(self) -> list[str]:
        return self.route

    @property
    def planned_hop_count(self) -> int:
        return max(0, len(self.planned_route) - 1)

    @property
    def hop_count(self) -> int:
        return self.planned_hop_count

    @property
    def actual_hop_count(self) -> int:
        return len(self.actual_path) - 1

    @property
    def latency_s(self) -> float | None:
        return None if self.delivered_at is None else self.delivered_at - self.created_at

    def assign_route(self, route: Sequence[str]) -> None:
        if self.is_terminal:
            raise ValueError('a terminal packet cannot be routed')
        nodes = list(route)
        if not nodes or nodes[0] != self.current_node_id:
            raise ValueError('route must start at current node, initially source_id')
        full_route = [*self.actual_path[:-1], *nodes]
        if len(full_route) != len(set(full_route)):
            raise ValueError('route must not revisit a node')
        self.route = full_route
        self.status = PacketStatus.IN_TRANSIT

    def advance_to(self, node_id: str) -> None:
        if self.is_terminal or self.status is not PacketStatus.IN_TRANSIT:
            raise ValueError('packet is not in transit')
        next_index = self.current_hop_index + 1
        if next_index >= len(self.route) or self.route[next_index] != node_id:
            raise ValueError('node_id must be the next planned hop')
        self.actual_path.append(node_id)

    def mark_delivered(self, delivered_at: float) -> bool:
        if not isfinite(delivered_at) or delivered_at < self.created_at:
            raise ValueError('delivered_at must not be earlier than created_at')
        if self.is_terminal:
            return False
        if not self.route or self.current_node_id != self.route[-1]:
            raise ValueError('packet has not reached its destination')
        self.delivered_at = delivered_at
        self.status = PacketStatus.DELIVERED
        return True

    def mark_dropped(self, reason: str, no_route: bool=False) -> bool:
        if not reason:
            raise ValueError('drop reason must not be empty')
        if self.is_terminal:
            return False
        self.status = PacketStatus.NO_ROUTE if no_route else PacketStatus.DROPPED
        self.drop_reason = reason
        return True
