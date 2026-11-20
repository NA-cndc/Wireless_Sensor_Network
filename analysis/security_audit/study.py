from __future__ import annotations
from argparse import ArgumentParser
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, replace
from datetime import datetime, timezone
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import sys
from time import perf_counter
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from wsn_sim.calibration import json_digest, source_fingerprint, verify_freeze
from wsn_sim.config import DetectorConfig, SimulationConfig
from wsn_sim.detection import ForwardingDetector
from wsn_sim.evaluation import security_metrics
from wsn_sim.recording import RunRecorder
from wsn_sim.simulation import Simulation

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')

def csv_write(path, rows):
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def protocol():
    return {'version': 'long_horizon_benign_v1', 'duration_s': 10000.0, 'channel_loss_probabilities': [0, 0.01, 0.05], 'seed_partitions': {'calibration_fit': list(range(171001, 171007)), 'benign_validation': list(range(172001, 172005)), 'attack_validation_reserved': list(range(173001, 173005)), 'evaluation_reserved': list(range(174001, 174031))}, 'grid': {'window_size_s': [20, 40, 80], 'min_observations': [2, 5, 10], 'beta_trust': [0.5, 0.8], 'trust_threshold': [0.7, 0.8, 0.9, 0.95], 'consecutive_bad_windows': [1, 2, 3]}, 'fixed': {'forwarding_timeout_s': 0.02, 'initial_trust': 1.0, 'isolation_duration_s': 60.0, 'calibration_status': 'TEST_ONLY'}, 'observation_model': 'ideal_observer_deadline_cohorts_v1', 'routing_algorithm': 'EMHR', 'prediction': 'ever_suspected_by_cutoff_all_sensors', 'max_empirical_fpr': 0.05, 'max_empirical_conditional_fpr': 0.05, 'min_seed_coverage': 0.2, 'selection_order': ['highest_tau_within_fpr_budget', 'lowest_worst_conditional_fpr', 'highest_min_seed_coverage', 'K_closest_to_2', 'shortest_window', 'candidate_id'], 'K_policy': 'K controls isolation only; suspicion FPR must not be claimed to improve from K alone', 'attack_validation': {'rho': 0.05, 'p_drop_values': [0.25, 0.5, 0.75], 'channel_loss_probability': 0.01, 'min_conditional_tpr': 0.5, 'min_unconditional_tpr': 0.3, 'max_mean_capped_detection_delay_s': 5000}, 'validation_policy': 'fit selection saved before validation; reject without reselection on any gate failure', 'evaluation_policy': 'freeze before evaluation; 30 new matched seeds; no evaluation tuning', 'independent_unit': 'seed', 'FPR_scope': 'ever_suspected over 10000s, not instantaneous', 'overhead_policy': 'ideal observer retains NA; parameterized counterfactual estimates reported separately without battery feedback', 'original_plan_horizon': '10000 rounds = 100000s; this study is a separate 10000s audit'}

