from collections import defaultdict
import json
from pathlib import Path
import pandas as pd
from wsn_sim.experiment_execution import valid_completion
from wsn_sim.experiment_plan import verify_plan
from wsn_sim.experiment_statistics import holm_adjust, paired_comparison, restricted_lifetime_summary, sample_summary
PERFORMANCE_METRICS = ['pdr', 'throughput_bps', 'goodput_bps', 'energy_per_payload_bit_j', 'mean_latency_s', 'mean_actual_hops', 'reroute_decision_count', 'route_edges_changed']
SECURITY_METRICS = ['tpr', 'fpr', 'precision', 'f1', 'coverage']
LIFETIMES = ['FND', 'HND', 'LND']
CONTRASTS = [('EMHR_SF', 'MHR_SF'), ('SF2', 'EMHR_SF'), ('SF3', 'SF2'), ('SF3', 'EMHR_SF')]

def collect_batch(directory: Path, root: Path):
    plan = json.loads((directory / 'plan.json').read_text(encoding='utf-8'))
    verify_plan(plan, root)
    checkpoint = json.loads((directory / 'checkpoint.json').read_text(encoding='utf-8'))
    records = []
    for job in plan['jobs']:
        entry = checkpoint['runs'].get(job['run_id'], {})
        if entry.get('status') != 'COMPLETE':
            continue
        attempt = Path(entry['directory'])
        if not valid_completion(attempt, job):
            raise ValueError(f"completed run fails hash validation: {job['run_id']}")
        manifest = json.loads((attempt / 'run_manifest.json').read_text(encoding='utf-8'))
        summary = json.loads((attempt / 'summary.json').read_text(encoding='utf-8'))
        records.append({'job': job, 'manifest': manifest, 'summary': summary, 'directory': attempt})
    return (plan, checkpoint, records)

def flatten_records(records):
    horizons = defaultdict(list)
    for record in records:
        case = record['job']['case']
        if case['rho'] > 0:
            horizons[case['rho'], case['p_drop'], case['placement']].append(record['summary']['time_s'])
    rows = []
    for record in records:
        job, summary, manifest = (record['job'], record['summary'], record['manifest'])
        case, security, performance = (job['case'], summary['security'], summary['performance'])
        row = {**case, 'seed': job['seed'], 'run_id': job['run_id'], 'directory': str(record['directory']), 'pairing_hash': job['pairing_hash'], 'topology_hash': manifest['topology_hash'], 'source_sha256': job['source_sha256'], 'actual_attacker_count': manifest['attack']['attacker_count'], 'actual_attacker_ratio': manifest['attack']['actual_ratio'], 'wall_clock_s': manifest['wall_clock_s'], 'peak_working_set_bytes': manifest['peak_working_set_bytes'], 'actual_duration_s': summary['time_s'], 'requested_horizon_s': manifest['requested_horizon_s'], 'stop_reason': summary['stop_reason']}
        for name in ('actual_num_sensors', 'topology_seed', 'log_end_s'):
            if name in manifest:
                row[name] = manifest[name]
        row.update({name: performance[name] for name in PERFORMANCE_METRICS})
        row.update({name: security.get(name) for name in SECURITY_METRICS})
        for name in ('TP', 'FP', 'TN', 'FN'):
            row[name] = security[name]
        row['isolation_events'] = performance['security_overhead']['logical_state_events'].get('isolated', 0)
        for name in LIFETIMES:
            milestone = summary['lifetime'][name]
            row[name + '_s'] = milestone['time_s']
            row[name + '_censored'] = milestone['censored']
            row[name + '_restricted_s'] = milestone['time_s'] if milestone['time_s'] is not None else manifest['requested_horizon_s']
            row[name + '_payload_bits'] = milestone['received_payload_bits']
        family = (case['rho'], case['p_drop'], case['placement'])
        tau = min(horizons[family]) if case['rho'] > 0 else None
        row['delay_common_tau_s'] = tau
        delays = list(security['attacker_delays'].values())
        for kind in ('detection', 'isolation'):
            values = [delay[kind + '_delay_s'] for delay in delays]
            row[kind + '_event_coverage'] = sum((value is not None for value in values)) / len(values) if values else None
            row[kind + '_capped_delay_s'] = sum((min(value, tau) if value is not None else tau for value in values)) / len(values) if values and tau is not None else None
        rows.append(row)
    return rows

