from argparse import ArgumentParser
import json
import math
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from wsn_sim.energy import RadioModel

def estimate(forwarded, payload_bytes, bandwidth_bps, *, observers_per_tx=None, ack_bytes=None, ack_distance_m=None):
    if isinstance(forwarded, bool) or not isinstance(forwarded, int) or forwarded < 0:
        raise ValueError('forwarded must be a nonnegative integer')
    for name, value in (('payload_bytes', payload_bytes), ('bandwidth_bps', bandwidth_bps)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (not math.isfinite(value)) or (value <= 0):
            raise ValueError(f'invalid {name}')
    if observers_per_tx is not None and (isinstance(observers_per_tx, bool) or not isinstance(observers_per_tx, int) or observers_per_tx < 0):
        raise ValueError('observers_per_tx must be a nonnegative integer')
    if (ack_bytes is None) != (ack_distance_m is None):
        raise ValueError('ACK size and distance must be supplied together')
    if ack_bytes is not None:
        if isinstance(ack_bytes, bool) or not isinstance(ack_bytes, int) or ack_bytes <= 0:
            raise ValueError('ACK size must be a positive integer')
        if isinstance(ack_distance_m, bool) or not isinstance(ack_distance_m, (int, float)) or (not math.isfinite(ack_distance_m)) or (ack_distance_m < 0):
            raise ValueError('ACK distance must be finite and nonnegative')
    radio = RadioModel()
    observations = None if observers_per_tx is None else forwarded * observers_per_tx
    return {'measurement_status': 'counterfactual_estimate_without_energy_or_timing_feedback', 'simulated_monitoring_energy_j': None, 'simulated_control_packets': None, 'forwarded_transit_TX_observed': forwarded, 'assumptions': {'observers_per_transit_TX': observers_per_tx, 'full_frame_bytes': payload_bytes, 'bandwidth_bps': bandwidth_bps, 'ACK_bytes': ack_bytes, 'ACK_distance_m': ack_distance_m, 'ACK_rule': None if ack_bytes is None else 'hypothetical_one_ACK_TX_plus_one_RX_per_observed_transit_TX; perfect_control_channel; no_retry'}, 'estimated_overhearing_RX_count': observations, 'estimated_overhearing_energy_j': None if observations is None else observations * radio.compute_rx_energy(payload_bytes * 8), 'estimated_active_RX_time_s': None if observations is None else observations * payload_bytes * 8 / bandwidth_bps, 'estimated_ACK_packets': None if ack_bytes is None else forwarded, 'estimated_system_ACK_energy_j': None if ack_bytes is None else forwarded * (radio.compute_tx_energy(ack_bytes * 8, ack_distance_m) + radio.compute_rx_energy(ack_bytes * 8)), 'estimated_ACK_airtime_s': None if ack_bytes is None else forwarded * ack_bytes * 8 / bandwidth_bps, 'not_included': ['idle_listening', 'MAC_contention', 'CPU_processing', 'lost_overhearing', 'ACK_loss', 'retransmission', 'control_route_advertisements', 'battery_feedback', 'observer_assignment_geometry'], 'not_a_lifetime_or_total_security_overhead_measurement': True}

def main():
    p = ArgumentParser()
    p.add_argument('run', type=Path)
    p.add_argument('--observers-per-tx', type=int)
    p.add_argument('--ack-bytes', type=int)
    p.add_argument('--ack-distance-m', type=float)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    summary = json.loads((args.run / 'summary.json').read_text(encoding='utf-8'))
    cfg = json.loads((args.run / 'configuration.json').read_text(encoding='utf-8'))
    forwarded = sum((state['forwarded'] for state in summary['detector']['relays'].values()))
    result = estimate(forwarded, cfg['wire_size_bytes'] or cfg['packet_size_bytes'], cfg['bandwidth_bps'], observers_per_tx=args.observers_per_tx, ack_bytes=args.ack_bytes, ack_distance_m=args.ack_distance_m)
    result['source_run'] = str(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
if __name__ == '__main__':
    main()
