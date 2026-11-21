from __future__ import annotations
from collections import Counter
from collections.abc import Iterable, Mapping
from math import ceil, isclose
import pandas as pd
from wsn_sim.config import require_integer, require_number
from wsn_sim.evaluation import security_metrics
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
__all__ = ['LifetimeTracker', 'performance_metrics', 'packet_event_metrics', 'security_metrics', 'topology_summary_frame']
METRIC_SCHEMA = 'wsn_metrics_event_ordered_v2'
TOPOLOGY_SUMMARY_COLUMNS = ['seed', 'communication_range_m', 'sensors', 'sinks', 'nodes', 'edges', 'routable_sensors', 'isolated_sensors']

def topology_summary_frame(summaries: Iterable[Mapping[str, int | float]]) -> pd.DataFrame:
    frame = pd.DataFrame(list(summaries), columns=TOPOLOGY_SUMMARY_COLUMNS)
    return frame.sort_values('communication_range_m', ignore_index=True) if not frame.empty else frame

class PacketAccumulator:

    def __init__(self, retain_completed: bool=True):
        self.retain_completed = retain_completed
        self.packets = {}
        self.decisions = set()
        self.totals = Counter()
        self.drop_reasons = Counter()
        self.reroute_reasons = Counter()
        self.decision_reasons = Counter()
        self.decision_categories = Counter()
        self.previous_time = -1

    def bulk_unreachable(self, count: int):
        if not count:
            return
        self.totals['generated'] += count
        self.totals['dropped'] += count
        self.drop_reasons['unreachable'] += count

    def consume(self, row: dict):
        time_s, packet_id, kind = (row['time_s'], row['packet_id'], row['event'])
        require_number('event_time_s', time_s, strict=False)
        if time_s < self.previous_time:
            raise ValueError('packet events must be chronological')
        self.previous_time = time_s
        if kind == 'created':
            payload, wire = (row['payload_size_bytes'], row['wire_size_bytes'])
            require_integer('payload_size_bytes', payload)
            require_integer('wire_size_bytes', wire, payload)
            if packet_id in self.packets:
                self.totals['duplicate_created'] += 1
                packet = self.packets[packet_id]
                if (packet['created_at'], packet['payload'], packet['wire']) != (time_s, payload, wire):
                    raise ValueError('conflicting packet creation')
            else:
                self.totals['generated'] += 1
                self.packets[packet_id] = {'created_at': time_s, 'payload': payload, 'wire': wire, 'terminal': None, 'received_nodes': set()}
            return
        if packet_id not in self.packets:
            raise ValueError('packet event without creation')
        packet = self.packets[packet_id]
        if kind == 'rx':
            packet['received_nodes'].add(row['node_id'])
        elif kind in {'delivered', 'dropped'}:
            if packet['terminal'] is not None:
                if packet['terminal'] != kind:
                    raise ValueError('conflicting terminal packet events')
                if kind == 'delivered':
                    self.totals['duplicate_delivery'] += 1
                return
            packet['terminal'] = kind
            self.totals[kind] += 1
            if kind == 'delivered':
                self.totals['payload_bits'] += packet['payload'] * 8
                self.totals['wire_bits'] += packet['wire'] * 8
                self.totals['hops'] += len(packet['received_nodes'])
                self.totals['latency'] += time_s - packet['created_at']
            else:
                self.drop_reasons[row.get('reason')] += 1
            if not self.retain_completed:
                self.packets.pop(packet_id)
        elif kind in {'rerouted', 'reroute_failed'}:
            key = row.get('decision_id', (kind, packet_id, time_s))
            if self.retain_completed and key in self.decisions:
                return
            if self.retain_completed:
                self.decisions.add(key)
            self.totals['decisions'] += 1
            self.decision_reasons[row['reason']] += 1
            self.decision_categories[row['reason_category']] += 1
            if kind == 'rerouted':
                self.totals['rerouted'] += 1
                self.reroute_reasons[row['reason']] += 1
                self.totals['added'] += row.get('added_edge_count', 0)
                self.totals['removed'] += row.get('removed_edge_count', 0)

    def summary(self, duration_s: float) -> dict:
        require_number('duration_s', duration_s, strict=False)
        totals = self.totals
        generated, received, lost = (totals['generated'], totals['delivered'], totals['dropped'])
        pending = generated - received - lost
        unavailable = {'queued_packets': 'queues_not_modeled'}

        def divide(name, numerator, denominator, reason):
            if not denominator:
                unavailable[name] = reason
                return None
            return numerator / denominator
        return {'metric_schema': METRIC_SCHEMA, 'generated': generated, 'delivered': received, 'received_unique_at_sink': received, 'dropped': lost, 'pending_in_flight': pending, 'queued_packets': None, 'conservation_ok': generated == received + lost + pending, 'duplicate_delivery_events': totals['duplicate_delivery'], 'duplicate_created_events': totals['duplicate_created'], 'received_payload_bits': totals['payload_bits'], 'received_wire_bits': totals['wire_bits'], 'pdr': divide('pdr', received, generated, 'no_generated_packets'), 'throughput_bps': divide('throughput_bps', totals['wire_bits'], duration_s, 'zero_duration'), 'goodput_bps': divide('goodput_bps', totals['payload_bits'], duration_s, 'zero_duration'), 'mean_actual_hops': divide('mean_actual_hops', totals['hops'], received, 'no_delivered_packets'), 'mean_latency_s': divide('mean_latency_s', totals['latency'], received, 'no_delivered_packets'), 'drop_reasons': dict(self.drop_reasons), 'reroute_count': totals['rerouted'], 'reroute_decision_count': totals['decisions'], 'reroute_failed_count': totals['decisions'] - totals['rerouted'], 'reroute_reasons': dict(self.reroute_reasons), 'reroute_decision_reasons': dict(self.decision_reasons), 'reroute_decision_categories': dict(self.decision_categories), 'route_edges_added': totals['added'], 'route_edges_removed': totals['removed'], 'route_edges_changed': totals['added'] + totals['removed'], 'na_reasons': unavailable}

