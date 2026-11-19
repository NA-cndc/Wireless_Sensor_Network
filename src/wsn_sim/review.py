from argparse import ArgumentParser
from dataclasses import replace
from pathlib import Path
import pandas as pd
from wsn_sim.attack_verification import binomial_count_interval
from wsn_sim.attacks import SelectiveForwarding
from wsn_sim.calibration import benign_metrics, linear_quantile
from wsn_sim.config import DEFAULT_CONFIG_PATH, DetectorConfig, SimulationConfig
from wsn_sim.detection import ForwardingDetector
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, create_run_manifest, save_json, save_simulation

def review_attacker(plan: SimulationConfig, samples: int=1000) -> tuple[dict, Simulation]:
    config = replace(plan, config_profile='TEST_ONLY', num_sensors=3, num_sinks=2, attacker_ratio=2 / 3, attacker_selection='near_sink', attacker_ids=None)
    network = Network(config, sensors={node: Sensor(node, x, y, plan.initial_energy_j) for node, x, y in (('a', 1, 0), ('b', 100, 0), ('c', 100, 1))}, sinks={'first_sink': Sink('first_sink', 0, 0), 'second_sink': Sink('second_sink', 100, 0)})
    original = SelectiveForwarding(config, network.sensors, network=network)
    network.sensors['b'].consume_energy(4.9, 0)
    modified = SelectiveForwarding(replace(config, routing_algorithm='MHR', p_drop=1), network.sensors, network=network)
    drop_sets = []
    for probability in (0.25, 0.5, 0.75):
        attack = SelectiveForwarding(replace(config, attacker_ids=('b',), p_drop=probability), network.sensors)
        drop_sets.append({index for index in range(samples) if attack.drops('b', f'nested_{index}', 'a')})
    config = replace(plan, config_profile='TEST_ONLY', num_sensors=2, num_sinks=1, communication_range_m=15, routing_algorithm='EMHR', detector=None, attacker_ids=('relay',), attacker_ratio=0, p_drop=0.5, channel_loss_probability=0.05)
    network = Network(config, sensors={node: Sensor(node, x, 0, config.initial_energy_j) for node, x in (('source', 0), ('relay', 10))}, sinks={'sink': Sink('sink', 20, 0)})
    simulation = Simulation(config, network=network)
    for _ in range(samples):
        simulation.traffic_gen.generate_packet('source')
    simulation.run_for(0.1)
    packets = simulation.traffic_gen.generated_packets
    opportunities = network.sensors['relay'].received_packets
    selective = sum((packet.drop_reason == 'selective_forwarding' for packet in packets))
    natural = sum((packet.drop_reason == 'natural_link_loss' for packet in packets))
    lower, upper = binomial_count_interval(opportunities, 0.5)
    event_rows = simulation.traffic_gen.events
    selective_packets = [packet for packet in packets if packet.drop_reason == 'selective_forwarding']
    stopped_after_rx = all(([row['event'] for row in event_rows if row['packet_id'] == packet.packet_id] == ['created', 'tx', 'rx', 'dropped'] for packet in selective_packets))
    report = {'scope': 'new_specification_derived_attacker_counterexamples', 'nearest_of_all_sinks_then_id': {'expected_ids': ['a', 'b'], 'actual': original.to_dict(), 'unchanged_after_energy_routing_pdrop_change': original.attacker_ids == modified.attacker_ids}, 'coupled_probabilities_nested': drop_sets[0] <= drop_sets[1] <= drop_sets[2], 'channel_censoring': {'generated': samples, 'successful_transit_RX_opportunities': opportunities, 'selective_drops': selective, 'natural_link_loss': natural, 'conditional_drop_ratio': selective / opportunities, 'incorrect_generated_denominator_ratio': selective / samples, 'conditional_binomial_interval': [lower, upper], 'conditional_binomial_check': lower <= selective <= upper, 'selective_trace_stops_after_RX': stopped_after_rx, 'physical_packet_conservation': simulation.summary()['performance']['conservation_ok']}}
    report['checks_passed'] = original.attacker_ids == {'a', 'b'} and original.attacker_ids == modified.attacker_ids and report['coupled_probabilities_nested'] and (0 < opportunities < samples) and (natural > 0) and (lower <= selective <= upper) and stopped_after_rx and report['channel_censoring']['physical_packet_conservation']
    return (report, simulation)

