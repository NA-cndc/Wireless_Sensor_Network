"""Mô-đun sinh lưu lượng (Traffic Generator) cho WSN bằng SimPy."""

import simpy
import math
from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.energy import RadioModel
from wsn_sim.models.packet import Packet

class TrafficGenerator:
    def __init__(self, env: simpy.Environment, network: Network, router: RoutingEngine, radio: RadioModel, config: SimulationConfig) -> None:
        self.env = env
        self.network = network
        self.router = router
        self.radio = radio
        self.config = config
        
        # 3 Danh sách hứng dữ liệu quan trọng
        self.generated_packets: list[Packet] = []
        self.delivered_packets: list[Packet] = []
        self.dropped_packets: list[Packet] = []
        self.delivered_latencies: list[float] = []

    def start(self) -> None:
        routable_sensors = self.network.routable_sensor_ids()
        for sensor_id in routable_sensors:
            self.env.process(self._sensor_loop(sensor_id))

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

            route = self.router.get_emhr_route(sensor_id)
            if route:
                packet.assign_route(route)
                # Bắn gói tin đi bằng một luồng thời gian thực độc lập
                self.env.process(self._transmit_packet(packet, route))
            else:
                packet.mark_dropped("NO_ROUTE", no_route=True)
                self.dropped_packets.append(packet)
                
    def _transmit_packet(self, packet: Packet, route: list[str]):
        """Mô phỏng hành trình bay qua từng trạm của gói tin."""
        # Tốc độ truyền ZigBee chuẩn (250,000 bits/s)
        bandwidth_bps = 250000.0
        # Tính độ trễ của 1 cú nhảy: (số Byte * 8) / băng thông
        transmission_delay_s = (packet.size_bytes * 8) / bandwidth_bps

        is_dropped = False

        for i in range(len(route) - 1):
            sender_id = route[i]
            receiver_id = route[i+1]
            
            # 1. Gói tin mất một khoảng thời gian để bay đến trạm tiếp theo
            yield self.env.timeout(transmission_delay_s)

            sender = self.network.sensors[sender_id]
            receiver = self.network.sensors.get(receiver_id) or self.network.sinks.get(receiver_id)
            
            # 2. Rớt gói nếu trạm trung gian lỡ "đột tử" lúc gói tin đang bay tới
            if (hasattr(sender, 'is_alive') and not sender.is_alive) or \
               (hasattr(receiver, 'is_alive') and not receiver.is_alive):
                packet.mark_dropped("NODE_DEAD_MID_FLIGHT")
                self.dropped_packets.append(packet)
                is_dropped = True
                break

            # 3. Trừ pin của các trạm
            dist_m = math.hypot(sender.x - receiver.x, sender.y - receiver.y)
            self.radio.process_transmission(sender, receiver, packet.size_bytes, dist_m)

        # 4. Nếu bình an về tới Sink, chốt sổ thời gian
        if not is_dropped:
            # Độ trễ = Thời gian lúc chạm đích - Thời gian lúc sinh ra
            actual_latency = float(self.env.now) - packet.created_at
            self.delivered_latencies.append(actual_latency)
            self.delivered_packets.append(packet)