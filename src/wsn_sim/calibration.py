from argparse import ArgumentParser
from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
import pandas as pd
from wsn_sim.config import DEFAULT_CONFIG_PATH, DetectorConfig, SimulationConfig, require_integer, require_number, require_probability
from wsn_sim.detection import ForwardingDetector
from wsn_sim.provenance import json_digest, source_fingerprint
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, create_run_manifest, save_csv, save_detector_outputs, save_json
SELECTION_ORDER = ['lowest_worst_channel_conditional_fpr', 'highest_tau', 'shortest_K_times_W_plus_timeout', 'highest_min_seed_coverage', 'beta_closest_to_0.8', 'lowest_N_min', 'candidate_id']

@dataclass(frozen=True, slots=True)
class BenignTrace:
    seed: int
    channel_loss_probability: float
    sensor_ids: tuple[str, ...]
    sink_ids: tuple[str, ...]
    end_time_s: float
    events: list[tuple[str, float, str, str, str]]

def linear_quantile(values, probability: float) -> float | None:
    require_probability('quantile', probability)
    ordered = sorted(values)
    for value in ordered:
        require_probability('forwarding_ratio', value)
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])

def validate_protocol(protocol: dict) -> None:
    if protocol.get('version') == 'long_horizon_benign_v1':
        _validate_long_horizon_protocol(protocol)
        return
    if protocol['version'] != 'stage4_benign_v1':
        raise ValueError('unsupported calibration protocol')
    partitions = protocol['seed_partitions']
    required = {'calibration_fit', 'benign_validation', 'attack_validation_reserved', 'evaluation_reserved'}
    if set(partitions) != required:
        raise ValueError('all four seed partitions must be declared')
    seen = set()
    for name, seeds in partitions.items():
        if not isinstance(seeds, list) or not seeds:
            raise ValueError(f'empty or invalid seed partition: {name}')
        for seed in seeds:
            require_integer('seed', seed, 0)
            if seed in seen:
                raise ValueError(f'seed partitions overlap or repeat seed {seed}')
            seen.add(seed)
    channels = protocol['channel_loss_probabilities']
    if set(channels) != {0, 0.01, 0.05} or len(channels) != 3:
        raise ValueError('calibration must cover channel loss 0, 0.01, 0.05 exactly once')
    if protocol['selection_order'] != SELECTION_ORDER:
        raise ValueError('unsupported selection criteria')
    if protocol['observation_model'] != ForwardingDetector.model_metadata()['version'] or protocol['routing_algorithm'] != 'EMHR':
        raise ValueError('protocol does not match the passive ideal EMHR observer')
    require_number('duration_s', protocol['duration_s'])
    require_probability('tau_quantile', protocol['tau_quantile'])
    if protocol['tau_quantile'] != 0.05 or 0 not in protocol['tau_offsets']:
        raise ValueError('Q0.05 itself must be a tau candidate')
    if len(set(protocol['tau_offsets'])) != len(protocol['tau_offsets']):
        raise ValueError('tau offsets must be unique')
    for offset in protocol['tau_offsets']:
        require_number('negative_tau_offset', -offset, strict=False)
        if offset < -1:
            raise ValueError('tau offset out of range')
    require_probability('max_empirical_conditional_fpr', protocol['max_empirical_conditional_fpr'])
    require_probability('min_seed_coverage', protocol['min_seed_coverage'])
    require_integer('min_valid_windows_per_channel', protocol['min_valid_windows_per_channel'])
    structures = protocol['structural_grid']
    if not structures or len({json_digest(row) for row in structures}) != len(structures):
        raise ValueError('structural grid must be nonempty and unique')
    for row in structures:
        detector_parameters(protocol, row, 0.5)
        if protocol['duration_s'] <= row['window_size_s'] + row['forwarding_timeout_s']:
            raise ValueError('horizon must include at least one complete observation window')

