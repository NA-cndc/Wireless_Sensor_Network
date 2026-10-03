"""First Order Radio Energy Model for WSN with strict accounting and ledger."""

from __future__ import annotations

import math
from typing import Any

from wsn_sim.models import Sensor, Sink


class RadioModel:
    """Tính toán tiêu hao năng lượng truyền/nhận dựa trên khoảng cách và dung lượng.

    Tuân thủ First-Order Radio Model:
    - l = packet_size_bytes * 8 (bits)
    - ETX(l, d) = l * E_elec + l * epsilon_fs * d^2  (khi d < d0)
    - ETX(l, d) = l * E_elec + l * epsilon_mp * d^4  (khi d >= d0)
    - ERX(l) = l * E_elec
    - d0 = sqrt(epsilon_fs / epsilon_mp)
    - E_DA = 0 (Data aggregation tắt)
    """

    def __init__(
        self,
        e_elec_j_bit: float = 50e-9,
        e_fs_j_bit_m2: float = 10e-12,
        e_mp_j_bit_m4: float = 0.0013e-12,
        e_da_j_bit: float = 0.0,
        d0_m: float | None = None,
    ) -> None:
        self.e_elec = float(e_elec_j_bit)
        self.e_fs = float(e_fs_j_bit_m2)
        self.e_mp = float(e_mp_j_bit_m4)
        self.e_da = float(e_da_j_bit)

        if d0_m is not None:
            self.d0 = float(d0_m)
        else:
            self.d0 = math.sqrt(self.e_fs / self.e_mp)

        self.energy_ledger: list[dict[str, Any]] = []

    def compute_tx_energy(self, packet_size_bits: int, distance_m: float) -> float:
        """Tính năng lượng tiêu hao để phát một gói tin (Joules)."""
        if packet_size_bits < 0:
            raise ValueError("packet_size_bits must not be negative")
        if distance_m < 0:
            raise ValueError("distance_m must not be negative")

        if distance_m < self.d0:
            amp_energy = self.e_fs * packet_size_bits * (distance_m ** 2)
        else:
            amp_energy = self.e_mp * packet_size_bits * (distance_m ** 4)

        return (self.e_elec * packet_size_bits) + amp_energy

    def compute_rx_energy(self, packet_size_bits: int) -> float:
        """Tính năng lượng tiêu hao để nhận một gói tin (Joules)."""
        if packet_size_bits < 0:
            raise ValueError("packet_size_bits must not be negative")
        return self.e_elec * packet_size_bits

    def attempt_transmission(
        self,
        sender: Sensor,
        receiver: Sensor | Sink,
        packet_size_bytes: int,
        distance_m: float,
        sim_time_s: float = 0.0,
        packet_id: str = "",
    ) -> dict[str, Any]:
        """Thực thi kiểm tra và trừ pin có bảo đảm tính toàn vẹn (Atomic Debit).

        Chính sách kiểm tra nghiêm ngặt:
        1. Sender không đủ pin TX -> Thao tác không thành công, gói hủy do energy_depletion,
           không trừ pin vô lý ở sender, receiver không tốn pin.
        2. Sender đủ pin TX nhưng Receiver (nếu là Sensor) không đủ pin RX:
           Sender đã phát sóng vô tuyến nên vẫn bị trừ pin TX, Receiver không nhận được gói,
           gói hủy do energy_depletion tại receiver.
        3. Cả hai đủ pin -> Trừ pin TX ở Sender, trừ pin RX ở Receiver (Sink không trừ pin).
        4. Ghi sổ cái (energy_ledger) cho mọi giao dịch.
        """
        packet_size_bits = packet_size_bytes * 8
        tx_energy = self.compute_tx_energy(packet_size_bits, distance_m)
        rx_energy = self.compute_rx_energy(packet_size_bits) if isinstance(receiver, Sensor) else 0.0

        ledger_entry: dict[str, Any] = {
            "time_s": sim_time_s,
            "packet_id": packet_id,
            "sender_id": sender.node_id,
            "receiver_id": receiver.node_id,
            "distance_m": distance_m,
            "tx_energy_j": tx_energy,
            "rx_energy_j": rx_energy,
            "success": False,
            "reason": "OK",
            "sender_energy_before": sender.energy_j,
            "receiver_energy_before": receiver.energy_j if isinstance(receiver, Sensor) else None,
        }

        if not sender.has_enough_energy(tx_energy):
            ledger_entry["success"] = False
            ledger_entry["reason"] = "TX_INSUFFICIENT_ENERGY"
            ledger_entry["tx_energy_j"] = 0.0
            ledger_entry["rx_energy_j"] = 0.0
            self.energy_ledger.append(ledger_entry)
            return ledger_entry

        if isinstance(receiver, Sensor) and not receiver.has_enough_energy(rx_energy):
            sender.consume_energy(tx_energy)
            sender.tx_energy_total_j += tx_energy
            ledger_entry["success"] = False
            ledger_entry["reason"] = "RX_INSUFFICIENT_ENERGY"
            ledger_entry["tx_energy_j"] = tx_energy
            ledger_entry["rx_energy_j"] = 0.0
            ledger_entry["sender_energy_after"] = sender.energy_j
            ledger_entry["receiver_energy_after"] = receiver.energy_j
            self.energy_ledger.append(ledger_entry)
            return ledger_entry

        sender.consume_energy(tx_energy)
        sender.tx_energy_total_j += tx_energy
        if isinstance(receiver, Sensor):
            receiver.consume_energy(rx_energy)
            receiver.rx_energy_total_j += rx_energy

        ledger_entry["success"] = True
        ledger_entry["sender_energy_after"] = sender.energy_j
        ledger_entry["receiver_energy_after"] = receiver.energy_j if isinstance(receiver, Sensor) else None
        self.energy_ledger.append(ledger_entry)
        return ledger_entry

    def process_transmission(
        self,
        sender: Sensor,
        receiver: Sensor | Sink,
        packet_size_bytes: int,
        distance_m: float,
    ) -> bool:
        """Wrapper tương thích ngược thực thi quá trình trừ pin."""
        result = self.attempt_transmission(
            sender=sender,
            receiver=receiver,
            packet_size_bytes=packet_size_bytes,
            distance_m=distance_m,
        )
        return bool(result["success"])