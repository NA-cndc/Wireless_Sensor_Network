"""Sensor node domain model."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Protocol


class PositionedNode(Protocol):
    """Structural type for any object with Cartesian coordinates."""

    x: float
    y: float


@dataclass(slots=True)
class Sensor:
    """Represent a stationary, energy-constrained wireless sensor node."""

    node_id: str
    x: float
    y: float
    initial_energy_j: float
    energy_j: float | None = None
    is_alive: bool = True
    generated_packets: int = 0
    received_packets: int = 0
    forwarded_packets: int = 0
    dropped_packets: int = 0

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("node_id must not be empty")
        if self.initial_energy_j <= 0:
            raise ValueError("initial_energy_j must be greater than zero")
        if self.energy_j is None:
            self.energy_j = float(self.initial_energy_j)
        if self.energy_j < 0:
            raise ValueError("energy_j must not be negative")
        self.energy_j = float(self.energy_j)
        self.is_alive = self.energy_j > 0

    def distance_to(self, other: PositionedNode) -> float:
        """Return Euclidean distance in metres to another positioned node."""
        return hypot(self.x - other.x, self.y - other.y)

    def consume_energy(self, amount_j: float) -> float:
        """Consume energy without allowing the stored value to become negative.

        Args:
            amount_j: Non-negative energy amount in joules.

        Returns:
            The sensor's remaining energy in joules.

        Raises:
            ValueError: If ``amount_j`` is negative.
        """
        if amount_j < 0:
            raise ValueError("amount_j must not be negative")
        self.energy_j = max(0.0, self.energy_j - amount_j)
        self.is_alive = self.energy_j > 0
        return self.energy_j

    def can_forward(self, threshold_j: float) -> bool:
        """Return whether this live sensor meets an energy threshold."""
        if threshold_j < 0:
            raise ValueError("threshold_j must not be negative")
        return self.is_alive and self.energy_j >= threshold_j