def _validate_long_horizon_protocol(protocol: dict) -> None:
    if protocol['duration_s'] != 10000 or set(protocol['channel_loss_probabilities']) != {0, 0.01, 0.05}:
        raise ValueError('long-horizon calibration requires 10000s and three benign channels')
    required = {'calibration_fit', 'benign_validation', 'attack_validation_reserved', 'evaluation_reserved'}
    if set(protocol['seed_partitions']) != required:
        raise ValueError('all four independent seed partitions are required')
    seen = set()
    for name, seeds in protocol['seed_partitions'].items():
        if not seeds or (name == 'evaluation_reserved' and len(seeds) < 30):
            raise ValueError('empty partition or fewer than 30 evaluation seeds')
        for seed in seeds:
            require_integer('seed', seed, 0)
            if seed in seen:
                raise ValueError('seed partitions overlap')
            seen.add(seed)
    if protocol['observation_model'] != ForwardingDetector.model_metadata()['version'] or protocol['routing_algorithm'] != 'EMHR':
        raise ValueError('unsupported observer or routing model')
    for name in ('max_empirical_fpr', 'max_empirical_conditional_fpr', 'min_seed_coverage'):
        require_probability(name, protocol[name])
    if protocol['prediction'] != 'ever_suspected_by_cutoff_all_sensors':
        raise ValueError('prediction scope must be declared without changing the FPR denominator')
    expected_order = ['highest_tau_within_fpr_budget', 'lowest_worst_conditional_fpr', 'highest_min_seed_coverage', 'K_closest_to_2', 'shortest_window', 'candidate_id']
    if protocol['selection_order'] != expected_order:
        raise ValueError('long-horizon selection criteria changed')
    from itertools import product
    grid = protocol['grid']
    expected_fields = {'window_size_s', 'min_observations', 'beta_trust', 'trust_threshold', 'consecutive_bad_windows'}
    if set(grid) != expected_fields or any((not values or len(values) != len(set(values)) for values in grid.values())):
        raise ValueError('invalid detector grid')
    for values in product(*grid.values()):
        config = DetectorConfig(**dict(zip(grid, values)), **protocol['fixed'])
        if config.calibration_status != 'TEST_ONLY' or config.window_size_s + config.forwarding_timeout_s >= protocol['duration_s']:
            raise ValueError('invalid calibration candidate')

def detector_parameters(protocol: dict, structure: dict, tau: float) -> DetectorConfig:
    return DetectorConfig(**structure, trust_threshold=tau, initial_trust=protocol['initial_trust'], isolation_duration_s=protocol['isolation_duration_s'], calibration_status='TEST_ONLY')

def replay_trace(trace: BenignTrace, config: DetectorConfig) -> ForwardingDetector:
    detector = ForwardingDetector(config, trace.sensor_ids, sink_ids=trace.sink_ids)
    for kind, time_s, relay_id, packet_id, source_id in trace.events:
        if kind == 'rx':
            detector.observe_received(relay_id, packet_id, source_id, time_s)
        elif kind == 'tx':
            detector.observe_forwarded(relay_id, packet_id, time_s, source_id=source_id)
        else:
            raise ValueError(f'invalid observable event {kind}')
    detector.advance(trace.end_time_s)
    return detector

def benign_metrics(detector: ForwardingDetector) -> dict:
    states = list(detector.states.values())
    observed = [state for state in states if state.valid_windows > 0]
    false_positives = sum((state.suspected_at is not None for state in states))
    conditional_fp = sum((state.suspected_at is not None for state in observed))
    valid = [row for row in detector.windows if row['status'] == 'valid']
    summary = detector.summary()
    return {'sensor_population': len(states), 'FP': false_positives, 'TN': len(states) - false_positives, 'fpr': false_positives / len(states) if states else None, 'observed_nodes': len(observed), 'conditional_FP': conditional_fp, 'conditional_TN': len(observed) - conditional_fp, 'conditional_fpr': conditional_fp / len(observed) if observed else None, 'coverage': len(observed) / len(states) if states else 0, 'valid_windows': len(valid), 'false_positive_windows': sum((row['suspected'] for row in valid)), 'window_fpr': sum((row['suspected'] for row in valid)) / len(valid) if valid else None, 'ever_isolated_nodes': sum((state.isolated_at is not None for state in states)), 'received_transit': summary['received_transit'], 'forwarded': summary['forwarded'], 'failed_timeout': summary['failed_timeout'], 'pending': summary['pending'], 'observations_awaiting_cohort': summary['observations_awaiting_cohort'], 'conservation_ok': summary['conservation_ok'], 'input_conservation_ok': summary['input_conservation_ok']}

