"""Tests for packet lifecycle, sink reception deduplication, queues, and conservation equation.

Kiểm tra:
- Item 11: Packet tới sink thực có DELIVERED, timestamp, sink_id, path và counter khớp.
- Item 12: Deduplication gói tin tại sink, sequence number theo nguồn.
- Item 13: Sensor sống cô lập vẫn tạo gói NO_ROUTE, node chết không tạo gói.
- Item 14: Queue overflow drop khi vượt quá capacity.
- Item 15: Phương trình bảo toàn gói: generated = delivered + dropped + pending.
"""

import simpy

from wsn_sim.config import SimulationConfig
from wsn_sim.models import Packet, PacketStatus, Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation


def test_sink_deduplication_and_delivered_status():
    sink = Sink("sink_00", 100.0, 100.0)
    packet = Packet("pkt_01", "sensor_000", created_at=10.0, size_bytes=128)
    packet.assign_route(["sensor_000", "sink_00"])

    res1 = sink.receive(packet, received_at=12.5)
    assert res1 is True
    assert packet.status == PacketStatus.DELIVERED
    assert packet.sink_id == "sink_00"
    assert packet.delivered_at == 12.5
    assert packet.latency_s == 2.5
    assert sink.received_packet_count == 1
    assert sink.total_received_bytes == 128
    assert sink.total_received_bits == 1024

    res2 = sink.receive(packet, received_at=13.0)
    assert res2 is False
    assert sink.received_packet_count == 1


def test_packet_sequence_numbers_per_source():
    """Kiểm tra sequence number tăng dần theo từng source."""
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(cfg, current_range_m=300.0, quiet=True)
    sim.run_for(31.0)

    pkts = [p for p in sim.traffic_gen.generated_packets if p.source_id == "sensor_000"]
    assert len(pkts) == 3
    seqs = [p.sequence_number for p in pkts]
    assert seqs == [1, 2, 3]


def test_isolated_sensor_generates_no_route_packet():
    """Sensor sống nhưng bị cô lập (không có đường tới sink) vẫn sinh gói và bị đánh dấu NO_ROUTE."""
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(cfg, current_range_m=10.0, quiet=True)
    sim.run_for(20.0)

    gen = len(sim.traffic_gen.generated_packets)
    assert gen > 0
    no_route_pkts = [p for p in sim.traffic_gen.dropped_packets if p.status == PacketStatus.NO_ROUTE]
    assert len(no_route_pkts) > 0
    assert no_route_pkts[0].drop_reason == "unreachable"


def test_packet_conservation_equation():
    """Phương trình bảo toàn gói: generated == delivered + dropped + pending."""
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(cfg, current_range_m=300.0, quiet=True)
    sim.run_for(50.0)

    metrics = sim.get_metrics()
    gen = metrics["generated_packets"]
    deliv = metrics["delivered_packets"]
    drop = metrics["dropped_packets"]
    pending = metrics["pending_packets"]

    assert gen == deliv + drop + pending
    assert gen > 0
    assert deliv > 0


def test_queue_overflow_drop():
    """Khi hàng đợi đầy (queue_capacity), gói mới sinh sẽ bị hủy do queue_drop."""
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(cfg, current_range_m=300.0, quiet=True)
    sim.traffic_gen.queue_capacity = 0
    sim.run_for(20.0)

    queue_drops = [p for p in sim.traffic_gen.dropped_packets if p.drop_reason == "queue_drop"]
    assert len(queue_drops) > 0
