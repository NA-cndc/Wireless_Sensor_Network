"""Tổng hợp số liệu thống kê cơ bản cho mô phỏng WSN multi-hop."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from wsn_sim.energy import RadioModel
from wsn_sim.models import PacketStatus
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.traffic import TrafficGenerator

TOPOLOGY_SUMMARY_COLUMNS = [
    "seed",
    "communication_range_m",
    "sensors",
    "sinks",
    "nodes",
    "edges",
    "routable_sensors",
    "isolated_sensors",
]


def topology_summary_frame(
    summaries: Iterable[Mapping[str, int | float]],
) -> pd.DataFrame:
    """Convert per-range summary mappings into a consistently ordered table."""
    frame = pd.DataFrame(list(summaries), columns=TOPOLOGY_SUMMARY_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values("communication_range_m", ignore_index=True)
    return frame


def calculate_simulation_metrics(
    network: Network,
    traffic_gen: TrafficGenerator,
    radio: RadioModel,
    sim_time_s: float,
    router: RoutingEngine | None = None,
) -> dict[str, Any]:
    """Tính toán các chỉ số cơ bản của đợt chạy mô phỏng multi-hop."""
    total_sensors = len(network.sensors)
    total_sinks = len(network.sinks)
    alive_sensors = sum(1 for s in network.sensors.values() if s.is_alive)
    dead_sensors = total_sensors - alive_sensors

    gen_count = len(traffic_gen.generated_packets)
    deliv_count = len(traffic_gen.delivered_packets)
    drop_count = len(traffic_gen.dropped_packets)
    pending_packets = [
        p for p in traffic_gen.generated_packets
        if p.status in (PacketStatus.CREATED, PacketStatus.IN_TRANSIT)
    ]
    pending_count = len(pending_packets)

    drop_reasons: dict[str, int] = {
        "energy_depletion": 0,
        "queue_drop": 0,
        "unreachable": 0,
        "node_dead_mid_flight": 0,
        "relay_below_threshold": 0,
    }
    for pkt in traffic_gen.dropped_packets:
        reason = pkt.drop_reason or "unreachable"
        if reason in drop_reasons:
            drop_reasons[reason] += 1
        else:
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1

    total_delivered_bytes = sum(pkt.size_bytes for pkt in traffic_gen.delivered_packets)
    total_delivered_bits = total_delivered_bytes * 8

    e0 = network.config.initial_energy_j
    initial_total_energy = total_sensors * e0
    residual_total_energy = sum(s.energy_j for s in network.sensors.values())
    consumed_energy = max(0.0, initial_total_energy - residual_total_energy)

    route_change_count = router.route_change_count if router else 0

    return {
        "simulated_time_s": round(sim_time_s, 2),
        "total_sensors": total_sensors,
        "total_sinks": total_sinks,
        "alive_sensors": alive_sensors,
        "dead_sensors": dead_sensors,
        "generated_packets": gen_count,
        "delivered_packets": deliv_count,
        "dropped_packets": drop_count,
        "pending_packets": pending_count,
        "drop_reasons": drop_reasons,
        "total_delivered_bytes": total_delivered_bytes,
        "total_delivered_bits": total_delivered_bits,
        "initial_total_energy_j": round(initial_total_energy, 4),
        "residual_total_energy_j": round(residual_total_energy, 4),
        "consumed_energy_sensors_j": round(consumed_energy, 4),
        "route_change_count": route_change_count,
    }