def aggregate_benign(rows: list[dict]) -> list[dict]:
    summaries = []
    for channel in (0, 0.01, 0.05):
        group = [row for row in rows if row['channel_loss_probability'] == channel]
        population = sum((row['sensor_population'] for row in group))
        observed = sum((row['observed_nodes'] for row in group))
        fp = sum((row['FP'] for row in group))
        conditional_fp = sum((row['conditional_FP'] for row in group))
        windows = sum((row['valid_windows'] for row in group))
        summaries.append({'channel_loss_probability': channel, 'runs': len(group), 'FP': fp, 'TN': population - fp, 'fpr': fp / population if population else None, 'conditional_FP': conditional_fp, 'conditional_TN': observed - conditional_fp, 'conditional_fpr': conditional_fp / observed if observed else None, 'observed_nodes': observed, 'sensor_population': population, 'coverage': observed / population if population else 0, 'min_seed_coverage': min((row['coverage'] for row in group), default=0), 'valid_windows': windows, 'window_fpr': sum((row['false_positive_windows'] for row in group)) / windows if windows else None, 'mean_seed_fpr': mean((row['fpr'] for row in group)) if group else None, 'max_seed_fpr': max((row['fpr'] for row in group), default=None), 'ever_isolated_nodes': sum((row['ever_isolated_nodes'] for row in group)), 'all_invariants_ok': bool(group) and all((row['conservation_ok'] and row['input_conservation_ok'] for row in group))})
    return summaries

def acceptable(channels: list[dict], protocol: dict) -> bool:
    return all((row['conditional_fpr'] is not None and row['conditional_fpr'] <= protocol['max_empirical_conditional_fpr'] and (row['min_seed_coverage'] >= protocol['min_seed_coverage']) and (row['valid_windows'] >= protocol['min_valid_windows_per_channel']) and row['all_invariants_ok'] for row in channels))

def select_candidate(candidates: list[dict], protocol: dict) -> dict:
    eligible = [row for row in candidates if row['eligible']]
    if not eligible:
        raise ValueError('no candidate meets preregistered benign FPR/coverage requirements')

    def rank(row):
        parameters = row['parameters']
        return (max((item['conditional_fpr'] for item in row['channels'])), -parameters['trust_threshold'], parameters['consecutive_bad_windows'] * parameters['window_size_s'] + parameters['forwarding_timeout_s'], -min((item['min_seed_coverage'] for item in row['channels'])), abs(parameters['beta_trust'] - 0.8), parameters['min_observations'], row['candidate_id'])
    if protocol['selection_order'] != SELECTION_ORDER:
        raise ValueError('selection criteria changed')
    return min(eligible, key=rank)

def _capture_trace(plan, seed, channel, directory, root, duration_s) -> BenignTrace:
    started = perf_counter()
    config = replace(plan, seed=seed, routing_algorithm='EMHR', detector=None, attacker_ids=(), attacker_ratio=0, p_drop=0, channel_loss_probability=channel)
    simulation = Simulation(config)
    simulation.run_for(duration_s)
    events = [(row['event'], row['time_s'], row['node_id'], row['packet_id'], row['source_id']) for row in simulation.traffic_gen.events if row['event'] in {'rx', 'tx'}]
    trace = BenignTrace(seed, channel, tuple(simulation.network.sensors), tuple(simulation.network.sinks), float(simulation.env.now), events)
    directory.mkdir(parents=True, exist_ok=False)
    files = [save_csv(pd.DataFrame(events, columns=['event', 'time_s', 'relay_id', 'packet_id', 'source_id']), directory / 'observations.csv'), save_json(simulation.summary(), directory / 'physical_summary.json')]
    manifest_path = directory / 'run_manifest.json'
    manifest = create_run_manifest(config, [*files, manifest_path], root)
    coordinates = simulation.network.coordinates()
    manifest.update({'coordinates': coordinates, 'physical_edges': sorted((sorted(edge) for edge in simulation.network.graph.edges)), 'topology_hash': json_digest(coordinates), 'observation_model': ForwardingDetector.model_metadata(), 'observer_projection': ['event', 'time_s', 'relay_id', 'packet_id', 'source_id'], 'observer_success': 'relay_tx_started_not_next_hop_ack', 'passive_replay': True, 'routing_avoidance_enabled': False, 'actual_duration_s': trace.end_time_s, 'wall_clock_s': perf_counter() - started, 'attacker_ids': [], 'attack_enabled': False})
    save_json(manifest, manifest_path)
    return trace

