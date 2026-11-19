from collections import defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import tempfile
import zipfile
from scipy.stats import t
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from wsn_sim.calibration import source_fingerprint, verify_freeze, json_digest

def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))

def verify(out, source_root):
    errors = []
    hashed = 0
    classifiers = 0
    physical = 0
    paired = {}
    native_values = defaultdict(list)
    fingerprint = source_fingerprint(source_root)
    for complete_path in sorted(out.rglob('complete.json')):
        directory = complete_path.parent
        completion = read(complete_path)
        for name, digest in completion['files'].items():
            p = directory / name
            if not p.exists() and name.endswith('.jsonl') and ('diagnostic_old_SF3' in directory.parts):
                continue
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
                errors.append([str(directory.relative_to(ROOT)), name, 'hash'])
            hashed += 1
        summary = read(directory / 'summary.json')
        physical += 1
        manifest = read(directory / 'run_manifest.json')
        if manifest['source_fingerprint'] != fingerprint:
            errors.append([str(directory), 'source'])
        perf = summary['performance']
        if perf['generated'] != perf['delivered'] + perf['dropped'] + perf['pending_in_flight']:
            errors.append([str(directory), 'packet_conservation'])
        if sum(perf['drop_reasons'].values()) != perf['dropped']:
            errors.append([str(directory), 'drop_reasons'])
        for old in [False, True]:
            if old:
                if not (directory / 'paired_old_security.json').exists():
                    continue
                security = read(directory / 'paired_old_security.json')
                detector = read(directory / 'paired_old_detector.json')
            else:
                security, detector = (summary['security'], summary['detector'])
            if detector is None:
                continue
            population = set(detector['relays'])
            attackers = set(summary['attack']['attacker_ids'])
            predicted = {n for n, s in detector['relays'].items() if s['suspected_at'] is not None and s['suspected_at'] <= 10000}
            observable = {n for n, s in detector['relays'].items() if s['valid_windows'] > 0}
            expected = {'TP': len(predicted & attackers), 'FP': len(predicted - attackers), 'FN': len(attackers - predicted), 'TN': len(population - attackers - predicted)}
            if any((security[k] != v for k, v in expected.items())):
                errors.append([str(directory), 'classifier', old])
            if abs(security['fpr'] - expected['FP'] / (expected['FP'] + expected['TN'])) > 1e-12:
                errors.append([str(directory), 'FPR', old])
            if abs(security['coverage'] - len(observable) / 450) > 1e-12:
                errors.append([str(directory), 'coverage', old])
            for node, s in detector['relays'].items():
                if s['received_transit'] != s['forwarded'] + s['failed_timeout'] + s['pending']:
                    errors.append([str(directory), node, 'counters'])
            classifiers += 1
        job = read(directory / 'job.json')
        if 'eval_SF3_old' in directory.parts or 'eval_SF3_new' in directory.parts:
            key = job['seed']
            treatment = 'old' if 'eval_SF3_old' in directory.parts else 'new'
            paired.setdefault(key, {})[treatment] = (json_digest(read(directory / 'topology.json')), summary['stream_seeds'], summary['attack']['attacker_ids'])
    if len(paired) != 30 or any((set(v) != {'old', 'new'} or v['old'] != v['new'] for v in paired.values())):
        errors.append(['SF3_pairing'])
    per_seed = list(csv.DictReader((out / 'comparison_per_seed.csv').open(encoding='utf-8-sig', newline='')))
    groups = defaultdict(list)
    for row in per_seed:
        groups[row['group'], row['channel'], row['treatment']].append(row)
    aggregate = list(csv.DictReader((out / 'aggregate.csv').open(encoding='utf-8-sig', newline='')))
    for row in aggregate:
        values = [float(r[row['metric']]) for r in groups[row['group'], row['channel'], row['treatment']] if r[row['metric']]]
        if len(values) != int(row['n']):
            errors.append([row['metric'], 'n'])
        if not values:
            continue
        mean = statistics.mean(values)
        std = statistics.stdev(values)
        half = float(t.ppf(0.975, len(values) - 1)) * std / math.sqrt(len(values))
        for key, value in [('mean', mean), ('std', std), ('ci95_low', mean - half), ('ci95_high', mean + half)]:
            if not math.isclose(float(row[key]), value, rel_tol=1e-11, abs_tol=1e-12):
                errors.append([row['group'], row['metric'], key])
    if physical != 223:
        errors.append(['physical_count', physical])
    freeze = verify_freeze(ROOT / 'configs/detector_long_horizon_20261117.json', source_root)
    result = {'status': 'PASS' if not errors else 'FAIL', 'physical_runs_checked': physical, 'file_hashes_checked': hashed, 'classifier_instances_checked': classifiers, 'SF3_matched_seed_pairs': len(paired), 'aggregate_rows_recomputed': len(aggregate), 'freeze_verified': freeze['verified'], 'errors': errors, 'retuned_after_evaluation': False}
    (out / 'independent_verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    if errors:
        raise SystemExit(1)
if __name__ == '__main__':
    out = ROOT / 'results/security_crosscheck_20261117'
    lock = read(ROOT / 'configs/detector_long_horizon_20261117.lock.json')
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out / 'source_snapshot.zip') as archive:
        snapshot = Path(tmp)
        for name, expected in lock['source_fingerprint']['files'].items():
            data = archive.read(name)
            target = (snapshot / name).resolve()
            if not target.is_relative_to(snapshot.resolve()) or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f'Invalid source snapshot member: {name}')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        evidence = Path(lock['validation_evidence_path'])
        if not (snapshot / evidence).resolve().is_relative_to(snapshot.resolve()):
            raise ValueError('Invalid evidence path')
        (snapshot / evidence).parent.mkdir(parents=True, exist_ok=True)
        (snapshot / evidence).write_bytes((ROOT / evidence).read_bytes())
        verify(out, snapshot)
