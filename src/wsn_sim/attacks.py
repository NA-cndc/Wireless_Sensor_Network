from __future__ import annotations
from collections.abc import Iterable
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from random import Random
from typing import TYPE_CHECKING
from wsn_sim.config import SimulationConfig, require_integer
from wsn_sim.randomness import event_occurs
if TYPE_CHECKING:
    from wsn_sim.network import Network

class SelectiveForwarding:

    def __init__(self, config: SimulationConfig, sensor_ids: Iterable[str], *, network: Network | None=None) -> None:
        if isinstance(sensor_ids, str):
            raise TypeError('sensor_ids must be a collection of sensor IDs')
        sensors = sorted(sensor_ids)
        if any((not isinstance(node, str) or not node for node in sensors)):
            raise TypeError('sensor_ids must contain non-empty strings')
        if len(set(sensors)) != len(sensors):
            raise ValueError('sensor_ids must be unique')
        if network is not None and set(sensors) != set(network.sensors):
            raise ValueError('attacker candidates must be exactly the network sensor IDs')
        count = int((Decimal(str(config.attacker_ratio)) * len(sensors)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        distances = None
        if network is not None and network.sinks:
            distances = {node: min((network.distance(node, sink) for sink in sorted(network.sinks))) for node in sensors}
            if any((not isfinite(value) for value in distances.values())):
                raise ValueError('attacker positions must have finite distances to sinks')
        self.selection = 'explicit' if config.attacker_ids is not None else config.attacker_selection
        if self.selection == 'explicit':
            selected = config.attacker_ids
            if not set(selected).issubset(sensors):
                raise ValueError('attackers must be sensor IDs from this network')
        elif self.selection == 'near_sink':
            if distances is None:
                raise ValueError('near_sink selection requires network sensor and sink positions')
            selected = sorted(sensors, key=lambda node: (distances[node], node))[:count]
        else:
            selected = Random(config.stream_seeds['attacker_selection']).sample(sensors, count)
        self.attacker_ids = frozenset(selected)
        self.config = config
        self.requested_count_from_ratio = count
        self.decision_seed = config.stream_seeds['attack_decision']
        self.actual_ratio = len(self.attacker_ids) / len(sensors) if sensors else 0.0
        self.nearest_sink_distances_m = None if distances is None else {node: distances[node] for node in sorted(self.attacker_ids)}

    def drops(self, relay_id: str, packet_id: str, source_id: str, *, attempt_index: int=0) -> bool:
        require_integer('attempt_index', attempt_index, 0)
        return relay_id != source_id and relay_id in self.attacker_ids and event_occurs(self.decision_seed, self.config.p_drop, packet_id, relay_id, attempt_index)

    def to_dict(self) -> dict:
        return {'attacker_ids': sorted(self.attacker_ids), 'attacker_count': len(self.attacker_ids), 'requested_count_from_ratio': self.requested_count_from_ratio, 'requested_ratio': self.config.attacker_ratio, 'actual_ratio': self.actual_ratio, 'requested_selection': self.config.attacker_selection, 'selection': self.selection, 'selection_rule': {'explicit': 'explicit_sensor_ids_override_ratio_and_selection', 'random': 'uniform_sample_without_replacement_from_sorted_sensor_ids', 'near_sink': 'minimum_euclidean_distance_to_any_sink_then_sensor_id'}[self.selection], 'rounding': 'half_up', 'nearest_sink_distances_m': self.nearest_sink_distances_m}