def verify_freeze(config_path: Path, root: Path) -> dict:
    lock_path = config_path.with_suffix('.lock.json')
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    if hashlib.sha256(config_path.read_bytes()).hexdigest() != lock['config_file_sha256']:
        raise ValueError('frozen detector file changed')
    if source_fingerprint(root)['sha256'] != lock['source_fingerprint']['sha256']:
        raise ValueError('source changed since calibration; recalibration is required')
    validate_protocol(lock['protocol'])
    if json_digest(lock['protocol']) != lock['protocol_sha256'] or not lock['benign_validation_passed']:
        raise ValueError('invalid calibration lock')
    if json_digest(lock['simulation_configuration']) != lock['simulation_config_sha256']:
        raise ValueError('simulation basis changed in calibration lock')
    config = DetectorConfig(**json.loads(config_path.read_text(encoding='utf-8')))
    if config.calibration_status != 'CALIBRATED' or asdict(config) != lock['detector_parameters']:
        raise ValueError('detector does not match its frozen parameters')
    if lock['protocol']['version'] == 'long_horizon_benign_v1':
        evidence_path = (root / lock['validation_evidence_path']).resolve()
        if not evidence_path.is_relative_to(root.resolve()):
            raise ValueError('validation evidence must stay within the project')
        if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != lock['validation_evidence_sha256']:
            raise ValueError('long-horizon validation evidence changed')
        evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
        expected_parameters = {**asdict(config), 'calibration_status': 'TEST_ONLY'}
        if not evidence['benign_passed'] or not evidence['attack_passed'] or evidence['protocol_sha256'] != lock['protocol_sha256'] or (evidence['parameters'] != expected_parameters) or (evidence['source_sha256'] != lock['source_fingerprint']['sha256']):
            raise ValueError('long-horizon validation gates or provenance do not match')
    return {'verified': True, 'config': str(config_path), 'lock': str(lock_path), 'config_file_sha256': lock['config_file_sha256'], 'scope': lock['scope']}

