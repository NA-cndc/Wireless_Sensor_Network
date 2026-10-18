"""Mô-đun sinh lưu lượng (Traffic Generator) cho WSN bằng SimPy với mô hình Radio Energy."""

from __future__ import annotations

import math

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
            # Chờ đúng chu kỳ sinh gói tin (đơn vị: giây, ví dụ: 10.0s)
            yield self.env.timeout(self.config.packet_interval_s)

            # Nếu cảm biến đã chết (hết pin) thì chấm dứt vòng lặp sinh gói
            if not sensor_obj.is_alive:
                break

            # Tạo gói tin mới với kích thước và số thứ tự xác định
            packet_count += 1
            pkt_id = f"{sensor_id}_p{packet_count}"
            packet = Packet(
                packet_id=pkt_id,
                source_id=sensor_id,
                created_at=float(self.env.now),
                size_bytes=self.config.packet_size_bytes,
                payload_size_bytes=self.config.payload_size_bytes,
                sequence_number=packet_count,
            )
            self.generated_packets.append(packet)
            sensor_obj.generated_packets += 1

            # Kiểm tra sức chứa hàng đợi của nút nguồn (queue_capacity: số gói đang chờ)
            queue = self.queues[sensor_id]
            if len(queue) >= self.queue_capacity:
                packet.mark_dropped("queue_drop", node_id=sensor_id)
                self.dropped_packets.append(packet)
                sensor_obj.dropped_packets += 1
                continue

            # Tìm tuyến đường ban đầu từ nút nguồn tới Sink
            route = self.router.get_route(sensor_id, is_source=True)

            if route:
                # Gán tuyến hợp lệ, đưa gói vào hàng đợi FIFO và đánh thức tiến trình TX
                packet.assign_route(route)
                queue.append(packet)
                if not self.tx_events[sensor_id].triggered:
                    self.tx_events[sensor_id].succeed()
            else:
                # Nút bị cô lập hoặc không tìm thấy đường dẫn tới bất kỳ Sink nào
                packet.mark_dropped("unreachable", node_id=sensor_id, no_route=True)
                self.dropped_packets.append(packet)
                sensor_obj.dropped_packets += 1

    def _sensor_tx_loop(self, sensor_id: str):
        """Tiến trình FIFO phục vụ phát gói tin tuần tự độc quyền cho từng sensor node."""
        sensor = self.network.sensors[sensor_id]
        # Thời gian truyền một gói tin trên kênh vô tuyến (giây) = (kích_thước_bit) / (băng_thông_bps)
        transmission_delay_s = (self.config.packet_size_bytes * 8) / self.bandwidth_bps

        while sensor.is_alive:
            # Nếu hàng đợi đang rỗng, tiến trình chuyển sang trạng thái ngủ chờ sự kiện có gói mới
            if not self.queues[sensor_id]:
                self.tx_events[sensor_id] = self.env.event()
                yield self.tx_events[sensor_id]
                if not sensor.is_alive:
                    break

            if not self.queues[sensor_id]:
                continue

            # Lấy gói tin ở đầu hàng đợi theo nguyên tắc vào trước ra trước (FIFO)
            packet = self.queues[sensor_id].pop(0)

            # Kiểm tra điều kiện relay EMHR: Ngoại lệ dưới ngưỡng chỉ dành cho nút nguồn thực sự;
            # Relay còn sống nhưng có pin < Eth thì KHÔNG được chuyển tiếp (hủy với relay_below_threshold)
            is_source = (sensor_id == packet.source_id)
            if not is_source and self.router.algorithm == "EMHR":
                if not sensor.can_forward(self.router.threshold_j):
                    packet.mark_dropped("relay_below_threshold", node_id=sensor_id)
                    self.dropped_packets.append(packet)
                    sensor.dropped_packets += 1
                    continue

            # Xác định tập các nút cần né tránh: Toàn bộ nút đã đi qua trong packet.path trừ nút hiện tại
            avoid_nodes = set(packet.path) - {sensor_id}

            # Trích xuất phân đoạn tuyến đường còn lại từ vị trí nút hiện tại
            try:
                curr_idx = len(packet.path) - 1
                if curr_idx < len(packet.route) and packet.route[curr_idx] == sensor_id:
                    remaining_route = packet.route[curr_idx:]
                else:
                    remaining_route = packet.route[packet.route.index(sensor_id):]
            except (ValueError, IndexError):
                remaining_route = []

            # Kiểm tra xem tuyến đường còn lại có hợp lệ và không vi phạm tập avoid_nodes hay không
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

            # Nếu tuyến đường cũ bị gián đoạn (relay phía trước chết/hết pin), thực hiện định tuyến lại
            if not route_valid:
                new_sub_route = self.router.get_route(
                    sensor_id,
                    algorithm=self.router.algorithm,
                    avoid_nodes=avoid_nodes,
                    is_source=is_source,
                )
                if new_sub_route:
                    # Cập nhật nhất quán: ghép lộ trình đã đi với tuyến mới, cập nhật sink_id và chỉ số hop
                    self.router.route_change_count += 1
                    packet.route = list(packet.path[:-1]) + new_sub_route
                    packet.sink_id = new_sub_route[-1]
                    packet.current_hop_index = len(packet.path) - 1
                    remaining_route = new_sub_route
                else:
                    # Không còn đường vòng nào hợp lệ tới Sink mà tránh được các nút đã qua -> Hủy gói NO_ROUTE
                    packet.mark_dropped("unreachable", node_id=sensor_id, no_route=True)
                    self.dropped_packets.append(packet)
                    sensor.dropped_packets += 1
                    continue

            # Xác định nút nhận ở chặng kế tiếp (tiếp tục hành trình multi-hop)
            next_hop_id = remaining_route[1]
            receiver = self.network.sensors.get(next_hop_id) or self.network.sinks.get(next_hop_id)
            if receiver is None:
                packet.mark_dropped("unreachable", node_id=sensor_id, no_route=True)
                self.dropped_packets.append(packet)
                sensor.dropped_packets += 1
                continue

            # Chiếm dụng kênh truyền vô tuyến trong khoảng thời gian delay truyền sóng
            yield self.env.timeout(transmission_delay_s)

            # Kiểm tra nếu nút gửi bị chết giữa chừng trong lúc truyền sóng
            if not sensor.is_alive:
                packet.mark_dropped("node_dead_mid_flight", node_id=sensor_id)
                self.dropped_packets.append(packet)
                sensor.dropped_packets += 1
                continue

            # Tính khoảng cách hình học thực tế giữa nút phát và nút thu (mét)
            dist_m = math.hypot(sensor.x - receiver.x, sensor.y - receiver.y)

            # Thực thi giao dịch trừ năng lượng nguyên tử qua mô hình First-Order Radio Model
            ledger_entry = self.radio.attempt_transmission(
                sender=sensor,
                receiver=receiver,
                packet_size_bytes=packet.size_bytes,
                distance_m=dist_m,
                sim_time_s=float(self.env.now),
                packet_id=packet.packet_id,
            )

            # Nếu giao dịch thất bại do không đủ năng lượng TX hoặc RX
            if not ledger_entry["success"]:
                fail_node = sensor_id if ledger_entry["reason"] == "TX_INSUFFICIENT_ENERGY" else next_hop_id
                packet.mark_dropped("energy_depletion", node_id=fail_node)
                self.dropped_packets.append(packet)
                sensor.dropped_packets += 1
                continue

            # Ghi nhận chặng nhảy thành công vào lịch sử đường đi của gói tin
            packet.record_hop(next_hop_id)
            if not is_source:
                sensor.forwarded_packets += 1

            # Trường hợp 1: Nút nhận là trạm Sink đích
            if isinstance(receiver, Sink):
                is_new = receiver.receive(packet, float(self.env.now))
                if is_new:
                    self.delivered_packets.append(packet)
                    if packet.latency_s is not None:
                        self.delivered_latencies.append(packet.latency_s)
                continue

            # Trường hợp 2: Nút nhận là một nút cảm biến chuyển tiếp (Relay Sensor)
            if isinstance(receiver, Sensor):
                receiver.received_packets += 1
                # Nếu receiver cạn kiệt năng lượng sau khi tốn chi phí RX -> Hủy gói tại receiver
                if not receiver.is_alive:
                    packet.mark_dropped("energy_depletion", node_id=receiver.node_id)
                    self.dropped_packets.append(packet)
                    receiver.dropped_packets += 1
                    if receiver.node_id in self.tx_events and not self.tx_events[receiver.node_id].triggered:
                        self.tx_events[receiver.node_id].succeed()
                    continue

                # Kiểm tra dung lượng hàng đợi tại nút nhận (Relay queue)
                queue = self.queues[receiver.node_id]
                if len(queue) >= self.queue_capacity:
                    # Hàng đợi đầy: Gói bị loại queue_drop, chi phí RX đã tốn được giữ nguyên, không tính TX
                    packet.mark_dropped("queue_drop", node_id=receiver.node_id)
                    self.dropped_packets.append(packet)
                    receiver.dropped_packets += 1
                else:
                    # Hàng đợi còn chỗ: Đưa gói vào hàng đợi của relay và đánh thức tiến trình TX của relay
                    queue.append(packet)
                    if not self.tx_events[receiver.node_id].triggered:
                        self.tx_events[receiver.node_id].succeed()

        # Khi cảm biến chết (hết pin): Toàn bộ gói tin còn tồn đọng trong hàng đợi bị loại do energy_depletion
        while self.queues[sensor_id]:
            pkt = self.queues[sensor_id].pop(0)
            pkt.mark_dropped("energy_depletion", node_id=sensor_id)
            self.dropped_packets.append(pkt)
            sensor.dropped_packets += 1