def review_detector() -> dict:
    outcomes = [0] * 5 + [1] * 95
    tau = linear_quantile(outcomes, 0.05)
    config = DetectorConfig(0.8, 1, 0.1, 1, tau, 1, 1, 1000)
    reports = []
    for required in (1, 2):
        detector = ForwardingDetector(replace(config, consecutive_bad_windows=required), ['benign_relay'], sink_ids=['sink'])
        for index, forwarded in enumerate(outcomes):
            received = index + 0.1
            detector.observe_received('benign_relay', f'p{index}', 'source', received)
            if forwarded:
                detector.observe_forwarded('benign_relay', f'p{index}', received + 0.01, source_id='source')
        detector.advance(100)
        reports.append({'K': required, 'parameters': detector.summary()['parameters'], 'metrics': benign_metrics(detector), 'windows': detector.windows})
    paired = ForwardingDetector(config, ['relay_A', 'relay_B'], sink_ids=['sink'])
    paired.observe_received('relay_A', 'same_packet', 'source', 0.1)
    paired.observe_received('relay_B', 'same_packet', 'source', 0.1)
    paired.observe_forwarded('relay_B', 'same_packet', 0.11, source_id='source')
    paired.observe_forwarded('relay_A', 'different_own_packet', 0.12, source_id='relay_A')
    paired.observe_received('relay_A', 'same_packet', 'source', 0.13)
    paired.advance(1)
    summary = paired.summary()
    return {'scope': 'synthetic_benign_observer_fault_counterexample_not_calibration_data', 'FR_sequence': outcomes, 'Q0.05': tau, 'quantile_does_not_bound_EWMA_FPR': reports, 'same_packet_different_relays_and_unrelated_own_TX': summary, 'checks_passed': abs(tau - 0.95) < 1e-12 and all((row['metrics']['false_positive_windows'] == 16 and row['metrics']['fpr'] == 1 for row in reports)) and (summary['received_transit'] == 2) and (summary['forwarded'] == 1) and (summary['failed_timeout'] == 1) and (summary['relays']['relay_A']['forwarded'] == 0) and summary['conservation_ok'] and summary['input_conservation_ok'], 'interpretation': 'FR has only 5% failed windows, but EWMA trust is below tau for 16% of valid windows; ever-suspected node FPR is 100% on this one injected-fault benign relay. K=2 does not reduce these suspected FPRs.'}

def packet_demo(plan: SimulationConfig) -> Simulation:
    config = replace(plan, config_profile='TEST_ONLY', num_sensors=5, num_sinks=1, routing_algorithm='EMHR', attacker_ids=('attacker',), p_drop=1, channel_loss_probability=0, detector=DetectorConfig(0.5, 1, 0.1, 1, 0.8, 2, 1, 10))
    positions = {'source_A': (0, 0), 'source_B': (0, 10), 'attacker': (10, 0), 'good': (10, 10), 'idle': (1000, 1000)}
    network = Network(config, sensors={node: Sensor(node, *position, config.initial_energy_j) for node, position in positions.items()}, sinks={'sink': Sink('sink', 20, 5)})
    network.graph.remove_edges_from(list(network.graph.edges))
    for left, right in (('source_A', 'attacker'), ('attacker', 'sink'), ('source_B', 'good'), ('good', 'sink')):
        network.graph.add_edge(left, right, distance_m=network.distance(left, right))
    simulation = Simulation(config, network=network)

    def inject():
        for delay, sources in ((0, ['source_A', 'source_B']), (0.2, ['attacker']), (0.1, ['idle']), (0.9, ['source_A', 'source_B'])):
            yield simulation.env.timeout(delay)
            for source in sources:
                simulation.traffic_gen.generate_packet(source)
    simulation.env.process(inject())
    simulation.run_for(2.1)
    return simulation