def run_calibration(root: Path, protocol_path: Path, output_root: Path, freeze_path: Path | None=None, config_path: Path | None=None) -> dict:
    protocol = json.loads(protocol_path.read_text(encoding='utf-8'))
    validate_protocol(protocol)
    plan = SimulationConfig.from_json(config_path or root / 'configs/plan.json')
    if protocol['duration_s'] > plan.max_duration_s:
        raise ValueError('calibration duration exceeds configured simulation limit')
    if freeze_path is not None and (freeze_path.exists() or freeze_path.with_suffix('.lock.json').exists()):
        raise FileExistsError('freeze destination already exists; choose a new path')
    directory = create_run_directory(output_root, 'stage4_calibration')
    fingerprint = source_fingerprint(root)
    status = {'expected_benign_runs': 3 * (len(protocol['seed_partitions']['calibration_fit']) + len(protocol['seed_partitions']['benign_validation'])), 'completed_benign_runs': 0, 'failed_runs': [], 'evaluation_runs': 0, 'attack_validation_runs': 0, 'status': 'RUNNING'}
    save_json(protocol, directory / 'protocol.json')
    save_json({'protocol_sha256': json_digest(protocol), 'source_fingerprint': fingerprint, 'selection_before_validation': True}, directory / 'preregistration.json')
    save_json(status, directory / 'run_status.json')
    candidate_rows, candidates, references = ([], [], [])
    current_run = None
    try:

        def collect(phase):
            nonlocal current_run
            traces = []
            for seed in protocol['seed_partitions'][phase]:
                for channel in protocol['channel_loss_probabilities']:
                    current_run = {'phase': phase, 'seed': seed, 'channel_loss_probability': channel}
                    name = f'seed_{seed}_channel_{channel:g}'
                    trace = _capture_trace(plan, seed, channel, directory / phase / name, root, protocol['duration_s'])
                    traces.append(trace)
                    status['completed_benign_runs'] += 1
                    save_json(status, directory / 'run_status.json')
                    print(f"{phase}: {status['completed_benign_runs']}/{status['expected_benign_runs']}, seed={seed}, p_channel={channel:g}", flush=True)
            current_run = None
            return traces
        fit = collect('calibration_fit')
        for index, structure in enumerate(protocol['structural_grid'], 1):
            reference_config = detector_parameters(protocol, structure, 0)
            samples = []
            for trace in fit:
                detector = replay_trace(trace, reference_config)
                samples.extend(({'seed': trace.seed, 'channel_loss_probability': trace.channel_loss_probability, 'relay_id': row['relay_id'], 'window_end_s': row['window_end_s'], 'observations': row['observations'], 'forwarded': row['forwarded'], 'forwarding_ratio': row['forwarding_ratio']} for row in detector.windows if row['status'] == 'valid'))
            quantile = linear_quantile([row['forwarding_ratio'] for row in samples], protocol['tau_quantile'])
            references.append({'reference_id': f'reference_{index:02d}', 'purpose': 'FR_quantile_only_tau_zero_not_a_selected_detector', 'parameters': asdict(reference_config), 'valid_cohort_samples': len(samples), 'q05_pooled': quantile, 'q05_by_channel': {str(channel): linear_quantile([row['forwarding_ratio'] for row in samples if row['channel_loss_probability'] == channel], 0.05) for channel in protocol['channel_loss_probabilities']}})
            save_csv(pd.DataFrame(samples), directory / f'reference_{index:02d}_fr.csv')
            for offset_index, offset in enumerate(protocol['tau_offsets'], 1):
                candidate_id = f'candidate_{index:02d}_{offset_index}'
                if quantile is None:
                    candidates.append({'candidate_id': candidate_id, 'parameters': None, 'eligible': False, 'reason': 'no_valid_FR_samples', 'channels': []})
                    continue
                config = detector_parameters(protocol, structure, max(0, min(1, quantile + offset)))
                rows = []
                for trace in fit:
                    metrics = benign_metrics(replay_trace(trace, config))
                    row = {'phase': 'calibration_fit', 'candidate_id': candidate_id, 'seed': trace.seed, 'channel_loss_probability': trace.channel_loss_probability, **metrics}
                    rows.append(row)
                    candidate_rows.append(row)
                channels = aggregate_benign(rows)
                eligible = config.trust_threshold > 0 and acceptable(channels, protocol)
                candidates.append({'candidate_id': candidate_id, 'reference_id': f'reference_{index:02d}', 'tau_offset': offset, 'q05': quantile, 'parameters': asdict(config), 'channels': channels, 'eligible': eligible, 'reason': 'meets_empirical_fit_gate' if eligible else 'fails_FPR_coverage_or_positive_tau_gate'})
            print(f"grid: {index}/{len(protocol['structural_grid'])}, Q0.05={quantile}, candidates={len(candidates)}", flush=True)
        save_json({'references': references, 'candidates': candidates}, directory / 'all_configurations.json')
        save_csv(pd.DataFrame(candidate_rows), directory / 'fit_trials.csv')
        selected = select_candidate(candidates, protocol)
        selection = {'candidate': selected, 'selected_from': 'calibration_fit_only', 'benign_validation_seen': False, 'attack_validation_seen': False, 'evaluation_seen': False, 'protocol_sha256': json_digest(protocol)}
        save_json(selection, directory / 'selection_before_validation.json')
        print(f"Selected {selected['candidate_id']}; starting held-out benign validation without reselection.", flush=True)
        selected_config = DetectorConfig(**selected['parameters'])
        validation_rows = []
        for trace in collect('benign_validation'):
            detector = replay_trace(trace, selected_config)
            metrics = benign_metrics(detector)
            validation_rows.append({'phase': 'benign_validation', 'candidate_id': selected['candidate_id'], 'seed': trace.seed, 'channel_loss_probability': trace.channel_loss_probability, **metrics})
            save_detector_outputs(detector, directory / 'benign_validation' / f'seed_{trace.seed}_channel_{trace.channel_loss_probability:g}' / 'selected_detector')
        validation_channels = aggregate_benign(validation_rows)
        passed = acceptable(validation_channels, protocol)
        save_csv(pd.DataFrame(validation_rows), directory / 'benign_validation_trials.csv')
        report = {'stage': 4, 'protocol_sha256': json_digest(protocol), 'protocol': protocol, 'references': references, 'candidates': candidates, 'selected_candidate': selected, 'benign_validation_channels': validation_channels, 'benign_validation_passed': passed, 'selection_used_attacker_labels': False, 'selection_used_evaluation': False, 'reselected_after_validation': False, 'false_positive_reduction': 'NOT_DEMONSTRATED', 'optimality_claim': False, 'uncertainty': 'finite horizon and limited independent seeds; correlated node/window observations are not independent binomial trials; empirical FPR does not prove population FPR <=5%', 'observer_limitation': 'ideal TX observer; benign next-hop channel loss cannot by itself reduce relay forwarding ratio; no realistic overhearing/ACK loss calibration', 'reference_replays': len(references) * len(fit), 'fit_candidate_trials': len(candidate_rows), 'benign_validation_trials': len(validation_rows), 'evaluation_runs': 0, 'attack_validation_runs': 0, 'output_directory': str(directory), 'frozen': False}
        if passed:
            frozen_config = replace(selected_config, calibration_status='CALIBRATED')
            frozen_path = freeze_path or directory / 'detector_frozen.json'
            frozen_path.parent.mkdir(parents=True, exist_ok=True)
            lock = {'stage': 4, 'scope': protocol['scope'], 'protocol': protocol, 'protocol_sha256': json_digest(protocol), 'source_fingerprint': fingerprint, 'detector_parameters': asdict(frozen_config), 'simulation_configuration': plan.to_dict(), 'simulation_config_sha256': json_digest(plan.to_dict()), 'selected_candidate_id': selected['candidate_id'], 'selection_report': str(directory / 'selection_before_validation.json'), 'benign_validation_passed': True, 'validation_channels': validation_channels, 'evaluation_runs_before_freeze': 0, 'attack_validation_runs': 0, 'false_positive_reduction': 'NOT_DEMONSTRATED', 'human_review': 'PENDING_USER_SELF_REVIEW_NO_NAMES_REQUIRED', 'calibration_report': str(directory / 'calibration_report.json')}
            payload = json.dumps(asdict(frozen_config), ensure_ascii=False, indent=2) + '\n'
            lock['config_file_sha256'] = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            with frozen_path.open('x', encoding='utf-8', newline='\n') as handle:
                handle.write(payload)
            with frozen_path.with_suffix('.lock.json').open('x', encoding='utf-8') as handle:
                json.dump(lock, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.write('\n')
            report['frozen'] = True
            report['freeze_verification'] = verify_freeze(frozen_path, root)
        save_json(report, directory / 'calibration_report.json')
        status['status'] = 'COMPLETE' if passed else 'VALIDATION_REJECTED_NO_FREEZE'
        status['pending_benign_runs'] = status['expected_benign_runs'] - status['completed_benign_runs']
        save_json(status, directory / 'run_status.json')
        manifest_path = directory / 'run_manifest.json'
        manifest = create_run_manifest(plan, [*sorted(directory.rglob('*.*')), manifest_path], root)
        manifest.update({'stage': 4, 'protocol_sha256': json_digest(protocol), 'source_fingerprint': fingerprint, 'seed_partitions': protocol['seed_partitions'], 'evaluation_runs': 0, 'frozen': report['frozen']})
        save_json(manifest, manifest_path)
        print(f"output_directory={directory}\nfrozen={report['frozen']}", flush=True)
        return report
    except Exception as error:
        status['status'] = 'FAILED'
        status['failed_runs'].append({'run': current_run, 'error': f'{type(error).__name__}: {error}'})
        status['pending_benign_runs'] = status['expected_benign_runs'] - status['completed_benign_runs']
        save_json(status, directory / 'run_status.json')
        save_json({'references': references, 'candidates': candidates}, directory / 'all_configurations.json')
        raise

def main() -> None:
    root = DEFAULT_CONFIG_PATH.parents[1]
    parser = ArgumentParser()
    parser.add_argument('--protocol', type=Path, default=root / 'configs/calibration_protocol.json')
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument('--output', type=Path, default=root / 'results/runs')
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--verify-freeze', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.verify_freeze:
        print(json.dumps(verify_freeze(args.verify_freeze.resolve(), root), indent=2))
        return
    protocol = json.loads(args.protocol.read_text(encoding='utf-8'))
    validate_protocol(protocol)
    if args.dry_run:
        fit_runs = 3 * len(protocol['seed_partitions']['calibration_fit'])
        validation_runs = 3 * len(protocol['seed_partitions']['benign_validation'])
        print(json.dumps({'protocol_sha256': json_digest(protocol), 'source_fingerprint': source_fingerprint(root), 'benign_simulations': fit_runs + validation_runs, 'quantile_reference_replays': len(protocol['structural_grid']) * fit_runs, 'candidate_configurations': len(protocol['structural_grid']) * len(protocol['tau_offsets']), 'fit_candidate_trials': fit_runs * len(protocol['structural_grid']) * len(protocol['tau_offsets']), 'selected_validation_trials': validation_runs, 'evaluation_runs': 0, 'attack_validation_runs': 0, 'seed_partitions': protocol['seed_partitions'], 'selection_order': SELECTION_ORDER}, indent=2))
        return
    report = run_calibration(root, args.protocol.resolve(), args.output.resolve(), args.freeze.resolve() if args.freeze else None, args.config.resolve())
    if not report['frozen']:
        raise SystemExit(1)
if __name__ == '__main__':
    main()
