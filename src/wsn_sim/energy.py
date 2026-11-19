from math import isfinite, sqrt
from wsn_sim.models import Sensor, Sink

class RadioModel:

    def __init__(self, e_elec_j_bit: float=5e-08, e_fs_j_bit_m2: float=1e-11, e_mp_j_bit_m4: float=1.3e-15) -> None:
        values = (e_elec_j_bit, e_fs_j_bit_m2, e_mp_j_bit_m4)
        if any((not isfinite(value) or value <= 0 for value in values)):
            raise ValueError('radio energy coefficients must be finite and positive')
        self.e_elec, self.e_fs, self.e_mp = values
        self.d0 = sqrt(self.e_fs / self.e_mp)

    def compute_tx_energy(self, packet_size_bits: int, distance_m: float) -> float:
        if packet_size_bits <= 0 or not isfinite(distance_m) or distance_m < 0:
            raise ValueError('invalid packet size or distance')
        amplifier = self.e_fs * distance_m ** 2 if distance_m < self.d0 else self.e_mp * distance_m ** 4
        return packet_size_bits * (self.e_elec + amplifier)

    def compute_rx_energy(self, packet_size_bits: int) -> float:
        if packet_size_bits <= 0:
            raise ValueError('packet_size_bits must be positive')
        return self.e_elec * packet_size_bits

    @staticmethod
    def spend(sensor: Sensor, required_j: float, time_s: float, *, reason: str='radio', packet_id: str | None=None) -> bool:
        enough = sensor.is_alive and sensor.energy_j >= required_j
        sensor.consume_energy(required_j, time_s, reason=reason, packet_id=packet_id)
        return enough

    def process_transmission(self, sender: Sensor, receiver: Sensor | Sink, packet_size_bytes: int, distance_m: float, time_s: float=0.0) -> bool:
        size_bits = packet_size_bytes * 8
        if not self.spend(sender, self.compute_tx_energy(size_bits, distance_m), time_s):
            return False
        return isinstance(receiver, Sink) or self.spend(receiver, self.compute_rx_energy(size_bits), time_s)
