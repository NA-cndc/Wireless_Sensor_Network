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
        self.tx_events: dict[str, simpy.Event] = {}

        base_seed = config.seed
        self.traffic_rng = np.random.default_rng(base_seed if traffic_seed is None else traffic_seed)

    def start(self) -> None:
        """Khởi động luồng sinh gói và tiến trình truyền cho TẤT CẢ các sensor còn sống."""
        for sensor_id in sorted(self.network.sensors.keys()):
            self.tx_events[sensor_id] = self.env.event()
            self.env.process(self._sensor_loop(sensor_id))
            self.env.process(self._sensor_tx_loop(sensor_id))

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

            route = self.router.get_route(sensor_id, is_source=True)

            if route:
                packet.assign_route(route)
                queue.append(packet)
                if not self.tx_events[sensor_id].triggered:
                    self.tx_events[sensor_id].succeed()
            else:
                packet.mark_dropped("unreachable", node_id=sensor_id, no_route=True)
                self.dropped_packets.append(packet)
                sensor_obj.dropped_packets += 1

    def _sensor_tx_loop(self, sensor_id: str):
        """Tiến trình FIFO phục vụ phát gói tin tuần tự độc quyền cho từng sensor node."""
        sensor = self.network.sensors[sensor_id]
        transmission_delay_s = (self.config.packet_size_bytes * 8) / self.bandwidth_bps

        while sensor.is_alive:
            if not self.queues[sensor_id]:
                self.tx_events[sensor_id] = self.env.event()
                yield self.tx_events[sensor_id]
                if not sensor.is_alive:
                    break

            if not self.queues[sensor_id]:
                continue

            packet = self.queues[sensor_id].pop(0)

            is_source = (sensor_id == packet.source_id)
            if not is_source and self.router.algorithm == "EMHR":
                if not sensor.can_forward(self.router.threshold_j):
                    packet.mark_dropped("relay_below_threshold", node_id=sensor_id)
                    self.dropped_packets.append(packet)
                    sensor.dropped_packets += 1
                    continue

            avoid_nodes = set(packet.path) - {sensor_id}

            try:
                curr_idx = len(packet.path) - 1
                if curr_idx < len(packet.route) and packet.route[curr_idx] == sensor_id:
                    remaining_route = packet.route[curr_idx:]
                else:
                    remaining_route = packet.route[packet.route.index(sensor_id):]
            except (ValueError, IndexError):
                remaining_route = []

            route_valid = bool(
                remaining_route
                and len(remaining_route) >= 2
                and self.router.is_route_valid(
                    remaining_route,
                    algorithm=self.router.algorithm,
                    is_source=is_source,
                    avoid_nodes=avoid_nodes,
                )
            )

            if not route_valid:
                new_sub_route = self.router.get_route(
                    sensor_id,
                    algorithm=self.router.algorithm,
                    avoid_nodes=avoid_nodes,
                    is_source=is_source,
                )
                if new_sub_route:
                    self.router.route_change_count += 1
                    packet.route = list(packet.path[:-1]) + new_sub_route
                    packet.sink_id = new_sub_route[-1]
                    packet.current_hop_index = len(packet.path) - 1
                    remaining_route = new_sub_route
                else:
                    packet.mark_dropped("unreachable", node_id=sensor_id, no_route=True)
                    self.dropped_packets.append(packet)
                    sensor.dropped_packets += 1
                    continue

            next_hop_id = remaining_route[1]
            receiver = self.network.sensors.get(next_hop_id) or self.network.sinks.get(next_hop_id)
            if receiver is None:
                packet.mark_dropped("unreachable", node_id=sensor_id, no_route=True)
                self.dropped_packets.append(packet)
                sensor.dropped_packets += 1
                continue

            yield self.env.timeout(transmission_delay_s)

            if not sensor.is_alive:
                packet.mark_dropped("node_dead_mid_flight", node_id=sensor_id)
                self.dropped_packets.append(packet)
                sensor.dropped_packets += 1
                continue

            dist_m = math.hypot(sensor.x - receiver.x, sensor.y - receiver.y)

            ledger_entry = self.radio.attempt_transmission(
                sender=sensor,
                receiver=receiver,
                packet_size_bytes=packet.size_bytes,
                distance_m=dist_m,
                sim_time_s=float(self.env.now),
                packet_id=packet.packet_id,
            )

            if not ledger_entry["success"]:
                fail_node = sensor_id if ledger_entry["reason"] == "TX_INSUFFICIENT_ENERGY" else next_hop_id
                packet.mark_dropped("energy_depletion", node_id=fail_node)
                self.dropped_packets.append(packet)
                sensor.dropped_packets += 1
                continue

            packet.record_hop(next_hop_id)
            if not is_source:
                sensor.forwarded_packets += 1

            if isinstance(receiver, Sink):
                is_new = receiver.receive(packet, float(self.env.now))
                if is_new:
                    self.delivered_packets.append(packet)
                    if packet.latency_s is not None:
                        self.delivered_latencies.append(packet.latency_s)
                continue

            if isinstance(receiver, Sensor):
                receiver.received_packets += 1
                if not receiver.is_alive:
                    packet.mark_dropped("energy_depletion", node_id=receiver.node_id)
                    self.dropped_packets.append(packet)
                    receiver.dropped_packets += 1
                    if receiver.node_id in self.tx_events and not self.tx_events[receiver.node_id].triggered:
                        self.tx_events[receiver.node_id].succeed()
                    continue

                queue = self.queues[receiver.node_id]
                if len(queue) >= self.queue_capacity:
                    packet.mark_dropped("queue_drop", node_id=receiver.node_id)
                    self.dropped_packets.append(packet)
                    receiver.dropped_packets += 1
                else:
                    queue.append(packet)
                    if not self.tx_events[receiver.node_id].triggered:
                        self.tx_events[receiver.node_id].succeed()

        while self.queues[sensor_id]:
            pkt = self.queues[sensor_id].pop(0)
            pkt.mark_dropped("energy_depletion", node_id=sensor_id)
            self.dropped_packets.append(pkt)
            sensor.dropped_packets += 1