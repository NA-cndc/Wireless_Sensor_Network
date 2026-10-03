"""Tests for first-order radio energy model and atomic energy debits.

Kiểm tra:
- Item 8: ETX nhánh d^2 / d^4, ERX, byte -> bit, d0 tính động theo hệ số.
- Item 9: Sender thiếu TX, Receiver thiếu RX, pin đúng bằng chi phí, không âm pin.
- Item 10: Sổ cái energy ledger khớp mức giảm pin, hop sau gói mất không phát sinh debit.
"""

import math
import pytest

from wsn_sim.energy import RadioModel
from wsn_sim.models import Sensor, Sink


def test_radio_d0_computed_dynamically():
    radio = RadioModel(e_fs_j_bit_m2=10e-12, e_mp_j_bit_m4=0.0013e-12)
    expected_d0 = math.sqrt(10e-12 / 0.0013e-12)
    assert radio.d0 == pytest.approx(expected_d0)
    assert abs(radio.d0 - 87.7058) < 0.01

    custom_radio = RadioModel(e_fs_j_bit_m2=20e-12, e_mp_j_bit_m4=0.0020e-12)
    assert custom_radio.d0 == pytest.approx(100.0)


def test_etx_free_space_vs_multipath_branches():
    radio = RadioModel()
    packet_bits = 128 * 8

    d_close = 50.0
    expected_tx_close = (radio.e_elec * packet_bits) + (radio.e_fs * packet_bits * (d_close ** 2))
    actual_tx_close = radio.compute_tx_energy(packet_bits, d_close)
    assert actual_tx_close == pytest.approx(expected_tx_close)

    d_far = 150.0
    expected_tx_far = (radio.e_elec * packet_bits) + (radio.e_mp * packet_bits * (d_far ** 4))
    actual_tx_far = radio.compute_tx_energy(packet_bits, d_far)
    assert actual_tx_far == pytest.approx(expected_tx_far)

    expected_rx = radio.e_elec * packet_bits
    assert radio.compute_rx_energy(packet_bits) == pytest.approx(expected_rx)


def test_sender_lacks_tx_energy():
    """Sender có pin nhưng không đủ để phát gói tin -> Giao dịch thất bại, pin không bị trừ âm."""
    radio = RadioModel()
    cost = radio.compute_tx_energy(128 * 8, 50.0)

    sender = Sensor("s1", 0, 0, initial_energy_j=5.0, energy_j=1e-6)
    receiver = Sensor("s2", 50, 0, initial_energy_j=5.0, energy_j=5.0)

    result = radio.attempt_transmission(sender, receiver, 128, 50.0, sim_time_s=10.0, packet_id="p1")
    assert result["success"] is False
    assert result["reason"] == "TX_INSUFFICIENT_ENERGY"
    assert sender.energy_j == 1e-6
    assert receiver.energy_j == 5.0


def test_receiver_lacks_rx_energy():
    """Sender đủ pin phát nhưng Receiver không đủ pin nhận.

    Sender đã phát sóng nên bị trừ pin TX, Receiver không nhận được gói.
    """
    radio = RadioModel()
    cost_tx = radio.compute_tx_energy(128 * 8, 50.0)
    cost_rx = radio.compute_rx_energy(128 * 8)

    sender = Sensor("s1", 0, 0, initial_energy_j=5.0, energy_j=1.0)
    receiver = Sensor("s2", 50, 0, initial_energy_j=5.0, energy_j=cost_rx / 2.0)

    result = radio.attempt_transmission(sender, receiver, 128, 50.0, sim_time_s=10.0, packet_id="p2")
    assert result["success"] is False
    assert result["reason"] == "RX_INSUFFICIENT_ENERGY"
    assert sender.energy_j == pytest.approx(1.0 - cost_tx)
    assert receiver.energy_j == cost_rx / 2.0


def test_exact_energy_depletion_edge_case():
    """Node có năng lượng bằng đúng chi phí TX: Hoàn thành phát rồi node chết (energy = 0, is_alive = False)."""
    radio = RadioModel()
    cost_tx = radio.compute_tx_energy(128 * 8, 50.0)
    cost_rx = radio.compute_rx_energy(128 * 8)

    sender = Sensor("s1", 0, 0, initial_energy_j=5.0, energy_j=cost_tx)
    receiver = Sensor("s2", 50, 0, initial_energy_j=5.0, energy_j=cost_rx * 2.0)

    result = radio.attempt_transmission(sender, receiver, 128, 50.0)
    assert result["success"] is True
    assert sender.energy_j == 0.0
    assert sender.is_alive is False
    assert receiver.energy_j == pytest.approx(cost_rx)


def test_energy_ledger_matches_battery_drop():
    radio = RadioModel()
    sender = Sensor("s1", 0, 0, initial_energy_j=5.0)
    receiver = Sensor("s2", 50, 0, initial_energy_j=5.0)

    res = radio.attempt_transmission(sender, receiver, 128, 50.0, sim_time_s=5.0, packet_id="pkt_001")
    assert res["success"] is True
    assert len(radio.energy_ledger) == 1

    entry = radio.energy_ledger[0]
    assert entry["packet_id"] == "pkt_001"
    assert entry["tx_energy_j"] == pytest.approx(5.0 - sender.energy_j)
    assert entry["rx_energy_j"] == pytest.approx(5.0 - receiver.energy_j)


def test_sink_does_not_consume_energy():
    radio = RadioModel()
    sender = Sensor("s1", 0, 0, initial_energy_j=5.0)
    sink = Sink("sink_00", 50, 0)

    res = radio.attempt_transmission(sender, sink, 128, 50.0)
    assert res["success"] is True
    assert res["rx_energy_j"] == 0.0