def register(out, original):
    if (out / 'protocol.json').exists():
        if read(out / 'protocol.json') != protocol():
            raise ValueError('registered protocol changed')
        return
    used = set()
    examined = []
    patterns = ['configs/*.json', 'results/**/plan.json', 'results/**/*protocol*.json', 'results/**/spec.json']

    def walk(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, int) and (not isinstance(value, bool)) and ('seed' in key or key in {'calibration_fit', 'benign_validation', 'attack_validation_reserved', 'evaluation_reserved'}):
            used.add(value)
    for pattern in patterns:
        for p in original.glob(pattern):
            try:
                walk(read(p))
                examined.append(str(p))
            except (OSError, ValueError):
                raise RuntimeError(f'could not inventory seed file {p}')
    proposed = set(itertools.chain.from_iterable(protocol()['seed_partitions'].values()))
    if proposed & used:
        raise ValueError(f'new seeds already used: {proposed & used}')
    out.mkdir(parents=True, exist_ok=True)
    write(out / 'seed_inventory.json', {'files_examined': examined, 'existing_seeds': sorted(used), 'proposed_seeds': sorted(proposed), 'overlap': []})
    write(out / 'protocol.json', protocol())
    write(out / 'registration.json', {'registered_at_utc': datetime.now(timezone.utc).isoformat(), 'protocol_sha256': json_digest(protocol()), 'source_fingerprint': source_fingerprint(ROOT), 'analysis_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'original_project': str(original), 'new_simulations_before_registration': 0})

class AuditRecorder(RunRecorder):

    def __init__(self, directory, sensors, *, collect=False, full=False, old_observer=None):
        super().__init__(directory, full_trace=full)
        self.ids = tuple(sorted(sensors))
        self.index = {node: i for i, node in enumerate(self.ids)}
        self.collect = collect
        self.rows = []
        self.active = {}
        self.old_observer = old_observer
        self.failure_reasons = Counter()
        self.timeout_context = {}
        self.diagnostic_rows = []
        self.simulation = None

    def emit(self, name, row):
        super().emit(name, row)
        if name == 'packet_events':
            kind, node, packet, source = (row['event'], row['node_id'], row['packet_id'], row['source_id'])
            eligible = node in self.index and node != source
            if kind in {'rx', 'tx'} and self.old_observer is not None:
                if kind == 'rx':
                    self.old_observer.observe_received(node, packet, source, row['time_s'])
                else:
                    self.old_observer.observe_forwarded(node, packet, row['time_s'], source_id=source)
            if self.collect and eligible:
                key = (node, packet)
                if kind == 'rx':
                    self.active[key] = len(self.rows)
                    self.rows.append([self.index[node], row['time_s'], math.nan])
                elif kind == 'tx' and key in self.active:
                    self.rows[self.active.pop(key)][2] = row['time_s']
            if kind == 'dropped':
                self.failure_reasons[row['reason']] += 1
                if self.simulation is not None and eligible:
                    sensor = self.simulation.network.sensors[node]
                    self.timeout_context[node, packet] = {'drop_time_s': row['time_s'], 'physical_drop_reason': row['reason'], 'energy_j_at_drop': sensor.energy_j, 'alive_at_drop': sensor.is_alive, 'energy_stage': row.get('energy_stage')}
        elif name == 'detector_events' and row['event'] == 'timeout':
            self.diagnostic_rows.append({**row, **self.timeout_context.pop((row['relay_id'], row['packet_id']), {})})

    def save_projection(self):
        if self.collect:
            data = np.asarray(self.rows, dtype=float).reshape((-1, 3))
            np.savez_compressed(self.directory / 'observations.npz', relay=data[:, 0].astype(np.int16), rx=data[:, 1], tx=data[:, 2], sensor_ids=np.asarray(self.ids))
        if self.diagnostic_rows:
            columns = sorted(set().union(*(r.keys() for r in self.diagnostic_rows)))
            csv_write(self.directory / 'timeout_causes.csv', [{k: r.get(k) for k in columns} for r in self.diagnostic_rows])

def run_job(job):
    out = Path(job['directory'])
    if (out / 'complete.json').exists():
        complete = read(out / 'complete.json')
        if complete['job_hash'] != json_digest(job):
            raise ValueError('job changed on resume')
        if all((hashlib.sha256((out / name).read_bytes()).hexdigest() == digest for name, digest in complete['files'].items())):
            return {'directory': str(out), 'reused': True}
        raise ValueError('completed result hash changed')
    out.mkdir(parents=True, exist_ok=True)
    write(out / 'job.json', job)
    started = perf_counter()
    base = SimulationConfig.from_json(ROOT / 'configs/experiment_plan.json')
    params = None if job.get('detector') is None else DetectorConfig(**job['detector'])
    cfg = replace(base, seed=job['seed'], max_rounds=1000, config_profile='CUSTOM', routing_algorithm=job.get('algorithm', 'EMHR'), detector=params, attacker_ids=() if job.get('rho', 0) == 0 else None, attacker_ratio=job.get('rho', 0), p_drop=job.get('p_drop', 0), attacker_selection='random', channel_loss_probability=job['channel'])
    ids = [f'sensor_{i:03d}' for i in range(450)]
    old = None
    if job.get('paired_old'):
        old = ForwardingDetector(DetectorConfig(**read(ROOT / 'configs/detector_stage78.json')), ids, retain_history=False)
    recorder = AuditRecorder(out, ids, collect=job.get('collect', False), full=job.get('full_trace', False), old_observer=old)
    simulation = Simulation(cfg, recorder=recorder)
    recorder.simulation = simulation
    coordinates = simulation.network.coordinates()
    for _ in range(100):
        if simulation.stop_event.triggered:
            break
        simulation.run_for(100)
        recorder.snapshot(simulation)
    summary = simulation.summary()
    if old:
        old.advance(summary['time_s'])
        write(out / 'paired_old_security.json', security_metrics(simulation.network.sensors, simulation.traffic_gen.attack.attacker_ids, old, summary['time_s']))
        write(out / 'paired_old_detector.json', old.summary())
    recorder.close()
    recorder.save_projection()
    if not summary['performance']['conservation_ok'] or not summary['performance']['energy_conservation_ok']:
        raise RuntimeError('packet or energy conservation failed')
    if summary['detector'] and (not summary['detector']['conservation_ok']):
        raise RuntimeError('detector conservation failed')
    write(out / 'summary.json', summary)
    write(out / 'configuration.json', cfg.to_dict())
    write(out / 'topology.json', {'coordinates': coordinates, 'edges': sorted((sorted(e) for e in simulation.network.graph.edges))})
    write(out / 'run_manifest.json', {'source_fingerprint': source_fingerprint(ROOT), 'job_hash': json_digest(job), 'wall_clock_s': perf_counter() - started, 'horizon_s': summary['time_s'], 'stream_seeds': cfg.stream_seeds, 'attack': summary['attack'], 'projection': ['relay_id', 'rx_time_s', 'tx_time_s'], 'projection_contains_attack_labels': False, 'drop_reasons_for_posthoc_audit_only': dict(recorder.failure_reasons), 'observer_model': ForwardingDetector.model_metadata(), 'full_trace': recorder.full_trace})
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name != 'complete.json'}
    write(out / 'complete.json', {'job_hash': json_digest(job), 'files': files})
    return {'directory': str(out), 'seconds': perf_counter() - started}

def run_jobs(jobs, workers):
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_job, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            print(json.dumps({'completed': i, 'total': len(jobs), **result}), flush=True)

def make_jobs(out, phase, seeds, channels, detector=None, *, rho=0, p_drop=0, algorithm='EMHR', collect=False, paired_old=False):
    return [{'directory': str(out / phase / f'ch_{channel:g}' / f'seed_{seed}'), 'seed': seed, 'channel': channel, 'rho': rho, 'p_drop': p_drop, 'algorithm': algorithm, 'detector': detector, 'collect': collect, 'paired_old': paired_old} for channel in channels for seed in seeds]

def cohort_arrays(trace, window, timeout, horizon):
    rx, tx, relay = (trace['rx'], trace['tx'], trace['relay'])
    deadline = rx + timeout
    near_tx = np.isfinite(tx) & (np.abs(tx - deadline) < 1e-10)
    if near_tx.any():
        from decimal import Decimal
        for i in np.flatnonzero(near_tx):
            deadline[i] = float(Decimal(str(float(rx[i]))) + Decimal(str(timeout)))
    quotient = deadline / window
    cohort = np.floor(quotient).astype(np.int64)
    near = np.abs(quotient - np.rint(quotient)) < 1e-10
    if near.any():
        from decimal import Decimal
        for i in np.flatnonzero(near):
            cohort[i] = int((Decimal(str(float(rx[i]))) + Decimal(str(timeout))) // Decimal(str(window)))
    n_windows, n_nodes = (int(horizon // window), len(trace['sensor_ids']))
    eligible = (cohort >= 0) & (cohort < n_windows)
    n = np.zeros((n_windows, n_nodes), dtype=np.int64)
    f = np.zeros_like(n)
    np.add.at(n, (cohort[eligible], relay[eligible]), 1)
    success = eligible & np.isfinite(tx) & (tx < deadline)
    np.add.at(f, (cohort[success], relay[success]), 1)
    return (n, f)

def fast_prediction(n, f, params):
    trust = np.full(n.shape[1], params['initial_trust'], dtype=float)
    first = np.full(n.shape[1], np.nan)
    valid_count = np.zeros(n.shape[1], dtype=np.int64)
    for k in range(len(n)):
        valid = n[k] >= params['min_observations']
        valid_count += valid
        trust[valid] = params['beta_trust'] * trust[valid] + (1 - params['beta_trust']) * f[k, valid] / n[k, valid]
        newly = valid & (trust < params['trust_threshold']) & np.isnan(first)
        first[newly] = (k + 1) * params['window_size_s']
    return {'trust': trust, 'first': first, 'observable': valid_count > 0, 'valid_windows': valid_count}

def fit(out):
    p = read(out / 'protocol.json')
    grid = p['grid']
    candidates = [{**dict(zip(grid, values)), **p['fixed']} for values in itertools.product(*grid.values())]
    traces = [(path, dict(np.load(path))) for path in sorted((out / 'fit').rglob('observations.npz'))]
    if len(traces) != len(p['seed_partitions']['calibration_fit']) * 3:
        raise ValueError('incomplete fit traces')
    cache, rows = ({}, [])
    for index, params in enumerate(candidates):
        per_channel, coverages = (defaultdict(list), [])
        for path, trace in traces:
            key = (str(path), params['window_size_s'])
            if key not in cache:
                cache[key] = cohort_arrays(trace, params['window_size_s'], params['forwarding_timeout_s'], p['duration_s'])
            prediction = fast_prediction(*cache[key], params)
            predicted, observable = (np.isfinite(prediction['first']), prediction['observable'])
            coverage = float(observable.mean())
            coverages.append(coverage)
            channel = read(path.parent / 'job.json')['channel']
            per_channel[channel].append((float(predicted.mean()), float(predicted[observable].mean()) if observable.any() else 1.0))
        worst = max((float(np.mean([x[1] for x in values])) for values in per_channel.values()))
        all_fpr = max((float(np.mean([x[0] for x in values])) for values in per_channel.values()))
        rows.append({'candidate_id': f'c{index:03d}', **params, 'worst_channel_fpr': all_fpr, 'worst_channel_conditional_fpr': worst, 'min_seed_coverage': min(coverages), 'eligible': worst <= p['max_empirical_conditional_fpr'] and all_fpr <= p['max_empirical_fpr'] and (min(coverages) >= p['min_seed_coverage'])})
    csv_write(out / 'fit_candidates.csv', rows)
    eligible = [r for r in rows if r['eligible']]
    if not eligible:
        write(out / 'selection_before_validation.json', {'status': 'NO_ELIGIBLE_CANDIDATE', 'reselection_allowed': False})
        return
    winner = min(eligible, key=lambda r: (-r['trust_threshold'], r['worst_channel_conditional_fpr'], -r['min_seed_coverage'], abs(r['consecutive_bad_windows'] - 2), r['window_size_s'], r['candidate_id']))
    params = {key: winner[key] for key in asdict(DetectorConfig(**{**{key: winner[key] for key in grid}, **p['fixed']}))}
    write(out / 'selection_before_validation.json', {'selected_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'SELECTED_FIT_ONLY', 'protocol_sha256': json_digest(p), 'candidate': winner, 'parameters': params, 'validation_runs_before_selection': 0, 'evaluation_runs_before_selection': 0})
    print(json.dumps(winner), flush=True)

def main():
    parser = ArgumentParser()
    parser.add_argument('action', choices=['register', 'diagnose', 'capture-fit', 'fit'])
    parser.add_argument('--output', type=Path, default=ROOT / 'results/security_audit')
    parser.add_argument('--original', type=Path, default=Path('F:/bangdzaihjhj/dancctt'))
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    out = args.output.resolve()
    if args.action == 'register':
        register(out, args.original)
    elif args.action == 'diagnose':
        job = make_jobs(out, 'diagnostic_old_SF3', [51001], [0.01], read(ROOT / 'configs/detector_stage78.json'), rho=0.05, p_drop=0.5, algorithm='S_EMHR')[0]
        job['full_trace'] = True
        print(run_job(job), flush=True)
    elif args.action == 'capture-fit':
        p = read(out / 'protocol.json')
        run_jobs(make_jobs(out, 'fit', p['seed_partitions']['calibration_fit'], p['channel_loss_probabilities'], collect=True), args.workers)
    elif args.action == 'fit':
        fit(out)
if __name__ == '__main__':
    main()