def make_tables(plan, checkpoint, records, output):
    output.mkdir(parents=True, exist_ok=True)
    rows = flatten_records(records)
    pd.DataFrame(rows).to_csv(output / 'runs.csv', index=False, encoding='utf-8')
    metrics = PERFORMANCE_METRICS + SECURITY_METRICS + ['detection_capped_delay_s', 'isolation_capped_delay_s', 'detection_event_coverage', 'isolation_event_coverage', 'isolation_events'] + [name + suffix for name in LIFETIMES for suffix in ('_restricted_s', '_payload_bits')]
    aggregates, completeness, lifetime = ([], [], {})
    expected = len(plan['seeds'])
    by_case = defaultdict(list)
    for row in rows:
        by_case[row['case_id']].append(row)
    for case in plan['cases']:
        group = by_case[case['case_id']]
        ids = [job['run_id'] for job in plan['jobs'] if job['case']['case_id'] == case['case_id']]
        failed = sum((checkpoint['runs'].get(run_id, {}).get('status') in {'FAILED', 'TIMEOUT'} for run_id in ids))
        completeness.append({**case, 'expected': expected, 'completed': len(group), 'failed': failed, 'pending': expected - len(group) - failed, 'meets_30_independent_seeds': len(group) >= 30 and len(group) == expected})
        for metric in metrics:
            aggregates.append({**case, 'metric': metric, 'estimand': 'restricted_to_administrative_horizon' if metric.endswith('_restricted_s') else 'conditional_on_observed_milestone' if metric.endswith('_payload_bits') else 'capped_at_common_observable_tau_includes_undetected' if 'capped_delay' in metric else 'mean_per_independent_seed', 'n_not_completed': expected - len(group), 'n_undefined_among_completed': sum((row[metric] is None for row in group)), **sample_summary([row[metric] for row in group], expected)})
        selected = [record for record in records if record['job']['case']['case_id'] == case['case_id']]
        lifetime[case['case_id']] = {name: restricted_lifetime_summary([record['summary']['lifetime'][name] for record in selected], [record['manifest']['requested_horizon_s'] for record in selected]) for name in LIFETIMES}
    pd.DataFrame(aggregates).to_csv(output / 'aggregate.csv', index=False, encoding='utf-8')
    pd.DataFrame(completeness).to_csv(output / 'completeness.csv', index=False, encoding='utf-8')
    (output / 'lifetime_censoring.json').write_text(json.dumps(lifetime, indent=2), encoding='utf-8')
    comparisons = []
    families = {(case['rho'], case['p_drop'], case['placement']) for case in plan['cases'] if case['rho'] >= 0}
    for family in sorted(families):
        family_cases = {case['scenario']: case for case in plan['cases'] if (case['rho'], case['p_drop'], case['placement']) == family}
        for first, second in CONTRASTS + [('EMHR', 'MHR')]:
            if first not in family_cases or second not in family_cases:
                continue
            a, b = (by_case[family_cases[first]['case_id']], by_case[family_cases[second]['case_id']])
            indexed_a, indexed_b = ({row['seed']: row for row in a}, {row['seed']: row for row in b})
            for seed in set(indexed_a) & set(indexed_b):
                if any((indexed_a[seed][name] != indexed_b[seed][name] for name in ('pairing_hash', 'topology_hash', 'actual_attacker_count'))):
                    raise ValueError('paired runs have different exogenous configuration/topology/attacker counts')
                rec_a = next((record for record in records if record['job']['run_id'] == indexed_a[seed]['run_id']))
                rec_b = next((record for record in records if record['job']['run_id'] == indexed_b[seed]['run_id']))
                if rec_a['manifest']['attack']['attacker_ids'] != rec_b['manifest']['attack']['attacker_ids']:
                    raise ValueError('paired attacker IDs differ')
            for metric in metrics:
                comparisons.append({'first': first, 'second': second, 'rho': family[0], 'p_drop': family[1], 'placement': family[2], 'metric': metric, **paired_comparison({row['seed']: row[metric] for row in a}, {row['seed']: row[metric] for row in b}, expected)})
    for comparison in comparisons:
        comparison['inferentially_complete_30_pairs'] = comparison['n_matched'] >= 30 and comparison['n_matched'] == expected
    for key in ('paired_t_p', 'wilcoxon_p'):
        adjusted = holm_adjust([row[key] for row in comparisons])
        for row, value in zip(comparisons, adjusted):
            row[key + '_holm'] = value
            row['holm_family_size'] = len(comparisons)
    pd.DataFrame(comparisons).to_csv(output / 'paired_comparisons.csv', index=False, encoding='utf-8')
    return (rows, aggregates, completeness, comparisons)
