from argparse import ArgumentParser
from dataclasses import asdict, replace
import json
from pathlib import Path
from wsn_sim.config import DEFAULT_CONFIG_PATH, DetectorConfig, SimulationConfig
from wsn_sim.detection import ForwardingDetector
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.randomness import event_occurs
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, create_run_manifest, save_detector_outputs, save_json, save_simulation

def replay_observations(config: DetectorConfig, events: list[tuple[str, float, str]], end_time_s: float) -> ForwardingDetector:
    detector = ForwardingDetector(config, ['relay'], sink_ids=['sink'])
    for kind, time_s, packet_id in events:
        if kind == 'rx':
            detector.observe_received('relay', packet_id, 'source', time_s)
        elif kind == 'tx':
            detector.observe_forwarded('relay', packet_id, time_s, source_id='source')
        else:
            raise ValueError(f'unknown observation kind: {kind}')
    detector.advance(end_time_s)
    return detector

def sensitivity_checks() -> list[dict]:
    base = DetectorConfig(beta_trust=0.5, window_size_s=1, forwarding_timeout_s=0.4, min_observations=1, trust_threshold=0.8, consecutive_bad_windows=2, initial_trust=1, isolation_duration_s=10, calibration_status='TEST_ONLY')
    events = [('rx', 0.1, 'p1'), ('tx', 0.15, 'p1'), ('rx', 0.2, 'p2'), ('rx', 1.2, 'p3'), ('tx', 1.5, 'p3'), ('rx', 2.2, 'p4'), ('tx', 2.25, 'p4')]
    variants = [{}, {'window_size_s': 2}, {'min_observations': 2}, {'beta_trust': 0.8}, {'trust_threshold': 0.6}, {'consecutive_bad_windows': 1}, {'forwarding_timeout_s': 0.1}]
    rows = []
    for changes in variants:
        config = replace(base, **changes)
        detector = replay_observations(config, events, 5)
        rows.append({'scope': 'TEST_ONLY_one_factor_synthetic_observation_sensitivity', 'changed_parameters': changes, 'parameters': asdict(config), 'input_events': events, 'summary': detector.summary(), 'windows': detector.windows})
    return rows

def _simulation_case(plan: SimulationConfig, detector: DetectorConfig, name: str) -> tuple[Simulation, dict]:
    channel_seed = plan.seed
    if name == 'channel_after_tx':

        def loses(seed, sender, receiver):
            return event_occurs(replace(plan, seed=seed).stream_seeds['channel_loss'], 0.5, 'source_p1', sender, receiver, 0)
        channel_seed = next((seed for seed in range(1000) if not loses(seed, 'source', 'relay') and loses(seed, 'relay', 'sink')))
    config = replace(plan, config_profile='TEST_ONLY', num_sensors=2, num_sinks=1, communication_range_m=15, routing_algorithm='MHR', detector=detector, seed=channel_seed, attacker_ids=('relay',) if name == 'selective_forwarding' else (), p_drop=1 if name == 'selective_forwarding' else 0, channel_loss_probability=0.5 if name == 'channel_after_tx' else 0)
    network = Network(config, sensors={node: Sensor(node, x, 0, config.initial_energy_j) for node, x in (('source', 0), ('relay', 10))}, sinks={'sink': Sink('sink', 20, 0)})
    simulation = Simulation(config, network=network)
    if name == 'relay_energy_failure':
        bits = config.transmission_size_bytes * 8
        budget = bits * 5e-08 + bits * (5e-08 + 1e-11 * 10 ** 2) / 2
        network.sensors['relay'].consume_energy(plan.initial_energy_j - budget, 0)
    if name == 'missing_tx_observation':
        original = simulation.detector.observe_forwarded

        def omit_relay_tx(relay_id, packet_id, time_s, *, source_id=None):
            if relay_id != 'relay':
                original(relay_id, packet_id, time_s, source_id=source_id)
        simulation.detector.observe_forwarded = omit_relay_tx
    context = {'scope': 'TEST_ONLY_known_graph_ideal_observer_validation', 'initial_residual_energy_j': {node: sensor.energy_j for node, sensor in network.sensors.items()}, 'observer_fault_injected': 'relay_tx_observation_suppressed' if name == 'missing_tx_observation' else None, 'debug_seed_chosen_for_channel_boundary_case': name == 'channel_after_tx'}
    simulation.traffic_gen.generate_packet('source')
    if name == 'selective_forwarding':

        def second_packet():
            yield simulation.env.timeout(1.2)
            simulation.traffic_gen.generate_packet('source')
        simulation.env.process(second_packet())
    simulation.run_for(2.1)
    return (simulation, context)