def packet_event_metrics(events: list[dict], duration_s: float) -> dict:
    accumulator = PacketAccumulator()
    for row in events:
        accumulator.consume(row)
    return accumulator.summary(duration_s)

class LifetimeTracker:

    def __init__(self, network: Network, router: RoutingEngine | None=None, *, start_time_s: float=0, complete_payload_history: bool=False) -> None:
        self.network, self.router = (network, router or RoutingEngine(network))
        self.started_at = start_time_s
        self.complete_payload_history = complete_payload_history
        self.retain_history = True
        self.receipt_history = [(start_time_s, 0)]
        self.events: list[dict] = []
        self.reachability_events: list[dict] = []
        self.reachability: dict = {}
        self.metadata = {'payload_na_reasons': {}, 'death_time_na_reasons': {}, 'boundary_rule': 'cumulative_deliveries_in_event_prefix_at_death_before_later_same_time_events'}
        self.milestones = {name: {'time_s': None, 'censored': True, 'received_payload_bits': None} for name in ('FND', 'HND', 'LND', 'functional_network_death', 'functional_routing_network_death')}

    def record_received(self, time_s: float, received_payload_bits: int) -> None:
        if time_s < self.receipt_history[-1][0] or received_payload_bits < self.receipt_history[-1][1]:
            raise ValueError('received payload history must be monotonic')
        if received_payload_bits != self.receipt_history[-1][1]:
            self.receipt_history.append((time_s, received_payload_bits))
            if not self.retain_history:
                self.receipt_history = self.receipt_history[-1:]

    def _mark(self, name, time_s, payload):
        self.milestones[name] = {'time_s': time_s, 'censored': False, 'received_payload_bits': payload}
        self.events.append({'milestone': name, **self.milestones[name]})

    def observe(self, time_s: float, received_payload_bits: int) -> None:
        self.record_received(time_s, received_payload_bits)
        sensors = list(self.network.sensors.values())
        dead = [sensor for sensor in sensors if not sensor.is_alive]
        times = [sensor.died_at for sensor in dead]
        if any((value is not None and value > time_s for value in times)):
            raise ValueError('sensor death timestamp is after observation')
        for name, rank in (('FND', 1), ('HND', ceil(len(sensors) / 2)), ('LND', len(sensors))):
            if len(dead) < rank or not self.milestones[name]['censored']:
                continue
            if any((value is None for value in times)):
                self.metadata['death_time_na_reasons'][name] = 'death_timestamp_unavailable'
                continue
            death_time = sorted(times)[rank - 1]
            if death_time == time_s:
                payload = received_payload_bits
            elif death_time < self.started_at:
                payload = 0
            elif self.complete_payload_history:
                payload = next((bits for when, bits in reversed(self.receipt_history) if when <= death_time), 0)
            else:
                payload = None
                self.metadata['payload_na_reasons'][name] = 'no_exact_payload_observation_at_death'
            self._mark(name, death_time, payload)
        alive = sum((sensor.is_alive for sensor in sensors))
        physical_ids = self.network.routable_sensor_ids(alive_only=True)
        routing_ids = self.router.reachable_sensor_ids(time_s)
        state = {'status': 'alive_population' if alive else 'no_alive_sensors', 'alive_sensors': alive, 'physical_reachable_alive': len(physical_ids), 'routing_reachable_alive': len(routing_ids), 'physical_reachable_ratio': len(physical_ids) / alive if alive else None, 'routing_reachable_ratio': len(routing_ids) / alive if alive else None, 'routing_algorithm': self.network.config.routing_algorithm, 'source_policy': 'alive_origin_may_send_own_traffic_but_is_not_transit_exception'}
        if state != self.reachability:
            self.reachability = state
            self.reachability_events.append({'time_s': time_s, **state})
        for name, key in (('functional_network_death', 'physical_reachable_ratio'), ('functional_routing_network_death', 'routing_reachable_ratio')):
            if alive and state[key] < 0.5 and self.milestones[name]['censored']:
                self._mark(name, time_s, received_payload_bits)

