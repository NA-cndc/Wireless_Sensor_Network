"""Behavioral tests verifying the 4 required bug fixes for multi-hop WSN simulation."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import networkx as nx
import pytest

from wsn_sim.config import SimulationConfig
from wsn_sim.energy import RadioModel
from wsn_sim.models import Packet, PacketStatus, Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine
from wsn_sim.simulation import Simulation


def create_linear_test_network(
    num_sensors: int = 2,
    initial_energy_j: float = 5.0,
    distance_m: float = 50.0,
    packet_interval_s: float = 2.0,
) -> Network:
    """Tạo topology đường thẳng đơn giản: sensor_000 -> ... -> sensor_XXX -> sink_00."""
    cfg = SimulationConfig(
        area_width_m=1000.0,
        area_height_m=1000.0,
        num_sensors=num_sensors,
        num_sinks=1,
        initial_energy_j=initial_energy_j,
        packet_size_bytes=128,
        packet_interval_s=packet_interval_s,
        communication_ranges_m=(250.0, 300.0, 350.0),
        seed=42,
    )
    net = Network(cfg, communication_range_m=300.0)
    net.sensors.clear()
    net.sinks.clear()
    net.graph = nx.Graph()

    for i in range(num_sensors):
        s_id = f"sensor_{i:03d}"
        net.sensors[s_id] = Sensor(s_id, float(i * distance_m), 0.0, initial_energy_j)
        net.graph.add_node(s_id, node_type="sensor", x=float(i * distance_m), y=0.0, energy_j=initial_energy_j)

    sink_id = "sink_00"
    sink_x = float(num_sensors * distance_m)
    net.sinks[sink_id] = Sink(sink_id, sink_x, 0.0)
    net.graph.add_node(sink_id, node_type="sink", x=sink_x, y=0.0)

    for i in range(num_sensors - 1):
        u = f"sensor_{i:03d}"
        v = f"sensor_{i+1:03d}"
        net.graph.add_edge(u, v, distance_m=distance_m, weight=distance_m)

    last_sensor = f"sensor_{num_sensors - 1:03d}"
    net.graph.add_edge(last_sensor, sink_id, distance_m=distance_m, weight=distance_m)

    return net


def test_fifo_queue_positive_capacity_and_overflow():
    """Lỗi 1: Kiểm thử hàng đợi FIFO dung lượng dương (1) và tràn hàng đợi khi tốc độ sinh vượt tốc độ phục vụ."""
    net = create_linear_test_network(num_sensors=1, initial_energy_j=10.0, distance_m=50.0, packet_interval_s=2.0)
    sim = Simulation(net, quiet=True)
    sim.traffic_gen.queue_capacity = 1
    sim.traffic_gen.bandwidth_bps = 100.0

    sim.run_for(15.0)

    gen_pkts = sim.traffic_gen.generated_packets
    assert len(gen_pkts) >= 5

    queue_drops = [p for p in sim.traffic_gen.dropped_packets if p.drop_reason == "queue_drop"]
    assert len(queue_drops) >= 2
    for p in queue_drops:
        assert p.drop_node_id == "sensor_000"
        assert p.status == PacketStatus.DROPPED

    delivered = sim.traffic_gen.delivered_packets
    assert len(delivered) >= 1
    assert delivered[0].sequence_number == 1


def test_relay_rx_success_then_queue_drop_retains_rx_cost_and_no_tx():
    """Lỗi 1: Relay nhận thành công rồi phát hiện hàng đợi đầy vẫn giữ chi phí RX, không tính TX."""
    net = create_linear_test_network(num_sensors=2, initial_energy_j=5.0, distance_m=50.0, packet_interval_s=1.0)
    sim = Simulation(net, quiet=True)
    sim.traffic_gen.queue_capacity = 1
    sim.traffic_gen.bandwidth_bps = 500.0

    relay = net.sensors["sensor_001"]
    energy_before = relay.energy_j

    sim.run_for(10.0)

    drops = [p for p in sim.traffic_gen.dropped_packets if p.drop_node_id == "sensor_001" and p.drop_reason == "queue_drop"]
    assert len(drops) >= 1
    assert relay.received_packets >= 1
    assert relay.rx_energy_total_j > 0.0
    assert relay.energy_j < energy_before


def test_dead_node_stops_processing_and_drops_waiting_packets():
    """Lỗi 1: Node chết không tiếp tục phát gói và các gói trong hàng đợi bị loại đúng một lần."""
    net = create_linear_test_network(num_sensors=1, initial_energy_j=0.0001, distance_m=50.0)
    sensor = net.sensors["sensor_000"]

    radio = RadioModel()
    cost_tx = radio.compute_tx_energy(128 * 8, 50.0)
    sensor.energy_j = cost_tx
    sensor.initial_energy_j = 5.0

    sim = Simulation(net, quiet=True)
    sim.traffic_gen.queue_capacity = 5
    sim.traffic_gen.bandwidth_bps = 50000.0

    sim.run_for(10.0)

    assert not sensor.is_alive
    assert sensor.energy_j == 0.0


def test_emhr_relay_below_threshold_after_rx_cannot_tx():
    """Lỗi 2: Relay giảm dưới ngưỡng sau RX không được TX, bị loại với relay_below_threshold, không đánh dấu chết."""
    net = create_linear_test_network(num_sensors=2, initial_energy_j=5.0, distance_m=50.0)
    router = RoutingEngine(net, algorithm="EMHR", alpha_energy=0.20)
    radio = RadioModel()

    rx_cost = radio.compute_rx_energy(128 * 8)
    relay = net.sensors["sensor_001"]
    relay.energy_j = router.threshold_j + (rx_cost / 2.0)
    relay.initial_energy_j = 5.0

    sim = Simulation(net, routing_algorithm="EMHR", quiet=True)
    sim.traffic_gen.queue_capacity = 10
    sim.run_for(3.0)

    drops = [p for p in sim.traffic_gen.dropped_packets if p.drop_reason == "relay_below_threshold"]
    assert len(drops) >= 1
    assert drops[0].drop_node_id == "sensor_001"
    assert relay.is_alive is True
    assert relay.energy_j > 0.0
    assert relay.energy_j < router.threshold_j


def test_emhr_source_below_threshold_can_transmit_own_packet():
    """Lỗi 2: Nguồn thật dưới ngưỡng nhưng đủ pin vẫn được phát gói của chính mình."""
    net = create_linear_test_network(num_sensors=1, initial_energy_j=5.0, distance_m=50.0)
    source = net.sensors["sensor_000"]
    source.energy_j = 0.5
    source.initial_energy_j = 5.0

    sim = Simulation(net, routing_algorithm="EMHR", quiet=True)
    sim.run_for(3.0)

    delivered = sim.traffic_gen.delivered_packets
    assert len(delivered) >= 1
    assert delivered[0].source_id == "sensor_000"
    assert source.is_alive is True


def test_mhr_allows_forwarding_through_relay_below_emhr_threshold():
    """Lỗi 2: Thuật toán MHR không áp ngưỡng EMHR lên nút chuyển tiếp còn sống."""
    net = create_linear_test_network(num_sensors=2, initial_energy_j=5.0, distance_m=50.0)
    relay = net.sensors["sensor_001"]
    relay.energy_j = 0.5
    relay.initial_energy_j = 5.0

    sim = Simulation(net, routing_algorithm="MHR", quiet=True)
    sim.run_for(5.0)

    delivered = sim.traffic_gen.delivered_packets
    assert len(delivered) >= 1
    assert any(p.source_id == "sensor_000" for p in delivered)


def test_reroute_avoids_visited_nodes_and_drops_unreachable_on_backward_only():
    """Lỗi 3: Khi đường phía trước bị hỏng và chỉ còn đường quay lại node đã qua, gói bị hủy NO_ROUTE."""
    cfg = SimulationConfig(
        area_width_m=500.0,
        area_height_m=500.0,
        num_sensors=3,
        num_sinks=1,
        initial_energy_j=5.0,
        packet_size_bytes=128,
        packet_interval_s=10.0,
        communication_ranges_m=(250.0, 300.0, 350.0),
        seed=42,
    )
    net = Network(cfg, communication_range_m=300.0)
    net.sensors.clear()
    net.sinks.clear()
    net.graph = nx.Graph()

    net.sensors["sensor_000"] = Sensor("sensor_000", 0.0, 0.0, 5.0)
    net.sensors["sensor_001"] = Sensor("sensor_001", 50.0, 0.0, 5.0)
    net.sensors["sensor_002"] = Sensor("sensor_002", 100.0, 0.0, 5.0)
    net.sinks["sink_00"] = Sink("sink_00", 150.0, 0.0)

    for s_id, s in net.sensors.items():
        net.graph.add_node(s_id, node_type="sensor", x=s.x, y=s.y, energy_j=s.energy_j)
    net.graph.add_node("sink_00", node_type="sink", x=150.0, y=0.0)

    net.graph.add_edge("sensor_000", "sensor_001", distance_m=50.0)
    net.graph.add_edge("sensor_001", "sensor_002", distance_m=50.0)
    net.graph.add_edge("sensor_002", "sink_00", distance_m=50.0)

    router = RoutingEngine(net, algorithm="MHR")
    route = router.get_route("sensor_000")
    assert route == ["sensor_000", "sensor_001", "sensor_002", "sink_00"]

    net.sensors["sensor_002"].energy_j = 0.0
    net.sensors["sensor_002"].is_alive = False

    sub_route = router.get_route(
        "sensor_001",
        avoid_nodes={"sensor_000"},
        is_source=False,
    )
    assert sub_route is None


def test_reroute_finds_loop_free_alternative_route():
    """Lỗi 3: Tuyến thay thế né tránh hoàn toàn các node đã đi qua và cập nhật route, path, sink_id."""
    cfg = SimulationConfig(
        area_width_m=500.0,
        area_height_m=500.0,
        num_sensors=4,
        num_sinks=2,
        initial_energy_j=5.0,
        packet_size_bytes=128,
        packet_interval_s=10.0,
        communication_ranges_m=(250.0, 300.0, 350.0),
        seed=42,
    )
    net = Network(cfg, communication_range_m=300.0)
    net.sensors.clear()
    net.sinks.clear()
    net.graph = nx.Graph()

    net.sensors["sensor_S"] = Sensor("sensor_S", 0.0, 0.0, 5.0)
    net.sensors["sensor_B"] = Sensor("sensor_B", 50.0, 0.0, 5.0)
    net.sensors["sensor_C1"] = Sensor("sensor_C1", 100.0, 20.0, 5.0)
    net.sensors["sensor_C2"] = Sensor("sensor_C2", 100.0, -20.0, 5.0)
    net.sinks["sink_01"] = Sink("sink_01", 150.0, 20.0)
    net.sinks["sink_02"] = Sink("sink_02", 150.0, -20.0)

    for s_id, s in net.sensors.items():
        net.graph.add_node(s_id, node_type="sensor", x=s.x, y=s.y, energy_j=s.energy_j)
    for k_id, k in net.sinks.items():
        net.graph.add_node(k_id, node_type="sink", x=k.x, y=k.y)

    net.graph.add_edge("sensor_S", "sensor_B", distance_m=50.0)
    net.graph.add_edge("sensor_B", "sensor_C1", distance_m=50.0)
    net.graph.add_edge("sensor_C1", "sink_01", distance_m=50.0)
    net.graph.add_edge("sensor_B", "sensor_C2", distance_m=50.0)
    net.graph.add_edge("sensor_C2", "sink_02", distance_m=50.0)

    router = RoutingEngine(net, algorithm="MHR")

    net.sensors["sensor_C1"].is_alive = False
    net.sensors["sensor_C1"].energy_j = 0.0

    new_sub = router.get_route(
        "sensor_B",
        avoid_nodes={"sensor_S"},
        is_source=False,
    )
    assert new_sub == ["sensor_B", "sensor_C2", "sink_02"]
    assert "sensor_S" not in new_sub


def test_csv_exports_all_generated_packets_and_independent_id_sets(tmp_path: Path):
    """Lỗi 4: CSV xuất tất cả gói đã sinh, để trống timestamp gói chưa hoàn tất, kiểm tra độc lập tập ID."""
    net = create_linear_test_network(num_sensors=2, initial_energy_j=5.0, distance_m=50.0)
    sim = Simulation(net, quiet=True)
    sim.traffic_gen.queue_capacity = 10
    sim.traffic_gen.bandwidth_bps = 500.0

    sim.run_for(6.0)

    out_dir = tmp_path / "test_out"
    saved = sim.export_results(out_dir)
    packets_csv = saved["packets"]

    with packets_csv.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    gen_pkts = sim.traffic_gen.generated_packets
    assert len(reader) == len(gen_pkts)

    gen_ids = {p.packet_id for p in gen_pkts}
    deliv_ids = {p.packet_id for p in sim.traffic_gen.delivered_packets}
    drop_ids = {p.packet_id for p in sim.traffic_gen.dropped_packets}
    pending_ids = {
        p.packet_id for p in gen_pkts
        if p.status in (PacketStatus.CREATED, PacketStatus.IN_TRANSIT)
    }

    assert gen_ids == (deliv_ids | drop_ids | pending_ids)
    assert len(deliv_ids & drop_ids) == 0
    assert len(deliv_ids & pending_ids) == 0
    assert len(drop_ids & pending_ids) == 0
    assert len(gen_ids) == len(deliv_ids) + len(drop_ids) + len(pending_ids)

    for row in reader:
        pid = row["packet_id"]
        if pid in pending_ids:
            assert row["delivered_at"] == ""
            assert row["latency_s"] == ""
            assert row["status"] in ("CREATED", "IN_TRANSIT")
        elif pid in deliv_ids:
            assert row["delivered_at"] != ""
            assert row["latency_s"] != ""
            assert row["status"] == "DELIVERED"
        elif pid in drop_ids:
            assert row["status"] in ("DROPPED", "NO_ROUTE")
            assert row["drop_reason"] != ""


def test_multihop_accounting_and_energy_ledger_consistency():
    """Kiểm tra toàn diện: multi-hop đến đúng sink, sổ cái khớp mức giảm pin, không âm pin, không trùng ID."""
    net = create_linear_test_network(num_sensors=3, initial_energy_j=5.0, distance_m=50.0, packet_interval_s=2.0)
    sim = Simulation(net, routing_algorithm="EMHR", quiet=True)
    sim.run_for(12.0)

    delivered = sim.traffic_gen.delivered_packets
    assert len(delivered) > 0

    for pkt in delivered:
        assert pkt.sink_id == "sink_00"
        assert pkt.status == PacketStatus.DELIVERED
        assert pkt.path[-1] == "sink_00"

    deliv_ids = [p.packet_id for p in delivered]
    assert len(deliv_ids) == len(set(deliv_ids))

    drop_ids = [p.packet_id for p in sim.traffic_gen.dropped_packets]
    assert len(drop_ids) == len(set(drop_ids))
    assert len(set(deliv_ids) & set(drop_ids)) == 0

    for s_id, s in net.sensors.items():
        assert s.energy_j >= 0.0

        tx_ledger_cost = sum(
            e["tx_energy_j"] for e in sim.radio.energy_ledger
            if e["sender_id"] == s_id and e["success"]
        )
        rx_ledger_cost = sum(
            e["rx_energy_j"] for e in sim.radio.energy_ledger
            if e["receiver_id"] == s_id and e["success"]
        )
        expected_drop = tx_ledger_cost + rx_ledger_cost
        actual_drop = s.initial_energy_j - s.energy_j
        assert actual_drop == pytest.approx(expected_drop, abs=1e-9)
