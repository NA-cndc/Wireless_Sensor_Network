"""First Order Radio Energy Model for WSN."""

from __future__ import annotations

from wsn_sim.models import Sensor, Sink

class RadioModel:
    """Tính toán tiêu hao năng lượng truyền/nhận dựa trên khoảng cách và dung lượng."""

    def __init__(
        self,
        e_elec_j_bit: float = 50e-9,       # 50 nJ/bit
        e_fs_j_bit_m2: float = 10e-12,     # 10 pJ/bit/m^2 (Free space)
        e_mp_j_bit_m4: float = 0.0013e-12, # 0.0013 pJ/bit/m^4 (Multipath)
        d0_m: float = 87.0,                # Ngưỡng khoảng cách d0
    ) -> None:
        self.e_elec = e_elec_j_bit
        self.e_fs = e_fs_j_bit_m2
        self.e_mp = e_mp_j_bit_m4
        self.d0 = d0_m

    def compute_tx_energy(self, packet_size_bits: int, distance_m: float) -> float:
        """Tính năng lượng tiêu hao để phát một gói tin (Joules)."""
        if distance_m < self.d0:
            # Mô hình không gian tự do (cự ly gần)
            amp_energy = self.e_fs * packet_size_bits * (distance_m ** 2)
        else:
            # Mô hình đa đường (cự ly xa)
            amp_energy = self.e_mp * packet_size_bits * (distance_m ** 4)
            
        return (self.e_elec * packet_size_bits) + amp_energy

    def compute_rx_energy(self, packet_size_bits: int) -> float:
        """Tính năng lượng tiêu hao để nhận một gói tin (Joules)."""
        return self.e_elec * packet_size_bits

    def process_transmission(
        self, 
        sender: Sensor, 
        receiver: Sensor | Sink, 
        packet_size_bytes: int, 
        distance_m: float
    ) -> None:
        """
        Thực thi quá trình trừ pin của nút gửi và nút nhận.
        Lưu ý: Kích thước cấu hình là Bytes, cần nhân 8 để chuyển sang Bits.
        """
        packet_size_bits = packet_size_bytes * 8
        
        # 1. Trừ pin nút gửi (Sensor)
        tx_energy = self.compute_tx_energy(packet_size_bits, distance_m)
        sender.consume_energy(tx_energy)
        
        # 2. Trừ pin nút nhận (Chỉ trừ nếu nút nhận là Sensor)
        # Trạm Sink cắm điện lưới nên không bị giới hạn năng lượng
        if isinstance(receiver, Sensor):
            rx_energy = self.compute_rx_energy(packet_size_bits)
            receiver.consume_energy(rx_energy)