def performance_metrics(network: Network, traffic, duration_s: float) -> dict:
    result = traffic.online_metrics.summary(duration_s) if traffic.online_metrics is not None else packet_event_metrics(traffic.events, duration_s)
    remaining = sum((sensor.energy_j for sensor in network.sensors.values()))
    initial = sum(traffic.initial_energy_at_start_j.values())
    e0 = sum((sensor.initial_energy_j for sensor in network.sensors.values()))
    spent = initial - remaining
    event_energy = traffic.recorder.energy['total'] if traffic.recorder is not None else sum((row['consumed_j'] for row in traffic.energy_events))
    radio_energy = traffic.recorder.energy['radio'] if traffic.recorder is not None else sum((row['consumed_j'] for row in traffic.energy_events if row['reason'] in {'TX', 'RX'}))
    unavailable = result['na_reasons']
    if result['received_payload_bits']:
        energy_per_bit = spent / result['received_payload_bits']
    else:
        energy_per_bit = None
        unavailable['energy_per_payload_bit_j'] = 'no_delivered_payload'
    sink_count = sum((sink.received_packet_count for sink in network.sinks.values())) if traffic.recorder is not None else len(set().union(*(sink.received_packet_ids for sink in network.sinks.values())))
    result['conservation_ok'] = result['conservation_ok'] and sink_count == result['delivered']
    transitions = Counter((row['event'] for row in traffic.detector.events if row['event'] in {'suspected', 'isolated', 'probation', 'recovered'})) if traffic.detector is not None else Counter()
    if traffic.recorder is not None:
        transitions = traffic.recorder.transitions
    result.update({'remaining_energy_j': remaining, 'consumed_energy_j': e0 - remaining, 'pre_simulation_depletion_j': e0 - initial, 'consumed_since_start_j': spent, 'energy_from_events_j': event_energy, 'radio_energy_j': radio_energy, 'energy_conservation_ok': isclose(spent, event_energy, rel_tol=1e-09, abs_tol=1e-09), 'energy_per_payload_bit_j': energy_per_bit, 'energy_per_bit_numerator': 'sensor_depletion_since_simulation_start', 'routing_overhead': {'decision_count': result['reroute_decision_count'], 'successful_decisions': result['reroute_count'], 'failed_decisions': result['reroute_failed_count'], 'changed_directed_edges': result['route_edges_changed'], 'control_packets': None, 'control_energy_j': None, 'control_time_s': None, 'measurement_status': 'control_protocol_not_modeled'}, 'security_overhead': {'logical_state_events': dict(transitions), 'control_packets': None, 'monitoring_energy_j': None, 'monitoring_time_s': None, 'measurement_status': 'ideal_observer_cost_not_modeled'}, 'control_packets': None, 'monitoring_energy_j': None, 'monitoring_time_s': None, 'unmodeled': ['MAC', 'queues', 'retransmission', 'ACK', 'overhearing', 'control_cost'], 'units': {'payload_and_wire_size': 'bytes', 'received_data': 'bits', 'throughput_and_goodput': 'bit/s', 'energy': 'J', 'energy_per_payload_bit': 'J/bit', 'time': 's'}})
    return result
