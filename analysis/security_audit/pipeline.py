from __future__ import annotations
from argparse import ArgumentParser
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
import numpy as np
from scipy.stats import t as student_t
sys.path.insert(0, str(Path(__file__).resolve().parent))
import study
from study import ROOT, read, write, csv_write, make_jobs, run_jobs
from wsn_sim.calibration import json_digest, source_fingerprint, verify_freeze
from wsn_sim.config import SimulationConfig, DetectorConfig
from wsn_sim.detection import ForwardingDetector

def source_guard(out):
    registration = read(out / 'registration.json')
    if source_fingerprint(ROOT) != registration['source_fingerprint']:
        raise ValueError('core source changed after registration; do not reuse calibration')
    if json_digest(read(out / 'protocol.json')) != registration['protocol_sha256']:
        raise ValueError('protocol changed after registration; do not reuse calibration')

def parameters(out):
    selection = read(out / 'selection_before_validation.json')
    if selection['status'] != 'SELECTED_FIT_ONLY':
        raise ValueError('no eligible candidate; do not select on validation')
    return selection['parameters']

def reference_replay(out, directory, params):
    trace = dict(np.load(directory / 'observations.npz'))
    ids = trace['sensor_ids'].tolist()
    events = []
    for i, (relay, rx, tx) in enumerate(zip(trace['relay'], trace['rx'], trace['tx'])):
        events.append((float(rx), 0, ids[int(relay)], f'projection_{i}'))
        if np.isfinite(tx):
            events.append((float(tx), 1, ids[int(relay)], f'projection_{i}'))
    detector = ForwardingDetector(DetectorConfig(**params), ids, retain_history=False)
    for when, kind, node, packet in sorted(events):
        if kind == 0:
            detector.observe_received(node, packet, 'outside_source', when)
        else:
            detector.observe_forwarded(node, packet, when, source_id='outside_source')
    detector.advance(10000)
    n, f = study.cohort_arrays(trace, params['window_size_s'], params['forwarding_timeout_s'], 10000)
    fast = study.fast_prediction(n, f, params)
    mismatch = []
    for i, node in enumerate(ids):
        state = detector.states[node]
        first = fast['first'][i]
        if not np.isclose(state.trust, fast['trust'][i], rtol=0, atol=1e-12) or state.valid_windows != int(fast['valid_windows'][i]) or state.suspected_at != (None if np.isnan(first) else float(first)):
            mismatch.append(node)
    result = {'trace_directory': str(directory), 'parameters': params, 'nodes_compared': len(ids), 'mismatch': mismatch, 'core_replay_conservation': detector.summary()['conservation_ok']}
    if mismatch:
        raise ValueError(f'accelerated fit projection disagrees with core detector: {mismatch}')
    return result

