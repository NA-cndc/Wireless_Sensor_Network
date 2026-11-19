from __future__ import annotations
from dataclasses import dataclass, field
from math import hypot, isfinite
from typing import Callable, Protocol

class PositionedNode(Protocol):
    x: float
    y: float

@dataclass(slots=True)
class Sensor:
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
    died_at: float | None = None
    energy_observer: Callable[[dict], None] | None = field(default=None, init=False, repr=False, compare=False)
    energy_clock: Callable[[], float] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError('node_id must not be empty')
        if not isfinite(self.initial_energy_j) or self.initial_energy_j <= 0:
            raise ValueError('initial_energy_j must be greater than zero')
        if self.energy_j is None:
            self.energy_j = float(self.initial_energy_j)
        if not isfinite(self.energy_j) or not 0 <= self.energy_j <= self.initial_energy_j:
            raise ValueError('energy_j must not be negative')
        self.energy_j = float(self.energy_j)
        self.is_alive = self.energy_j > 0
        if not self.is_alive and self.died_at is None:
            self.died_at = 0.0

    def distance_to(self, other: PositionedNode) -> float:
        return hypot(self.x - other.x, self.y - other.y)

    def consume_energy(self, amount_j: float, time_s: float | None=None, *, reason: str='external', packet_id: str | None=None) -> float:
        if not isfinite(amount_j) or amount_j < 0:
            raise ValueError('amount_j must not be negative')
        if time_s is not None and (not isfinite(time_s) or time_s < 0):
            raise ValueError('time_s must be finite and non-negative')
        if self.energy_clock is not None:
            current_time = float(self.energy_clock())
            if time_s is not None and time_s != current_time:
                raise ValueError('energy changes must use the current simulation time')
            time_s = current_time
        before, was_alive = (self.energy_j, self.is_alive)
        self.energy_j = max(0.0, before - amount_j)
        self.is_alive = self.energy_j > 0
        died = was_alive and (not self.is_alive)
        if died:
            self.died_at = time_s
        if self.energy_observer is not None and self.energy_j != before:
            self.energy_observer({'time_s': time_s, 'node_id': self.node_id, 'reason': reason, 'packet_id': packet_id, 'before_j': before, 'after_j': self.energy_j, 'requested_j': amount_j, 'consumed_j': before - self.energy_j, 'became_dead': died})
        return self.energy_j

    def can_forward(self, threshold_j: float) -> bool:
        if threshold_j < 0:
            raise ValueError('threshold_j must not be negative')
        return self.is_alive and self.energy_j >= threshold_j
