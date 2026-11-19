from argparse import ArgumentParser
from collections import Counter
from dataclasses import replace
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter, sleep
from wsn_sim.calibration import json_digest
from wsn_sim.config import DEFAULT_CONFIG_PATH, SimulationConfig
from wsn_sim.experiment_execution import atomic_json, coordinator_lock, execute_worker, valid_completion
from wsn_sim.experiment_plan import PILOT_SEEDS, build_plan, choose_range, definitions, parse_seeds, verify_plan
from wsn_sim.network import Network
from wsn_sim.storage import create_run_directory, save_json

def progress(plan, state):
    entries = list(state['runs'].values())
    completed = sum((entry['status'] == 'COMPLETE' for entry in entries))
    failed = sum((entry['status'] in {'FAILED', 'TIMEOUT'} for entry in entries))
    return {'expected': len(plan['jobs']), 'completed': completed, 'failed': failed, 'pending': len(plan['jobs']) - completed - failed, 'running': sum((entry['status'] == 'RUNNING' for entry in entries))}

def run_batch(plan, directory, root, *, workers=6, retries=1, timeout_s=3600, time_budget_s=None):
    verify_plan(plan, root)
    cap = max(1, min(12, (os.cpu_count() or 2) - 2))
    if not 1 <= workers <= cap or retries < 0 or timeout_s <= 0:
        raise ValueError(f'workers must be 1..{cap}, retries nonnegative, timeout positive')
    directory.mkdir(parents=True, exist_ok=True)
    with coordinator_lock(directory):
        checkpoint = directory / 'checkpoint.json'
        state = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {'plan_hash': plan['plan_hash'], 'runs': {}, 'attempts': []}
        if state['plan_hash'] != plan['plan_hash']:
            raise ValueError('checkpoint plan hash mismatch')
        queue, session_attempts = ([], Counter())
        for spec in plan['jobs']:
            entry = state['runs'].get(spec['run_id'])
            if entry and entry['status'] == 'COMPLETE' and valid_completion(Path(entry['directory']), spec):
                continue
            if entry:
                state['attempts'].append({**entry, 'status': 'INVALIDATED_OR_INCOMPLETE_ON_RESUME'})
            queue.append(spec)
            state['runs'][spec['run_id']] = {'status': 'PENDING'}
        atomic_json(checkpoint, state)
        running = {}
        started = last_status = perf_counter()
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        try:
            while queue or running:
                budget_expired = time_budget_s is not None and perf_counter() - started >= time_budget_s
                while queue and len(running) < workers and (not budget_expired):
                    spec = queue.pop(0)
                    session_attempts[spec['run_id']] += 1
                    job_dir = directory / 'runs' / spec['case']['case_id'] / f"seed_{spec['seed']}"
                    job_dir.mkdir(parents=True, exist_ok=True)
                    previous = [int(path.name.split('_')[-1]) for path in job_dir.glob('attempt_*') if path.is_dir()]
                    attempt = job_dir / f'attempt_{max(previous, default=0) + 1:04d}'
                    attempt.mkdir(exist_ok=False)
                    save_json({**spec, 'timeout_s': timeout_s}, attempt / 'spec.json')
                    stdout, stderr = [(attempt / name).open('w', encoding='utf-8') for name in ('stdout.log', 'stderr.log')]
                    command = [sys.executable, str(root / 'scripts/run_experiments.py'), '_worker', '--spec', str(attempt / 'spec.json'), '--output', str(attempt)]
                    process = subprocess.Popen(command, cwd=root, env=environment, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    running[process.pid] = (process, spec, attempt, perf_counter(), stdout, stderr)
                    state['runs'][spec['run_id']] = {'status': 'RUNNING', 'directory': str(attempt), 'pid': process.pid}
                    atomic_json(checkpoint, state)
                for pid, item in list(running.items()):
                    process, spec, attempt, submitted, stdout, stderr = item
                    timed_out = perf_counter() - submitted > timeout_s
                    if timed_out and process.poll() is None:
                        process.terminate()
                        process.wait(timeout=20)
                    if process.poll() is None:
                        continue
                    stdout.close()
                    stderr.close()
                    good = process.returncode == 0 and valid_completion(attempt, spec)
                    entry = {'run_id': spec['run_id'], 'status': 'COMPLETE' if good else 'TIMEOUT' if timed_out else 'FAILED', 'directory': str(attempt), 'exit_code': process.returncode, 'coordinator_wall_s': perf_counter() - submitted}
                    state['attempts'].append(dict(entry))
                    state['runs'][spec['run_id']] = dict(entry)
                    if not good and session_attempts[spec['run_id']] <= retries:
                        queue.append(spec)
                        state['runs'][spec['run_id']]['status'] = 'PENDING'
                    running.pop(pid)
                    atomic_json(checkpoint, state)
                if perf_counter() - last_status >= 10:
                    print(json.dumps({**progress(plan, state), 'elapsed_s': round(perf_counter() - started, 1)}), flush=True)
                    last_status = perf_counter()
                if budget_expired and (not running):
                    break
                sleep(0.2)
        finally:
            for process, spec, attempt, submitted, stdout, stderr in running.values():
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=20)
                stdout.close()
                stderr.close()
                state['runs'][spec['run_id']] = {'status': 'INTERRUPTED', 'directory': str(attempt)}
            counts = progress(plan, state)
            state['status'] = 'COMPLETE' if counts['completed'] == counts['expected'] else 'FAILED_OR_PENDING'
            state['counts'] = counts
            state['last_session_wall_s'] = perf_counter() - started
            atomic_json(checkpoint, state)
        print(json.dumps({**counts, 'directory': str(directory), 'status': state['status']}), flush=True)
        return state