def validate(out, workers):
    source_guard(out)
    p, params = (read(out / 'protocol.json'), parameters(out))
    reference_paths = [next((out / 'fit' / f'ch_{ch:g}').glob('seed_*')) for ch in p['channel_loss_probabilities']]
    evidence = [reference_replay(out, path, params) for path in reference_paths]
    write(out / 'reference_replay_checks.json', {'checks': evidence, 'all_match': True})
    jobs = make_jobs(out, 'benign_validation', p['seed_partitions']['benign_validation'], p['channel_loss_probabilities'], params, paired_old=True)
    for drop in p['attack_validation']['p_drop_values']:
        jobs += make_jobs(out, f'attack_validation_drop_{drop:g}', p['seed_partitions']['attack_validation_reserved'], [0.01], params, rho=0.05, p_drop=drop, paired_old=True)
    write(out / 'validation_jobs.json', jobs)
    run_jobs(jobs, workers)
    benign, attack = ([], [])
    for channel in p['channel_loss_probabilities']:
        summaries = [read(out / 'benign_validation' / f'ch_{channel:g}' / f'seed_{seed}' / 'summary.json') for seed in p['seed_partitions']['benign_validation']]
        metrics = [s['security'] for s in summaries]
        row = {'channel': channel, 'runs': len(metrics), 'fpr': statistics.mean((s['fpr'] for s in metrics)), 'conditional_fpr': statistics.mean((s['conditional_on_observable']['fpr'] for s in metrics)), 'min_coverage': min((s['coverage'] for s in metrics)), 'FP': sum((s['FP'] for s in metrics))}
        row['passed'] = row['fpr'] <= p['max_empirical_fpr'] and row['conditional_fpr'] <= p['max_empirical_conditional_fpr'] and (row['min_coverage'] >= p['min_seed_coverage'])
        benign.append(row)
    gate = p['attack_validation']
    for drop in gate['p_drop_values']:
        summaries = [read(out / f'attack_validation_drop_{drop:g}' / 'ch_0.01' / f'seed_{seed}' / 'summary.json') for seed in p['seed_partitions']['attack_validation_reserved']]
        metrics = [s['security'] for s in summaries]
        delays = [min(v['detection_delay_s'], 10000) if v['detection_delay_s'] is not None else 10000 for s in metrics for v in s['attacker_delays'].values()]
        row = {'p_drop': drop, 'runs': len(metrics), 'tpr': statistics.mean((s['tpr'] for s in metrics)), 'conditional_tpr': statistics.mean((s['conditional_on_observable']['tpr'] for s in metrics)), 'mean_capped_delay_s': statistics.mean(delays)}
        row['passed'] = row['tpr'] >= gate['min_unconditional_tpr'] and row['conditional_tpr'] >= gate['min_conditional_tpr'] and (row['mean_capped_delay_s'] <= gate['max_mean_capped_detection_delay_s'])
        attack.append(row)
    result = {'created_at_utc': datetime.now(timezone.utc).isoformat(), 'source_sha256': source_fingerprint(ROOT)['sha256'], 'protocol_sha256': json_digest(p), 'parameters': params, 'benign': benign, 'attack': attack, 'benign_passed': all((r['passed'] for r in benign)), 'attack_passed': all((r['passed'] for r in attack)), 'selection_unchanged': read(out / 'selection_before_validation.json')['parameters'] == params, 'evaluation_runs_before_gate': 0, 'reselection_allowed': False}
    write(out / 'validation_gate.json', result)
    print(json.dumps(result), flush=True)

