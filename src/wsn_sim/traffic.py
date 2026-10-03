"""Mô-đun sinh lưu lượng (Traffic Generator) cho WSN bằng SimPy với mô hình Radio Energy."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import simpy

from wsn_sim.config import SimulationConfig
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
        traffic_seed: int | None = None,
        queue_capacity: int = 50,
        bandwidth_bps: float = 250000.0,
    ) -> None:
        self.env = env
        self.network = network
        self.router = router
        self.radio = radio
        self.config = config

        self.queue_capacity = int(queue_capacity)
        self.bandwidth_bps = float(bandwidth_bps)

        self.generated_packets: list[Packet] = []
        self.delivered_packets: list[Packet] = []
        self.dropped_packets: list[Packet] = []
        self.delivered_latencies: list[float] = []

        self.queues: dict[str, list[Packet]] = {s_id: [] for s_id in self.network.sensors}

        base_seed = config.seed
        self.traffic_rng = np.random.default_rng(base_seed if traffic_seed is None else traffic_seed)

    def start(self) -> None:
        """Khởi động luồng sinh gói cho TẤT CẢ các sensor còn sống."""
        for sensor_id in sorted(self.network.sensors.keys()):
            self.env.process(self._sensor_loop(sensor_id))

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

            route = self.router.get_route(sensor_id)

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

            if isinstance(receiver, Sink):
                is_new = receiver.receive(packet, float(self.env.now))
                if is_new:
                    self.delivered_packets.append(packet)
                    if packet.latency_s is not None:
                        self.delivered_latencies.append(packet.latency_s)
                return

            if isinstance(receiver, Sensor):
                receiver.received_packets += 1

                remaining_route = current_route[i + 1 :]
                route_is_valid = self.router.is_route_valid(
                    remaining_route,
                    algorithm=self.router.algorithm,
                )

                if not route_is_valid:
                    new_sub_route = self.router.get_route(receiver_id)
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