def create_pilot(root, output, detector_file, duration_s=None, workers=2):
    directory = create_run_directory(output, 'stage7_pilot')
    base = SimulationConfig.from_json(root / 'configs/plan.json')
    rows = []
    for seed in PILOT_SEEDS:
        for radius in (250, 300, 350):
            network = Network(replace(base, seed=seed, communication_range_m=radius))
            reachable = len(network.routable_sensor_ids())
            rows.append({'seed': seed, 'communication_range_m': radius, 'routable_sensors': reachable, 'sensors': base.num_sensors, 'routable_fraction': reachable / base.num_sensors, 'isolated_sensors': len(network.isolated_sensor_ids()), 'topology_hash': json_digest(network.coordinates())})
    with (directory / 'reachability.csv').open('x', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    selection = choose_range(rows)
    save_json(selection, directory / 'range_selection.json')
    values = json.loads(detector_file.read_text(encoding='utf-8'))
    values['calibration_status'] = 'TEST_ONLY'
    pilot_detector = save_json(values, directory / 'pilot_detector.json')
    base = replace(base, communication_range_m=selection['selected_range_m'], channel_loss_probability=0.01)
    cases = definitions(core_only=True)
    plan = build_plan(root, base, pilot_detector, [45001], cases, test_only=True)
    for job in plan['jobs']:
        job['scope'] = 'PILOT_ONLY_NOT_EVALUATION'
        if duration_s is not None:
            job['pilot_duration_s'] = duration_s
        body = dict(job)
        body.pop('run_id')
        job['run_id'] = json_digest(body)[:24]
    plan.pop('plan_hash')
    plan['plan_hash'] = json_digest(plan)
    save_json(plan, directory / 'plan.json')
    state = run_batch(plan, directory, root, workers=workers)
    costs = []
    for entry in state['runs'].values():
        if entry['status'] != 'COMPLETE':
            continue
        attempt = Path(entry['directory'])
        manifest = json.loads((attempt / 'run_manifest.json').read_text(encoding='utf-8'))
        summary = json.loads((attempt / 'summary.json').read_text(encoding='utf-8'))
        costs.append({'scenario': manifest['case']['scenario'], 'wall_s': entry['coordinator_wall_s'], 'peak_working_set_bytes': manifest['peak_working_set_bytes'], 'output_bytes': sum((path.stat().st_size for path in attempt.iterdir() if path.is_file())), 'actual_duration_s': summary['time_s'], 'stop_reason': summary['stop_reason'], 'lifetime': summary['lifetime']})
    result = {'range_selection': selection, 'runtime_measurements': costs, 'counts': progress(plan, state), 'evaluation_runs': 0, 'output_directory': str(directory)}
    save_json(result, directory / 'pilot_report.json')
    print(json.dumps(result, indent=2))
    return result

def main():
    root = DEFAULT_CONFIG_PATH.parents[1]
    parser = ArgumentParser()
    subparsers = parser.add_subparsers(dest='mode', required=True)
    for name in ('dry-run', 'batch'):
        item = subparsers.add_parser(name)
        item.add_argument('--config', type=Path, default=root / 'configs/experiment_plan.json')
        item.add_argument('--detector', type=Path, default=root / 'configs/detector_stage78.json')
        item.add_argument('--seeds', default='51001:51030')
        item.add_argument('--output', type=Path, default=root / 'results/runs')
        item.add_argument('--placements', nargs='+', default=['random'])
        item.add_argument('--rhos', type=float, nargs='+', default=[0.02, 0.05, 0.1])
        item.add_argument('--p-drops', type=float, nargs='+', default=[0.25, 0.5, 0.75])
        item.add_argument('--sample-interval', type=float, default=100)
        for flag in ('core-only', 'test-only', 'full-trace'):
            item.add_argument('--' + flag, action='store_true')
        item.add_argument('--explicit-ids', nargs='*')
        item.add_argument('--workers', type=int, default=6)
        item.add_argument('--retries', type=int, default=1)
        item.add_argument('--timeout', type=float, default=3600)
        item.add_argument('--time-budget', type=float)
    resume = subparsers.add_parser('resume')
    resume.add_argument('directory', type=Path)
    resume.add_argument('--workers', type=int, default=6)
    resume.add_argument('--retries', type=int, default=1)
    resume.add_argument('--timeout', type=float, default=3600)
    resume.add_argument('--time-budget', type=float)
    pilot = subparsers.add_parser('pilot')
    pilot.add_argument('--output', type=Path, default=root / 'results/runs')
    pilot.add_argument('--detector', type=Path, default=root / 'configs/detector_stage56.json')
    pilot.add_argument('--duration', type=float)
    pilot.add_argument('--workers', type=int, default=2)
    worker = subparsers.add_parser('_worker')
    worker.add_argument('--spec', type=Path, required=True)
    worker.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == '_worker':
        execute_worker(json.loads(args.spec.read_text(encoding='utf-8')), args.output, root)
    elif args.mode == 'pilot':
        create_pilot(root, args.output, args.detector, args.duration, args.workers)
    elif args.mode == 'resume':
        plan = json.loads((args.directory / 'plan.json').read_text(encoding='utf-8'))
        run_batch(plan, args.directory, root, workers=args.workers, retries=args.retries, timeout_s=args.timeout, time_budget_s=args.time_budget)
    else:
        base = SimulationConfig.from_json(args.config)
        cases = definitions(args.rhos, args.p_drops, args.placements, args.core_only)
        plan = build_plan(root, base, args.detector.resolve(), parse_seeds(args.seeds), cases, test_only=args.test_only, sample_interval_s=args.sample_interval, full_trace=args.full_trace, explicit_ids=args.explicit_ids)
        if args.mode == 'dry-run':
            print(json.dumps({'configurations': len(cases), 'seeds_per_configuration': len(plan['seeds']), 'expected_runs': plan['expected_runs'], 'source_sha256': plan['source_fingerprint']['sha256'], 'plan_hash': plan['plan_hash'], 'scope': plan['scope'], 'max_rounds': base.max_rounds, 'horizon_s': base.max_duration_s, 'cases': cases, 'seeds': plan['seeds'], 'pending_extensions': plan['extension_pending']}, indent=2))
        else:
            directory = create_run_directory(args.output, 'stage7_batch')
            save_json(plan, directory / 'plan.json')
            diff = subprocess.run(['git', 'diff', '--binary'], cwd=root, check=True, capture_output=True).stdout
            (directory / 'source_diff.patch').write_bytes(diff)
            save_json({'sha256': hashlib.sha256(diff).hexdigest(), 'command': sys.argv}, directory / 'invocation.json')
            run_batch(plan, directory, root, workers=args.workers, retries=args.retries, timeout_s=args.timeout, time_budget_s=args.time_budget)
if __name__ == '__main__':
    main()