def freeze(out):
    source_guard(out)
    gate, p = (read(out / 'validation_gate.json'), read(out / 'protocol.json'))
    if not gate['benign_passed'] or not gate['attack_passed']:
        raise ValueError('validation failed; no calibrated freeze and no tuning on validation')
    path = ROOT / 'configs/detector_long_horizon_20261117.json'
    if path.exists():
        return verify_freeze(path, ROOT)
    params = {**parameters(out), 'calibration_status': 'CALIBRATED'}
    write(path, params)
    base = SimulationConfig.from_json(ROOT / 'configs/experiment_plan.json').to_dict()
    base.update({'max_rounds': 1000, 'config_profile': 'CUSTOM'})
    lock = {'stage': 'long_horizon_crosscheck', 'scope': '10000s empirical benign FPR gate plus independent attack validation; ideal observer; no real overhearing or lifetime guarantee', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'protocol': p, 'protocol_sha256': json_digest(p), 'source_fingerprint': source_fingerprint(ROOT), 'detector_parameters': params, 'simulation_configuration': base, 'simulation_config_sha256': json_digest(base), 'config_file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'benign_validation_passed': True, 'attack_validation_passed': True, 'validation_evidence_path': (out / 'validation_gate.json').relative_to(ROOT).as_posix(), 'validation_evidence_sha256': hashlib.sha256((out / 'validation_gate.json').read_bytes()).hexdigest(), 'evaluation_runs_before_freeze': 0}
    write(path.with_suffix('.lock.json'), lock)
    result = verify_freeze(path, ROOT)
    write(out / 'freeze_verification.json', result)
    print(json.dumps(result), flush=True)
    return result

def evaluation(out, workers):
    source_guard(out)
    path = ROOT / 'configs/detector_long_horizon_20261117.json'
    verify_freeze(path, ROOT)
    p, new = (read(out / 'protocol.json'), read(path))
    old = {**read(ROOT / 'configs/detector_stage78.json'), 'calibration_status': 'TEST_ONLY'}
    seeds = p['seed_partitions']['evaluation_reserved']
    jobs = make_jobs(out, 'eval_benign', seeds, p['channel_loss_probabilities'], new, paired_old=True)
    jobs += make_jobs(out, 'eval_SF2', seeds, [0.01], new, rho=0.05, p_drop=0.5, paired_old=True)
    for name, cfg in [('old', old), ('new', new)]:
        jobs += make_jobs(out, f'eval_SF3_{name}', seeds, [0.01], cfg, rho=0.05, p_drop=0.5, algorithm='S_EMHR')
    write(out / 'evaluation_jobs.json', jobs)
    run_jobs(jobs, workers)

def summarize(values):
    values = [float(v) for v in values if v is not None and math_isfinite(v)]
    if not values:
        return {'n': 0, 'mean': None, 'std': None, 'ci95_low': None, 'ci95_high': None}
    n = len(values)
    mean = statistics.mean(values)
    std = statistics.stdev(values) if n > 1 else None
    half = float(student_t.ppf(0.975, n - 1)) * std / n ** 0.5 if n > 1 else None
    return {'n': n, 'mean': mean, 'std': std, 'ci95_low': None if half is None else mean - half, 'ci95_high': None if half is None else mean + half}

def math_isfinite(value):
    import math
    return math.isfinite(float(value))

def flatten(directory, old=False):
    summary, job = (read(directory / 'summary.json'), read(directory / 'job.json'))
    security = read(directory / 'paired_old_security.json') if old else summary['security']
    detector = read(directory / 'paired_old_detector.json') if old else summary['detector']
    delays = list(security['attacker_delays'].values())
    observed = [v['detection_delay_s'] for v in delays if v['detection_delay_s'] is not None]
    return {'directory': str(directory.relative_to(ROOT)), 'seed': job['seed'], 'channel': job['channel'], 'treatment': 'old' if old or '_old' in directory.parts[-3] else 'new', **{k: security.get(k) for k in ['TP', 'FP', 'TN', 'FN', 'tpr', 'fpr', 'precision', 'f1', 'coverage']}, 'conditional_fpr': security['conditional_on_observable']['fpr'], 'conditional_tpr': security['conditional_on_observable']['tpr'], 'detection_delay_observed_mean_s': statistics.mean(observed) if observed else None, 'detection_delay_capped_mean_s': statistics.mean((v['detection_delay_s'] if v['detection_delay_s'] is not None else 10000 for v in delays)) if delays else None, 'detection_event_coverage': len(observed) / len(delays) if delays else None, 'suspected_current': sum((s['suspected'] for s in detector['relays'].values())), 'ever_suspected': sum((s['suspected_at'] is not None for s in detector['relays'].values())), 'isolated_current': sum((s['isolated_until'] is not None for s in detector['relays'].values())), 'ever_isolated': sum((s['isolated_at'] is not None for s in detector['relays'].values())), 'isolation_event_count': None if old else summary['performance']['security_overhead']['logical_state_events'].get('isolated', 0), 'pdr': summary['performance']['pdr'], 'goodput_bps': summary['performance']['goodput_bps'], 'monitoring_energy_j': summary['performance']['monitoring_energy_j'], 'valid_windows': sum((s['valid_windows'] for s in detector['relays'].values()))}

def report(out):
    source_guard(out)
    rows, suspects = ([], [])
    for phase in ['eval_benign', 'eval_SF2', 'eval_SF3_old', 'eval_SF3_new']:
        for path in sorted((out / phase).glob('ch_*/seed_*')):
            if not (path / 'complete.json').exists():
                raise ValueError(f'incomplete run {path}')
            r = flatten(path)
            r['group'] = phase.replace('_old', '').replace('_new', '')
            rows.append(r)
            job = read(path / 'job.json')
            if job['paired_old']:
                r = flatten(path, old=True)
                r['group'] = phase
                rows.append(r)
            summary = read(path / 'summary.json')
            for node, state in summary['detector']['relays'].items():
                if state['suspected'] or state['suspected_at'] is not None or state['isolated_until'] is not None:
                    suspects.append({'group': phase, 'seed': job['seed'], 'channel': job['channel'], 'node_id': node, **{k: state[k] for k in ['received_transit', 'forwarded', 'failed_timeout', 'pending', 'trust', 'suspected', 'suspected_at', 'isolated_until', 'isolated_at', 'valid_windows']}})
    csv_write(out / 'comparison_per_seed.csv', rows)
    csv_write(out / 'suspected_nodes.csv', suspects)
    grouped = defaultdict(list)
    for r in rows:
        grouped[r['group'], r['channel'], r['treatment']].append(r)
    metrics = ['fpr', 'conditional_fpr', 'tpr', 'conditional_tpr', 'precision', 'f1', 'coverage', 'detection_delay_observed_mean_s', 'detection_delay_capped_mean_s', 'detection_event_coverage', 'pdr', 'ever_suspected', 'ever_isolated', 'valid_windows']
    aggregate = []
    for (group, ch, treatment), values in grouped.items():
        if len(values) != 30 or len({v['seed'] for v in values}) != 30:
            raise ValueError('main configuration does not have 30 distinct seeds')
        for metric in metrics:
            aggregate.append({'group': group, 'channel': ch, 'treatment': treatment, 'metric': metric, **summarize((v[metric] for v in values))})
    csv_write(out / 'aggregate.csv', aggregate)
    pairs = []
    for group, channel in sorted({(g, c) for g, c, _ in grouped}):
        old = {v['seed']: v for v in grouped[group, channel, 'old']}
        new = {v['seed']: v for v in grouped[group, channel, 'new']}
        if set(old) != set(new):
            raise ValueError('unmatched comparison seeds')
        for metric in metrics:
            diffs = [new[s][metric] - old[s][metric] for s in old if new[s][metric] is not None and old[s][metric] is not None]
            pairs.append({'group': group, 'channel': channel, 'metric': metric, 'difference': 'new_minus_old', **summarize(diffs)})
    csv_write(out / 'paired_differences.csv', pairs)
    write(out / 'report_status.json', {'main_physical_runs': len(read(out / 'evaluation_jobs.json')), 'comparison_rows': len(rows), 'groups': len(grouped), 'independent_seeds_per_configuration': 30, 'source_sha256': source_fingerprint(ROOT)['sha256'], 'statistics': 'sample std ddof=1; Student-t CI95 over seed; paired differences on same seeds', 'calibration_source_unchanged': True, 'monitoring_costs': 'not dynamically modeled; parameterized estimate separate', 'evaluation_retuning': False})
    print(json.dumps({'physical_runs': len(read(out / 'evaluation_jobs.json')), 'rows': len(rows), 'aggregates': len(aggregate)}), flush=True)

def main():
    parser = ArgumentParser()
    parser.add_argument('action', choices=['validate', 'freeze', 'evaluate', 'report', 'verify-freeze'])
    parser.add_argument('--output', type=Path, default=ROOT / 'results/security_audit')
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.action == 'validate':
        validate(out, args.workers)
    elif args.action == 'freeze':
        freeze(out)
    elif args.action == 'evaluate':
        evaluation(out, args.workers)
    elif args.action == 'report':
        report(out)
    else:
        print(json.dumps(verify_freeze(ROOT / 'configs/detector_long_horizon_20261117.json', ROOT)))
if __name__ == '__main__':
    main()