def run_review(root: Path, output_root: Path) -> dict:
    directory = create_run_directory(output_root, 'stage4_review')
    plan = SimulationConfig.from_json(root / 'configs/plan.json')
    attacker, combined = review_attacker(plan)
    detector = review_detector()
    simulation = packet_demo(plan)
    packets = [{'packet_id': packet.packet_id, 'source': packet.source_id, 'status': packet.status.value, 'reason': packet.drop_reason, 'actual_path': ' -> '.join(packet.actual_path), 'TX': sum((row['event'] == 'tx' and row['packet_id'] == packet.packet_id for row in simulation.traffic_gen.events)), 'RX': sum((row['event'] == 'rx' and row['packet_id'] == packet.packet_id for row in simulation.traffic_gen.events))} for packet in simulation.traffic_gen.generated_packets]
    windows = [{key: row[key] for key in ('time_s', 'relay_id', 'received_transit', 'forwarded', 'failed_timeout', 'pending', 'forwarding_ratio', 'trust', 'status', 'suspected', 'bad_windows', 'isolated_until')} for row in simulation.detector.windows]
    text = '\n\n'.join(('TEST_ONLY ideal TX observer; fixed small graph; no calibration or evaluation.', 'PER PACKET\n' + pd.DataFrame(packets).to_string(index=False), 'PHYSICAL TX/RX EVENTS\n' + pd.DataFrame(simulation.traffic_gen.events)[['time_s', 'packet_id', 'node_id', 'event', 'reason']].to_string(index=False), 'RX/FWD/TIMEOUT/FR/TRUST/SUSPECTED BY COHORT\n' + pd.DataFrame(windows).to_string(index=False), f"Q0.05 benign fault counterexample={detector['Q0.05']:.6f}; valid-window suspected FPR=16%; K=1 and K=2 both ever-suspect the benign relay.", 'Human review: pending user self-review. No two-person review claimed.'))
    (directory / 'demo.txt').write_text(text + '\n', encoding='utf-8')
    save_simulation(simulation, directory / 'packet_demo', root)
    save_simulation(combined, directory / 'channel_censoring', root)
    demo_state = simulation.detector.states['attacker']
    report = {'stage': 4, 'attacker_review': attacker, 'detector_review': detector, 'demo_packets': packets, 'demo_windows': windows, 'human_review': 'PENDING_USER_SELF_REVIEW_NO_NAMES_REQUIRED', 'two_person_review_claimed': False, 'output_directory': str(directory), 'checks_passed': attacker['checks_passed'] and detector['checks_passed'] and ((demo_state.suspected_at, demo_state.isolated_at) == (1, 2))}
    save_json(report, directory / 'review_report.json')
    manifest_path = directory / 'run_manifest.json'
    manifest = create_run_manifest(plan, [*sorted(directory.rglob('*.*')), manifest_path], root)
    manifest.update({'stage': 4, 'human_review': report['human_review'], 'two_person_review_claimed': False})
    save_json(manifest, manifest_path)
    print(text)
    print(f"\nchecks_passed={report['checks_passed']}\noutput_directory={directory}")
    return report

def main() -> None:
    root = DEFAULT_CONFIG_PATH.parents[1]
    parser = ArgumentParser()
    parser.add_argument('--output', type=Path, default=root / 'results/runs')
    args = parser.parse_args()
    if not run_review(root, args.output.resolve())['checks_passed']:
        raise SystemExit(1)
if __name__ == '__main__':
    main()
