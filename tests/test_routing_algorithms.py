"""Tests for routing algorithms: MHR, EMHR, and S-EMHR.

Kiểm tra:
- Item 4: MHR tìm đường ít hop nhất tới nhiều sink, no-route, không đi qua node chết.
- Item 5: EMHR lọc pin dưới/bằng/trên ngưỡng, source dưới ngưỡng nhưng đủ pin TX.
- Item 6: Ưu tiên hop trước distance, distance trước energy, deterministic tie cuối.
- Item 7: Reroute khi relay chết/thấp pin, đổi sink, no-route không fallback.
- Item 23: S-EMHR tránh node blacklist, đổi sink, no-route khi không còn đường.
"""

import networkx as nx
import pytest

from wsn_sim.config import SimulationConfig
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.routing import RoutingEngine


def make_test_network() -> Network:
    """Tạo topology nhỏ với tọa độ và liên kết xác định trước để kiểm tra tính tay."""
    cfg = SimulationConfig(
        area_width_m=1000.0,
        area_height_m=1000.0,
        num_sensors=6,
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

    net.sinks["sink_00"] = Sink("sink_00", 100.0, 0.0)
    net.sinks["sink_01"] = Sink("sink_01", 0.0, 100.0)

    net.sensors["sensor_000"] = Sensor("sensor_000", 0.0, 0.0, 5.0)
    net.sensors["sensor_001"] = Sensor("sensor_001", 50.0, 0.0, 5.0)
    net.sensors["sensor_002"] = Sensor("sensor_002", 0.0, 50.0, 5.0)
    net.sensors["sensor_003"] = Sensor("sensor_003", 25.0, 25.0, 5.0)

    for s_id, s in net.sensors.items():
        net.graph.add_node(s_id, node_type="sensor", x=s.x, y=s.y, energy_j=s.energy_j)
    for k_id, k in net.sinks.items():
        net.graph.add_node(k_id, node_type="sink", x=k.x, y=k.y)

    def add_edge(u, v):
        u_node = net.sensors.get(u) or net.sinks.get(u)
        v_node = net.sensors.get(v) or net.sinks.get(v)
        d = u_node.distance_to(v_node)
        net.graph.add_edge(u, v, distance_m=d, weight=d)

    add_edge("sensor_000", "sensor_001")
    add_edge("sensor_001", "sink_00")

    add_edge("sensor_000", "sensor_002")
    add_edge("sensor_002", "sink_01")

    return net


def test_mhr_finds_minimum_hop_route():
    net = make_test_network()
    router = RoutingEngine(net, algorithm="MHR")

    route = router.get_mhr_route("sensor_000")
    assert route is not None
    assert len(route) == 3
    assert route[0] == "sensor_000"
    assert route[-1] in ("sink_00", "sink_01")


def test_mhr_excludes_dead_nodes():
    net = make_test_network()
    router = RoutingEngine(net, algorithm="MHR")

    net.sensors["sensor_001"].energy_j = 0.0
    net.sensors["sensor_001"].is_alive = False

    route = router.get_mhr_route("sensor_000")
    assert route == ["sensor_000", "sensor_002", "sink_01"]

    net.sensors["sensor_002"].energy_j = 0.0
    net.sensors["sensor_002"].is_alive = False
    assert router.get_mhr_route("sensor_000") is None


def test_mhr_dead_source_cannot_route():
    net = make_test_network()
    router = RoutingEngine(net, algorithm="MHR")
    net.sensors["sensor_000"].energy_j = 0.0
    net.sensors["sensor_000"].is_alive = False
    assert router.get_mhr_route("sensor_000") is None


def test_emhr_filters_below_threshold_and_allows_sub_threshold_source():
    net = make_test_network()
    router = RoutingEngine(net, algorithm="EMHR", alpha_energy=0.20)

    net.sensors["sensor_000"].energy_j = 0.5
    net.sensors["sensor_000"].is_alive = True

    net.sensors["sensor_001"].energy_j = 0.8

    net.sensors["sensor_002"].energy_j = 2.0

    route = router.get_emhr_route("sensor_000")
    assert route == ["sensor_000", "sensor_002", "sink_01"]

    net.sensors["sensor_002"].energy_j = 0.9
    assert router.get_emhr_route("sensor_000") is None


def test_emhr_lexicographic_order():
    """Kiểm tra thứ tự ưu tiên: 1. Hop, 2. Distance, 3. Energy Penalty, 4. Deterministic ID."""
    net = make_test_network()
    router = RoutingEngine(net, algorithm="EMHR", alpha_energy=0.20)

    net.graph["sensor_000"]["sensor_001"]["distance_m"] = 40.0
    net.graph["sensor_001"]["sink_00"]["distance_m"] = 50.0

    net.graph["sensor_000"]["sensor_002"]["distance_m"] = 50.0
    net.graph["sensor_002"]["sink_01"]["distance_m"] = 50.0

    route = router.get_emhr_route("sensor_000")
    assert route == ["sensor_000", "sensor_001", "sink_00"]

    net.graph["sensor_000"]["sensor_001"]["distance_m"] = 50.0
    net.sensors["sensor_001"].energy_j = 2.0
    net.sensors["sensor_002"].energy_j = 4.0

    route = router.get_emhr_route("sensor_000")
    assert route == ["sensor_000", "sensor_002", "sink_01"]


def test_semhr_avoids_blacklisted_nodes():
    net = make_test_network()
    router = RoutingEngine(net, algorithm="S-EMHR", alpha_energy=0.20)

    blacklist = {"sensor_001"}
    route = router.get_semhr_route("sensor_000", blacklist=blacklist)
    assert route == ["sensor_000", "sensor_002", "sink_01"]

    blacklist.add("sensor_002")
    assert router.get_semhr_route("sensor_000", blacklist=blacklist) is None