def run_detector_checks(project_root: str | Path, output_root: str | Path | None=None) -> dict:
    root = Path(project_root).resolve()
    plan = SimulationConfig.from_json(root / 'configs/plan.json')
    directory = create_run_directory(root / 'results/runs' if output_root is None else output_root, 'stage3_detector')
    hand_config = DetectorConfig(beta_trust=0.5, window_size_s=5, forwarding_timeout_s=1, min_observations=1, trust_threshold=0.8, consecutive_bad_windows=2, initial_trust=1, isolation_duration_s=10, calibration_status='TEST_ONLY')
    hand_events = [('rx', 0.1, 'p1'), ('tx', 0.2, 'p1'), ('rx', 0.3, 'p2'), ('rx', 5.1, 'p3')]
    hand = replay_observations(hand_config, hand_events, 10)
    cohort_events = [('rx', 0, 'p0'), ('rx', 4, 'p1'), ('tx', 4.1, 'p1'), ('rx', 4.5, 'p2'), ('tx', 4.6, 'p2')]
    cohort = replay_observations(hand_config, cohort_events, 10)
    for name, detector in (('hand_calculation', hand), ('deadline_cohort', cohort)):
        save_detector_outputs(detector, directory / name)
    physical_config = replace(hand_config, window_size_s=1, forwarding_timeout_s=0.1)
    cases = {}
    expected = {'benign': (1, 1, 0), 'channel_after_tx': (1, 1, 0), 'relay_energy_failure': (1, 0, 1), 'missing_tx_observation': (1, 0, 1), 'selective_forwarding': (2, 0, 2)}
    for name, counters in expected.items():
        simulation, context = _simulation_case(plan, physical_config, name)
        state = simulation.detector.states['relay']
        result = {'context': context, 'summary': simulation.summary(), 'counter_check': (state.received_transit, state.forwarded, state.failed_timeout) == counters}
        save_simulation(simulation, directory / name, root, {'case_check.json': result})
        cases[name] = result
    sensitivity = sensitivity_checks()
    save_json({'selection_performed': False, 'configurations': sensitivity}, directory / 'sensitivity.json')
    report = {'stage': 3, 'scope': 'TEST_ONLY_detector_semantics_validation_not_calibration_or_evaluation', 'observer_model': ForwardingDetector.model_metadata(), 'hand_calculation': {'input_events': hand_events, 'summary': hand.summary(), 'windows': hand.windows}, 'deadline_cohort': {'input_events': cohort_events, 'summary': cohort.summary(), 'windows': cohort.windows}, 'simulation_cases': cases, 'sensitivity_configurations': len(sensitivity), 'calibration_status': 'NEEDS_CALIBRATION', 'configuration_selected': False, 'checks_passed': [row['trust'] for row in hand.windows] == [0.75, 0.375] and [row['observations'] for row in cohort.windows] == [1, 2] and all((case['counter_check'] and case['summary']['detector']['conservation_ok'] and case['summary']['detector']['input_conservation_ok'] for case in cases.values())) and all((row['summary']['conservation_ok'] and row['summary']['input_conservation_ok'] for row in sensitivity)), 'output_directory': str(directory)}
    report_path = save_json(report, directory / 'detector_checks.json')
    manifest_path = directory / 'run_manifest.json'
    manifest = create_run_manifest(plan, [*sorted(directory.rglob('*.*')), manifest_path], root)
    manifest['stage'] = 3
    manifest['observer'] = ForwardingDetector.model_metadata()
    manifest['validation_report'] = str(report_path)
    save_json(manifest, manifest_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return report

def main() -> None:
    parser = ArgumentParser()
    parser.add_argument('--output', type=Path, default=DEFAULT_CONFIG_PATH.parents[1] / 'results/runs')
    args = parser.parse_args()
    report = run_detector_checks(DEFAULT_CONFIG_PATH.parents[1], args.output)
    if not report['checks_passed']:
        raise SystemExit(1)
if __name__ == '__main__':
    main()
