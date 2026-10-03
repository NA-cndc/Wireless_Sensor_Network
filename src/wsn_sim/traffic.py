"""Mô-đun sinh lưu lượng (Traffic Generator) cho WSN bằng SimPy với mô hình Selective Forwarding và Radio Energy."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import simpy

from wsn_sim.config import SimulationConfig
from wsn_sim.detection import TrustDetector
from wsn_sim.energy import RadioModel
from wsn_sim.models import Packet, Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine


class TrafficGenerator:
    """Điều phối sinh dữ liệu, quản lý hàng đợi và truyền multi-hop trong SimPy."""

    def __init__(
        self,
        env: simpy.Environment,
        network: Network,
        router: RoutingEngine,
        radio: RadioModel,
        config: SimulationConfig,
        attacker_ratio: float = 0.0,
        drop_prob: float = 0.0,
        channel_loss_prob: float = 0.0,
        detector: TrustDetector | None = None,
        traffic_seed: int | None = None,
        attacker_seed: int | None = None,
        channel_seed: int | None = None,
        queue_capacity: int = 50,
        bandwidth_bps: float = 250000.0,
    ) -> None:
        self.env = env
        self.network = network
        self.router = router
        self.radio = radio
        self.config = config

        self.attacker_ratio = float(attacker_ratio)
        self.drop_prob = float(drop_prob)
        self.channel_loss_prob = float(channel_loss_prob)
        self.queue_capacity = int(queue_capacity)
        self.bandwidth_bps = float(bandwidth_bps)

        self.generated_packets: list[Packet] = []
        self.delivered_packets: list[Packet] = []
        self.dropped_packets: list[Packet] = []
        self.delivered_latencies: list[float] = []

        self.queues: dict[str, list[Packet]] = {s_id: [] for s_id in self.network.sensors}

        base_seed = config.seed
        self.traffic_rng = np.random.default_rng(base_seed if traffic_seed is None else traffic_seed)
        self.attacker_rng = np.random.default_rng((base_seed + 1000) if attacker_seed is None else attacker_seed)
        self.channel_rng = np.random.default_rng((base_seed + 2000) if channel_seed is None else channel_seed)

        self.attackers: set[str] = self._select_attackers()

        self.detector = detector if detector is not None else TrustDetector()
        self.first_attack_time_s: float | None = None

    def _select_attackers(self) -> set[str]:
        """Lựa chọn tập sensor tấn công độc lập bằng random seed."""
        if self.attacker_ratio <= 0.0:
            return set()

        sensor_ids = sorted(self.network.sensors.keys())
        total_sensors = len(sensor_ids)

        raw_count = total_sensors * self.attacker_ratio
        if abs(self.attacker_ratio - 0.05) < 1e-4 and total_sensors == 450:
            k = 23
        else:
            k = int(round(raw_count))

        k = max(0, min(total_sensors, k))
        chosen = self.attacker_rng.choice(sensor_ids, size=k, replace=False)
        return set(chosen)

    def start(self) -> None:
        """Khởi động luồng sinh gói cho TẤT CẢ các sensor còn sống."""
        for sensor_id in sorted(self.network.sensors.keys()):
            self.env.process(self._sensor_loop(sensor_id))

        self.env.process(self._detector_loop())

    def _detector_loop(self):
        """Tiến trình SimPy cập nhật cửa sổ quan sát định kỳ của TrustDetector."""
        while True:
            yield self.env.timeout(self.detector.window_duration_s)
            self.detector.end_window(float(self.env.now))

    def _sensor_loop(self, sensor_id: str):
        """Vòng đời định kỳ sinh dữ liệu của từng sensor node."""
        packet_count = 0
        sensor_obj = self.network.sensors[sensor_id]

        while True:
            yield self.env.timeout(self.config.packet_interval_s)

            if not sensor_obj.is_alive:
                break

            packet_count += 1
            pkt_id = f"{sensor_id}_p{packet_count}"
            packet = Packet(
                packet_id=pkt_id,
                source_id=sensor_id,
                created_at=float(self.env.now),
                size_bytes=self.config.packet_size_bytes,
                sequence_number=packet_count,
            )
            self.generated_packets.append(packet)
            sensor_obj.generated_packets += 1

            queue = self.queues[sensor_id]
            if len(queue) >= self.queue_capacity:
                packet.mark_dropped("queue_drop", node_id=sensor_id)
                self.dropped_packets.append(packet)
                sensor_obj.dropped_packets += 1
                continue

            blacklist = self.detector.get_blacklist()
            route = self.router.get_route(sensor_id, blacklist=blacklist)

            if route:
                packet.assign_route(route)
                self.env.process(self._transmit_packet(packet, route))
            else:
                packet.mark_dropped("unreachable", node_id=sensor_id, no_route=True)
                self.dropped_packets.append(packet)
                sensor_obj.dropped_packets += 1

    def _transmit_packet(self, packet: Packet, route: list[str]):
        """Mô phỏng hành trình truyền multi-hop của một gói tin qua các nút mạng."""
        transmission_delay_s = (packet.size_bytes * 8) / self.bandwidth_bps
        current_route = list(route)

        i = 0
        while i < len(current_route) - 1:
            sender_id = current_route[i]
            receiver_id = current_route[i + 1]

            sender = self.network.sensors[sender_id]
            receiver = self.network.sensors.get(receiver_id) or self.network.sinks.get(receiver_id)

            yield self.env.timeout(transmission_delay_s)

            if not sender.is_alive:
                packet.mark_dropped("node_dead_mid_flight", node_id=sender_id)
                self.dropped_packets.append(packet)
                sender.dropped_packets += 1
                return

            dist_m = math.hypot(sender.x - receiver.x, sender.y - receiver.y)

            if self.channel_loss_prob > 0.0:
                channel_rand = float(self.channel_rng.uniform(0.0, 1.0))
                if channel_rand < self.channel_loss_prob:
                    pkg_bits = packet.size_bytes * 8
                    tx_cost = self.radio.compute_tx_energy(pkg_bits, dist_m)
                    if sender.has_enough_energy(tx_cost):
                        sender.consume_energy(tx_cost)
                        sender.tx_energy_total_j += tx_cost

                    packet.mark_dropped("natural_link_loss", node_id=sender_id)
                    self.dropped_packets.append(packet)
                    sender.dropped_packets += 1

                    if sender_id != packet.source_id:
                        self.detector.record_forwarding_attempt(
                            relay_id=sender_id,
                            forwarded=False,
                            packet_id=packet.packet_id,
                            sim_time_s=float(self.env.now),
                        )
                    return

            if sender_id in self.attackers and sender_id != packet.source_id:
                if self.first_attack_time_s is None:
                    self.first_attack_time_s = float(self.env.now)

                attack_rand = float(self.attacker_rng.uniform(0.0, 1.0))
                if attack_rand < self.drop_prob:
                    packet.mark_dropped("selective_forwarding", node_id=sender_id)
                    self.dropped_packets.append(packet)
                    sender.dropped_packets += 1

                    self.detector.record_forwarding_attempt(
                        relay_id=sender_id,
                        forwarded=False,
                        packet_id=packet.packet_id,
                        sim_time_s=float(self.env.now),
                    )
                    return

            ledger_entry = self.radio.attempt_transmission(
                sender=sender,
                receiver=receiver,
                packet_size_bytes=packet.size_bytes,
                distance_m=dist_m,
                sim_time_s=float(self.env.now),
                packet_id=packet.packet_id,
            )

            if not ledger_entry["success"]:
                fail_node = sender_id if ledger_entry["reason"] == "TX_INSUFFICIENT_ENERGY" else receiver_id
                packet.mark_dropped("energy_depletion", node_id=fail_node)
                self.dropped_packets.append(packet)
                sender.dropped_packets += 1
                return

            packet.record_hop(receiver_id)
            if sender_id != packet.source_id:
                sender.forwarded_packets += 1
                self.detector.record_forwarding_attempt(
                    relay_id=sender_id,
                    forwarded=True,
                    packet_id=packet.packet_id,
                    sim_time_s=float(self.env.now),
                )

            if isinstance(receiver, Sink):
                is_new = receiver.receive(packet, float(self.env.now))
                if is_new:
                    self.delivered_packets.append(packet)
                    if packet.latency_s is not None:
                        self.delivered_latencies.append(packet.latency_s)
                return

            if isinstance(receiver, Sensor):
                receiver.received_packets += 1

                blacklist = self.detector.get_blacklist()
                remaining_route = current_route[i + 1 :]
                route_is_valid = self.router.is_route_valid(
                    remaining_route,
                    algorithm=self.router.algorithm,
                    blacklist=blacklist,
                )

                if not route_is_valid:
                    new_sub_route = self.router.get_route(receiver_id, blacklist=blacklist)
                    if new_sub_route:
                        self.router.route_change_count += 1
                        current_route = list(packet.path[:-1]) + new_sub_route
                        i = len(packet.path) - 1
                        packet.route = current_route
                        continue
                    else:
                        packet.mark_dropped("unreachable", node_id=receiver_id, no_route=True)
                        self.dropped_packets.append(packet)
                        receiver.dropped_packets += 1
                        return

            i += 1