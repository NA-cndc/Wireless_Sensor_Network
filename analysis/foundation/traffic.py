"""Mô-đun sinh lưu lượng (Traffic Generator) cho WSN bằng SimPy."""

import simpy
import math
import random
from wsn_sim.config import SimulationConfig
from .network import Network
from .routing import RoutingEngine
from .energy import RadioModel
from wsn_sim.models.packet import Packet

class TrafficGenerator:
    def __init__(self, env: simpy.Environment, network: Network, router: RoutingEngine, radio: RadioModel, config: SimulationConfig, routing_algo: str = "EMHR") -> None:
        self.env = env
        self.network = network
        self.router = router
        self.radio = radio
        self.config = config
        self.routing_algo = routing_algo

        self.generated_packets = []
        self.delivered_packets = []
        self.dropped_packets = []
        self.delivered_latencies = []

        # [MỚI] Khởi tạo hàng đợi phần cứng (Radio TX Queue) cho mỗi sensor
        # Giới hạn capacity=1 nghĩa là anten chỉ có thể phát 1 gói tin tại 1 thời điểm
        self.tx_queues = {
            node_id: simpy.Resource(env, capacity=1)
            for node_id in self.network.sensors.keys()
        }

    def start(self) -> None:
        routable_sensors = self.network.routable_sensor_ids()
        for sensor_id in routable_sensors:
            self.env.process(self._sensor_loop(sensor_id))
            self.env.process(self._beacon_loop(sensor_id))

    def _beacon_loop(self, sensor_id: str):
        beacon_size_bytes = 24
        beacon_interval_s = 50.0
        sensor_obj = self.network.sensors[sensor_id]

        yield self.env.timeout(random.uniform(0.1, beacon_interval_s))

        while True:
            if not sensor_obj.is_alive:
                break

            radius = self.network.communication_range_m
            tx_energy = self.radio.compute_tx_energy(beacon_size_bytes * 8, radius)
            sensor_obj.consume_energy(tx_energy)

            if sensor_obj.is_alive:
                neighbors = self.network.neighbors(sensor_id)
                rx_energy = self.radio.compute_rx_energy(beacon_size_bytes * 8)

                for neighbor_id in neighbors:
                    if neighbor_id in self.network.sensors:
                        neighbor_obj = self.network.sensors[neighbor_id]
                        if neighbor_obj.is_alive:
                            neighbor_obj.consume_energy(rx_energy)

            yield self.env.timeout(beacon_interval_s)

    def _sensor_loop(self, sensor_id: str):
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
                size_bytes=self.config.packet_size_bytes
            )
            self.generated_packets.append(packet)

            # Gọi bộ điều phối định tuyến hỗ trợ cả 5 thuật toán
            route = self.router.get_route(sensor_id, self.routing_algo)

            if route:
                packet.assign_route(route)
                self.env.process(self._transmit_packet(packet, route))
            else:
                packet.mark_dropped("NO_ROUTE", no_route=True)
                self.dropped_packets.append(packet)

    def _transmit_packet(self, packet: Packet, route: list[str]):
        bandwidth_bps = 250000.0
        transmission_delay_s = (packet.size_bytes * 8) / bandwidth_bps
        is_dropped = False

        for i in range(len(route) - 1):
            sender_id = route[i]
            receiver_id = route[i+1]

            # [MỚI] 1. Mô phỏng hàng đợi (CSMA/CA cơ bản)
            # Xin cấp phát anten phát của node hiện tại
            tx_queue = self.tx_queues[sender_id]
            with tx_queue.request() as req:
                yield req # Bị block tại đây nếu anten đang bận phát gói khác

                # Bắt đầu phát sóng, tốn một khoảng thời gian truyền
                yield self.env.timeout(transmission_delay_s)

                sender = self.network.sensors[sender_id]
                receiver = self.network.sensors.get(receiver_id) or self.network.sinks.get(receiver_id)

                # [MỚI] 2. Mô phỏng rớt gói do nhiễu sóng hoặc đụng độ (5% mỗi hop)
                if random.random() < 0.05:
                    packet.mark_dropped("ENVIRONMENTAL_INTERFERENCE")
                    self.dropped_packets.append(packet)
                    is_dropped = True
                    break

                if (hasattr(sender, 'is_alive') and not sender.is_alive) or \
                   (hasattr(receiver, 'is_alive') and not receiver.is_alive):
                    packet.mark_dropped("NODE_DEAD_MID_FLIGHT")
                    self.dropped_packets.append(packet)
                    is_dropped = True
                    break

                dist_m = math.hypot(sender.x - receiver.x, sender.y - receiver.y)
                self.radio.process_transmission(sender, receiver, packet.size_bytes, dist_m)

            # Thoát khỏi khối 'with': Giải phóng anten cho gói tiếp theo trong hàng đợi

            # Dừng vòng lặp nếu gói tin đã bị rớt
            if is_dropped:
                break

        if not is_dropped:
            actual_latency = float(self.env.now) - packet.created_at
            self.delivered_latencies.append(actual_latency)
            self.delivered_packets.append(packet)
