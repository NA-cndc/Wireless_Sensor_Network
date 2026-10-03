"""Tests for Selective Forwarding attack model and TrustDetector with EWMA.

Kiểm tra:
- Item 19: Attacker không là sink; p_drop = 0/1; source attacker vẫn gửi dữ liệu của mình.
- Item 20: Tách bạch natural_link_loss và selective_forwarding.
- Item 21: Công thức EWMA; n_min; K cửa sổ; empty-window; blacklist expiry.
- Item 22: Benign calibration; detector không truy cập ground truth.
- Item 24: Confusion matrix (TP, FP, TN, FN, TPR, FPR, Precision, F1).
"""

import pytest

from wsn_sim.config import SimulationConfig
from wsn_sim.detection import TrustDetector
from wsn_sim.simulation import Simulation


def test_attacker_selection_constraints():
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(cfg, current_range_m=300.0, attacker_ratio=0.05, quiet=True)

    attackers = sim.traffic_gen.attackers
    assert len(attackers) == 23
    for node_id in attackers:
        assert node_id in sim.network.sensors
        assert node_id not in sim.network.sinks


def test_p_drop_zero_causes_no_attack_drops():
    """Khi p_drop = 0.0, dù có attacker nhưng không có gói nào bị selective_forwarding drop."""
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(cfg, current_range_m=300.0, attacker_ratio=0.10, drop_prob=0.0, quiet=True)
    sim.run_for(30.0)

    attack_drops = [p for p in sim.traffic_gen.dropped_packets if p.drop_reason == "selective_forwarding"]
    assert len(attack_drops) == 0


def test_source_attacker_sends_its_own_data():
    """Attacker chỉ bỏ gói quá cảnh khi làm relay, KHÔNG tự bỏ gói dữ liệu do chính mình tạo ra."""
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(cfg, current_range_m=300.0, attacker_ratio=0.05, drop_prob=1.0, quiet=True)
    sim.run_for(20.0)

    attackers = sim.traffic_gen.attackers
    assert len(attackers) > 0

    atk_node = next(iter(attackers))
    atk_gen_pkts = [p for p in sim.traffic_gen.generated_packets if p.source_id == atk_node]
    assert len(atk_gen_pkts) > 0
    assert all(p.drop_reason != "selective_forwarding" or p.drop_node_id != atk_node for p in atk_gen_pkts)


def test_natural_loss_and_selective_forwarding_are_distinct():
    """Gói mất được phân loại rạch ròi, không đếm hai lần."""
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(
        cfg,
        current_range_m=300.0,
        attacker_ratio=0.05,
        drop_prob=0.50,
        channel_loss_prob=0.05,
        quiet=True,
    )
    sim.run_for(30.0)

    nat_drops = {p.packet_id for p in sim.traffic_gen.dropped_packets if p.drop_reason == "natural_link_loss"}
    atk_drops = {p.packet_id for p in sim.traffic_gen.dropped_packets if p.drop_reason == "selective_forwarding"}

    assert len(nat_drops & atk_drops) == 0


def test_trust_detector_ewma_formula_and_blacklist_isolation():
    """Kiểm tra công thức EWMA và cơ chế Blacklist/T_isolation trên dữ liệu biết trước."""
    detector = TrustDetector(
        beta_trust=0.8,
        n_min=5,
        tau_threshold=0.85,
        k_consecutive=2,
        t_isolation_s=100.0,
        window_duration_s=50.0,
        initial_trust=1.0,
    )

    for _ in range(5):
        detector.record_forwarding_attempt("sensor_bad", forwarded=True)
    for _ in range(5):
        detector.record_forwarding_attempt("sensor_bad", forwarded=False)

    detector.end_window(current_sim_time_s=50.0)
    assert detector.nodes["sensor_bad"].trust_score == pytest.approx(0.90)
    assert detector.nodes["sensor_bad"].consecutive_low_windows == 0

    for _ in range(4):
        detector.record_forwarding_attempt("sensor_bad", forwarded=True)
    for _ in range(6):
        detector.record_forwarding_attempt("sensor_bad", forwarded=False)

    detector.end_window(current_sim_time_s=100.0)
    assert detector.nodes["sensor_bad"].trust_score == pytest.approx(0.80)
    assert detector.nodes["sensor_bad"].consecutive_low_windows == 1
    assert "sensor_bad" not in detector.get_blacklist()

    for _ in range(4):
        detector.record_forwarding_attempt("sensor_bad", forwarded=True)
    for _ in range(6):
        detector.record_forwarding_attempt("sensor_bad", forwarded=False)

    detector.end_window(current_sim_time_s=150.0)
    assert detector.nodes["sensor_bad"].trust_score == pytest.approx(0.72)
    assert "sensor_bad" in detector.get_blacklist()
    assert detector.nodes["sensor_bad"].is_blacklisted is True
    assert detector.nodes["sensor_bad"].isolation_until_s == 250.0

    detector.end_window(current_sim_time_s=200.0)
    assert "sensor_bad" in detector.get_blacklist()

    detector.end_window(current_sim_time_s=260.0)
    assert "sensor_bad" not in detector.get_blacklist()


def test_confusion_matrix_metrics():
    """Kiểm tra tính toán TPR, FPR, Precision, F1 theo công thức chuẩn."""
    detector = TrustDetector()
    all_sensors = {f"sensor_{i:03d}" for i in range(10)}
    actual_attackers = {"sensor_000", "sensor_001", "sensor_002"}

    detector._get_or_create("sensor_000").detection_timestamp_s = 50.0
    detector._get_or_create("sensor_001").detection_timestamp_s = 60.0
    detector._get_or_create("sensor_005").detection_timestamp_s = 55.0

    stats = detector.evaluate_detection(actual_attackers, all_sensors, first_attack_time_s=10.0)
    assert stats["TP"] == 2
    assert stats["FP"] == 1
    assert stats["FN"] == 1
    assert stats["TN"] == 6

    assert stats["TPR"] == pytest.approx(2 / 3)
    assert stats["FPR"] == pytest.approx(1 / 7)
    assert stats["Precision"] == pytest.approx(2 / 3)
    assert stats["F1"] == pytest.approx(2 / 3)
    assert stats["avg_detection_delay_s"] == pytest.approx(45.0)
