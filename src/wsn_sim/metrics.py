'''Metric calculations for reproducible WSN simulation runs.'''

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import pandas as pd

from wsn_sim.energy import RadioModel
from wsn_sim.models import PacketStatus
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.traffic import TrafficGenerator

TOPOLOGY_SUMMARY_COLUMNS = [
    'seed',
    'communication_range_m',
    'sensors',
    'sinks',
    'nodes',
    'edges',
    'routable_sensors',
    'isolated_sensors',
]

NETWORK_LIFETIME_DEFINITION = (
    'time_to_first_physical_reachability_ratio_below_0.5_'
    'among_alive_sensors_or_no_alive_sensors'
)


def topology_summary_frame(
    summaries: Iterable[Mapping[str, int | float]],
) -> pd.DataFrame:
    '''Convert per-range summaries into a consistently ordered table.'''
    frame = pd.DataFrame(list(summaries), columns=TOPOLOGY_SUMMARY_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values('communication_range_m', ignore_index=True)
    return frame


def calculate_lifetime_milestones(
    initial_sensor_count: int,
    death_events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    '''Calculate FND, HND and LND from unique physical death events.'''
    earliest_by_node: dict[str, float] = {}
    for event in death_events:
        node_id = str(event['node_id'])
        death_time = float(event['death_time_s'])
        if node_id not in earliest_by_node or death_time < earliest_by_node[node_id]:
            earliest_by_node[node_id] = death_time

    ordered_times = sorted(earliest_by_node.values())
    half_count = math.ceil(initial_sensor_count / 2)

    def milestone(position: int) -> tuple[float | None, str]:
        if position > 0 and len(ordered_times) >= position:
            return ordered_times[position - 1], 'observed'
        return None, 'not_observed'

    fnd_s, fnd_status = milestone(1)
    hnd_s, hnd_status = milestone(half_count)
    lnd_s, lnd_status = milestone(initial_sensor_count)
    return {
        'initial_sensor_count': initial_sensor_count,
        'hnd_dead_sensor_count': half_count,
        'fnd_s': fnd_s,
        'fnd_status': fnd_status,
        'hnd_s': hnd_s,
        'hnd_status': hnd_status,
        'lnd_s': lnd_s,
        'lnd_status': lnd_status,
    }


def calculate_simulation_metrics(
    network: Network,
    traffic_gen: TrafficGenerator,
    radio: RadioModel,
    sim_time_s: float,
    router: RoutingEngine | None = None,
    reachability_history: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    '''Calculate sink, lifetime, energy and packet metrics without mutation.'''
    total_sensors = len(network.sensors)
    total_sinks = len(network.sinks)
    alive_sensors = sum(1 for sensor in network.sensors.values() if sensor.is_alive)
    dead_sensors = total_sensors - alive_sensors

    packets = list(traffic_gen.generated_packets)
    delivered_by_id = {
        packet.packet_id: packet
        for packet in packets
        if packet.status is PacketStatus.DELIVERED
    }
    dropped = [
        packet
        for packet in packets
        if packet.status in (PacketStatus.DROPPED, PacketStatus.NO_ROUTE)
    ]
    pending = [
        packet
        for packet in packets
        if packet.status in (PacketStatus.CREATED, PacketStatus.IN_TRANSIT)
    ]
    delivered = list(delivered_by_id.values())

    generated_count = len(packets)
    delivered_count = len(delivered)
    dropped_count = len(dropped)
    pending_count = len(pending)

    drop_reasons: dict[str, int] = {}
    for packet in dropped:
        reason = packet.drop_reason or 'unspecified'
        drop_reasons[reason] = drop_reasons.get(reason, 0) + 1

    total_delivered_bytes = sum(packet.size_bytes for packet in delivered)
    total_delivered_payload_bytes = sum(packet.payload_size_bytes for packet in delivered)
    total_hops = sum(len(packet.path) - 1 for packet in delivered)
    total_delay_s = sum(
        packet.delivered_at - packet.created_at
        for packet in delivered
        if packet.delivered_at is not None
    )

    measurement_duration_s = float(sim_time_s)
    if measurement_duration_s > 0:
        throughput_bps = 8.0 * total_delivered_bytes / measurement_duration_s
        goodput_bps = 8.0 * total_delivered_payload_bytes / measurement_duration_s
    else:
        throughput_bps = None
        goodput_bps = None

    pdr_percent = (
        100.0 * delivered_count / generated_count if generated_count > 0 else None
    )
    average_hops = total_hops / delivered_count if delivered_count > 0 else None
    average_delay_s = total_delay_s / delivered_count if delivered_count > 0 else None

    initial_total_energy = sum(
        sensor.initial_energy_j for sensor in network.sensors.values()
    )
    residual_total_energy = sum(sensor.energy_j for sensor in network.sensors.values())
    consumed_energy = max(0.0, initial_total_energy - residual_total_energy)

    lifetime = calculate_lifetime_milestones(total_sensors, radio.death_events)
    history = list(reachability_history or [])
    functional_death_s = next(
        (
            float(item['time_s'])
            for item in history
            if item.get('alive_sensors', 0) == 0
            or (
                item.get('reachability_ratio') is not None
                and float(item['reachability_ratio']) < 0.5
            )
        ),
        None,
    )
    current_reachability = (
        dict(history[-1])
        if history
        else network.physical_reachability_snapshot(measurement_duration_s)
    )
    if router is not None and hasattr(router, 'transmission_feasibility_snapshot'):
        feasibility = router.transmission_feasibility_snapshot(
            radio,
            int(network.config.packet_size_bytes),
            measurement_duration_s,
        )
    else:
        feasibility = {
            'routing_eligible_sensors': None,
            'routing_eligible_ratio': None,
            'energy_feasible_sensors': None,
            'energy_feasible_ratio': None,
            'state': 'unavailable',
            'definition': (
                'independent_one_packet_snapshot_with_tx_rx_energy_and_'
                'routing_relay_rules_not_future_delivery_guarantee'
            ),
        }

    result = {
        'simulated_time_s': measurement_duration_s,
        'measurement_duration_s': measurement_duration_s,
        'measurement_interval': '[0, T)',
        'total_sensors': total_sensors,
        'total_sinks': total_sinks,
        'alive_sensors': alive_sensors,
        'dead_sensors': dead_sensors,
        'generated_packets': generated_count,
        'delivered_packets': delivered_count,
        'dropped_packets': dropped_count,
        'pending_packets': pending_count,
        'packet_conservation_holds': (
            generated_count == delivered_count + dropped_count + pending_count
        ),
        'drop_reasons': drop_reasons,
        'total_delivered_bytes': total_delivered_bytes,
        'total_delivered_bits': total_delivered_bytes * 8,
        'total_delivered_payload_bytes': total_delivered_payload_bytes,
        'total_delivered_payload_bits': total_delivered_payload_bytes * 8,
        'total_hops_delivered': total_hops,
        'total_end_to_end_delay_s': total_delay_s,
        'throughput_bps': throughput_bps,
        'goodput_bps': goodput_bps,
        'pdr_percent': pdr_percent,
        'average_hops': average_hops,
        'average_end_to_end_delay_s': average_delay_s,
        'initial_total_energy_j': initial_total_energy,
        'residual_total_energy_j': residual_total_energy,
        'consumed_energy_sensors_j': consumed_energy,
        'route_change_count': router.route_change_count if router else 0,
        'functional_network_death_s': functional_death_s,
        'functional_network_death_status': (
            'observed' if functional_death_s is not None else 'not_observed'
        ),
        'network_lifetime_s': functional_death_s,
        'network_lifetime_status': (
            'observed' if functional_death_s is not None else 'not_observed'
        ),
        'network_lifetime_definition': NETWORK_LIFETIME_DEFINITION,
        'current_reachable_sensors': current_reachability['reachable_sensors'],
        'current_reachability_ratio': current_reachability['reachability_ratio'],
        'current_reachability_state': current_reachability['state'],
        'current_routing_eligible_sensors': feasibility['routing_eligible_sensors'],
        'current_routing_eligible_ratio': feasibility['routing_eligible_ratio'],
        'current_energy_feasible_sensors': feasibility['energy_feasible_sensors'],
        'current_energy_feasible_ratio': feasibility['energy_feasible_ratio'],
        'current_energy_feasible_state': feasibility['state'],
        'energy_feasible_reachability_definition': feasibility['definition'],
    }
    result.update(lifetime)
    return result
