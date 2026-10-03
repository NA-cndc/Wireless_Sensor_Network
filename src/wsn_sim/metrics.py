"""Tính toán và tổng hợp các chỉ số đánh giá hiệu năng mạng WSN theo đề cương."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
import math
from typing import Any

import pandas as pd

from wsn_sim.detection import TrustDetector
from wsn_sim.energy import RadioModel
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


@dataclass(slots=True)
class SimulationMetrics:
    """Đóng gói toàn bộ các chỉ số nghiên cứu của một lần chạy mô phỏng."""

    simulated_time_s: float
    total_sensors: int
    total_sinks: int
    alive_sensors: int
    dead_sensors: int

    generated_packets: int
    delivered_packets: int
    dropped_packets: int
    pending_packets: int
    pdr_percent: float

    drops_natural_link_loss: int
    drops_selective_forwarding: int
    drops_energy_depletion: int
    drops_queue_drop: int
    drops_unreachable: int
    drops_node_dead_mid_flight: int
    drops_ttl_expired: int

    total_delivered_bytes: int
    total_delivered_bits: int
    offered_rate_bps: float
    throughput_bps: float
    goodput_bps: float

    initial_total_energy_j: float
    residual_total_energy_j: float
    consumed_energy_sensors_j: float
    energy_per_bit_j_bit: float | None

    avg_hop_count: float | None
    avg_latency_s: float | None

    jains_fairness_index: float

    t_fnd_s: float | None
    t_hnd_s: float | None
    t_lnd_s: float | None
    t_func_s: float | None
    bits_at_fnd: int | None
    bits_at_hnd: int | None
    bits_at_lnd: int | None

    route_change_count: int
    monitoring_energy_overhead_j: float

    attacker_count: int
    detection_metrics: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        """Xuất dict JSON-serializable."""
        return asdict(self)


def calculate_simulation_metrics(
    network: Network,
    traffic_gen: TrafficGenerator,
    radio: RadioModel,
    sim_time_s: float,
    router: RoutingEngine | None = None,
    detector: TrustDetector | None = None,
) -> dict[str, Any]:
    """Tính toán toàn bộ hệ thống chỉ số theo Mục 3.8 của đề cương."""
    total_sensors = len(network.sensors)
    total_sinks = len(network.sinks)
    alive_sensors = sum(1 for s in network.sensors.values() if s.is_alive)
    dead_sensors = total_sensors - alive_sensors

    gen_count = len(traffic_gen.generated_packets)
    deliv_count = len(traffic_gen.delivered_packets)
    drop_count = len(traffic_gen.dropped_packets)
    pending_count = max(0, gen_count - deliv_count - drop_count)

    pdr = (deliv_count / gen_count * 100.0) if gen_count > 0 else 0.0

    drop_reasons: dict[str, int] = {
        "natural_link_loss": 0,
        "selective_forwarding": 0,
        "energy_depletion": 0,
        "queue_drop": 0,
        "unreachable": 0,
        "node_dead_mid_flight": 0,
        "ttl_expired": 0,
    }
    for pkt in traffic_gen.dropped_packets:
        reason = pkt.drop_reason or "unreachable"
        if reason in drop_reasons:
            drop_reasons[reason] += 1
        else:
            drop_reasons[reason] = drop_reasons.get(reason, 0) + 1

    total_delivered_bytes = sum(pkt.size_bytes for pkt in traffic_gen.delivered_packets)
    total_delivered_bits = total_delivered_bytes * 8

    duration_s = max(sim_time_s, 1e-6)
    offered_rate_bps = (sum(pkt.size_bytes for pkt in traffic_gen.generated_packets) * 8) / duration_s
    throughput_bps = total_delivered_bits / duration_s
    goodput_bps = throughput_bps

    e0 = network.config.initial_energy_j
    initial_total_energy = total_sensors * e0
    residual_total_energy = sum(s.energy_j for s in network.sensors.values())
    consumed_energy = max(0.0, initial_total_energy - residual_total_energy)
    energy_per_bit = (consumed_energy / total_delivered_bits) if total_delivered_bits > 0 else None

    if deliv_count > 0:
        avg_hops = sum(pkt.hop_count for pkt in traffic_gen.delivered_packets) / deliv_count
        avg_latency = (
            sum(traffic_gen.delivered_latencies) / len(traffic_gen.delivered_latencies)
            if traffic_gen.delivered_latencies
            else 0.0
        )
    else:
        avg_hops = None
        avg_latency = None

    forward_counts = [s.forwarded_packets for s in network.sensors.values()]
    sum_f = sum(forward_counts)
    sum_f_sq = sum(f * f for f in forward_counts)
    if sum_f_sq > 0:
        jains_fairness = (sum_f ** 2) / (total_sensors * sum_f_sq)
    else:
        jains_fairness = 1.0

    t_fnd: float | None = None
    t_hnd: float | None = None
    t_lnd: float | None = None
    t_func: float | None = None

    if dead_sensors >= 1:
        t_fnd = sim_time_s if dead_sensors >= 1 else None
    if dead_sensors >= math.ceil(total_sensors / 2.0):
        t_hnd = sim_time_s
    if dead_sensors == total_sensors:
        t_lnd = sim_time_s

    routable_now = len(network.routable_sensor_ids())
    if alive_sensors > 0 and (routable_now / alive_sensors) < 0.5:
        t_func = sim_time_s

    route_changes = router.route_change_count if router is not None else 0
    det = detector or traffic_gen.detector
    monitoring_energy = det.total_monitoring_energy_j if det else 0.0

    detection_stats: dict[str, Any] | None = None
    if traffic_gen.attackers:
        all_sensors = set(network.sensors.keys())
        first_atk = traffic_gen.first_attack_time_s or 0.0
        detection_stats = det.evaluate_detection(
            actual_attackers=traffic_gen.attackers,
            total_sensor_ids=all_sensors,
            first_attack_time_s=first_atk,
        )

    metrics_obj = SimulationMetrics(
        simulated_time_s=round(sim_time_s, 2),
        total_sensors=total_sensors,
        total_sinks=total_sinks,
        alive_sensors=alive_sensors,
        dead_sensors=dead_sensors,
        generated_packets=gen_count,
        delivered_packets=deliv_count,
        dropped_packets=drop_count,
        pending_packets=pending_count,
        pdr_percent=round(pdr, 2),
        drops_natural_link_loss=drop_reasons["natural_link_loss"],
        drops_selective_forwarding=drop_reasons["selective_forwarding"],
        drops_energy_depletion=drop_reasons["energy_depletion"],
        drops_queue_drop=drop_reasons["queue_drop"],
        drops_unreachable=drop_reasons["unreachable"],
        drops_node_dead_mid_flight=drop_reasons["node_dead_mid_flight"],
        drops_ttl_expired=drop_reasons["ttl_expired"],
        total_delivered_bytes=total_delivered_bytes,
        total_delivered_bits=total_delivered_bits,
        offered_rate_bps=round(offered_rate_bps, 2),
        throughput_bps=round(throughput_bps, 2),
        goodput_bps=round(goodput_bps, 2),
        initial_total_energy_j=round(initial_total_energy, 4),
        residual_total_energy_j=round(residual_total_energy, 4),
        consumed_energy_sensors_j=round(consumed_energy, 4),
        energy_per_bit_j_bit=round(energy_per_bit, 8) if energy_per_bit is not None else None,
        avg_hop_count=round(avg_hops, 2) if avg_hops is not None else None,
        avg_latency_s=round(avg_latency, 4) if avg_latency is not None else None,
        jains_fairness_index=round(jains_fairness, 4),
        t_fnd_s=t_fnd,
        t_hnd_s=t_hnd,
        t_lnd_s=t_lnd,
        t_func_s=t_func,
        bits_at_fnd=total_delivered_bits if t_fnd is not None else None,
        bits_at_hnd=total_delivered_bits if t_hnd is not None else None,
        bits_at_lnd=total_delivered_bits if t_lnd is not None else None,
        route_change_count=route_changes,
        monitoring_energy_overhead_j=round(monitoring_energy, 6),
        attacker_count=len(traffic_gen.attackers),
        detection_metrics=detection_stats,
    )
    return metrics_obj.to_dict()
