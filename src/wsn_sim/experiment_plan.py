from dataclasses import replace
import json
from pathlib import Path
from wsn_sim.calibration import json_digest, source_fingerprint, verify_freeze
from wsn_sim.config import DetectorConfig, require_probability
SCENARIOS = {'MHR': ('MHR', False, False), 'EMHR': ('EMHR', False, False), 'MHR_SF': ('MHR', True, False), 'EMHR_SF': ('EMHR', True, False), 'SF2': ('EMHR', True, True), 'SF3': ('S_EMHR', True, True)}
PILOT_SEEDS = [44001, 44002, 44003, 44004, 44005]
PAIR_FIELDS = ('area_width_m', 'area_height_m', 'num_sensors', 'num_sinks', 'initial_energy_j', 'energy_threshold_ratio', 'communication_range_m', 'packet_size_bytes', 'wire_size_bytes', 'packet_interval_s', 'bandwidth_bps', 'seed', 'channel_loss_probability', 'max_rounds')

def pairing_hash(configuration):
    fields = {key: configuration[key] for key in PAIR_FIELDS}
    if 'topology_model' in configuration:
        fields['topology_model'] = configuration['topology_model']
    return json_digest(fields)

def validate_calibration_basis(configuration, lock):
    basis = lock['simulation_configuration']
    for name in PAIR_FIELDS:
        if name not in {'seed', 'channel_loss_probability', 'max_rounds'} and configuration[name] != basis[name]:
            raise ValueError(f'calibration basis mismatch: {name}')
    if configuration.get('topology_model', 'uniform') != basis.get('topology_model', 'uniform'):
        raise ValueError('calibration basis mismatch: topology_model')
    if configuration['channel_loss_probability'] not in lock['protocol']['channel_loss_probabilities']:
        raise ValueError('channel loss is outside the benign calibration protocol')

def parse_seeds(value: str) -> list[int]:
    seeds = []
    for token in value.split(','):
        if ':' in token:
            start, end = map(int, token.split(':'))
            seeds.extend(range(start, end + 1))
        else:
            seeds.append(int(token))
    if not seeds or any((seed < 0 for seed in seeds)) or len(seeds) != len(set(seeds)):
        raise ValueError('seeds must be nonempty, nonnegative and unique')
    return seeds

def definitions(rhos=(0.02, 0.05, 0.1), drops=(0.25, 0.5, 0.75), placements=('random',), core_only=False):
    for probability in (*rhos, *drops):
        require_probability('experiment_probability', probability)
    if not set(placements).issubset({'random', 'near_sink'}) or not placements:
        raise ValueError('unsupported attacker placement')
    cases = [{'scenario': name, 'rho': 0, 'p_drop': 0, 'placement': 'random'} for name in ('MHR', 'EMHR')]
    values = [(rho, probability) for rho in rhos for probability in drops]
    values.sort(key=lambda pair: (pair != (0.05, 0.5), pair))
    for placement in placements:
        for rho, probability in values:
            if core_only and (rho, probability) != (0.05, 0.5):
                continue
            for name in ('MHR_SF', 'EMHR_SF', 'SF2', 'SF3'):
                cases.append({'scenario': name, 'rho': rho, 'p_drop': probability, 'placement': placement})
    for case in cases:
        case['case_id'] = f"{case['scenario']}_r{case['rho']:g}_d{case['p_drop']:g}_{case['placement']}"
    return cases

def validate_evaluation_seeds(root: Path, seeds: list[int], test_only=False):
    protocol = json.loads((root / 'configs/calibration_protocol.json').read_text(encoding='utf-8'))
    forbidden = set(PILOT_SEEDS) | {45001}
    for name, values in protocol['seed_partitions'].items():
        if name != 'evaluation_reserved':
            forbidden.update(values)
    if len(seeds) != len(set(seeds)) or not seeds or any((isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds)):
        raise ValueError('evaluation seeds must be distinct nonnegative integers')
    if not test_only and forbidden.intersection(seeds):
        raise ValueError('evaluation seeds overlap calibration, validation or pilot')
    if len(seeds) < 30 and (not test_only):
        raise ValueError('evaluation requires at least 30 independent seeds per configuration')

def choose_range(rows, reachability_threshold=0.99, full_topology_fraction=0.8):
    candidates = []
    for radius in (250, 300, 350):
        group = [row for row in rows if row['communication_range_m'] == radius]
        if not group:
            raise ValueError('range pilot must include 250, 300 and 350')
        mean = sum((row['routable_fraction'] for row in group)) / len(group)
        full = sum((row['routable_fraction'] == 1 for row in group)) / len(group)
        candidates.append({'radius_m': radius, 'mean_routable_fraction': mean, 'fully_reachable_topology_fraction': full, 'not_fully_reachable_rate': 1 - full, 'passes': mean >= reachability_threshold and full >= full_topology_fraction})
    eligible = [row for row in candidates if row['passes']]
    selected = min(eligible, key=lambda row: row['radius_m']) if eligible else max(candidates, key=lambda row: (row['mean_routable_fraction'], -row['radius_m']))
    return {'selected_range_m': selected['radius_m'], 'criteria_met': bool(eligible), 'criteria': {'minimum_mean_reachability': reachability_threshold, 'minimum_full_topology_fraction': full_topology_fraction}, 'rule': 'lowest_R_meeting_both_criteria_else_best_mean_with_explicit_failure_flag', 'all_radii': candidates, 'pilot_seeds': PILOT_SEEDS, 'evaluation_used': False, 'topologies_discarded': 0}

def build_plan(root, base, detector_path, seeds, cases, *, test_only=False, sample_interval_s=100, full_trace=False, explicit_ids=None):
    validate_evaluation_seeds(root, seeds, test_only)
    if explicit_ids is not None and (not test_only):
        raise ValueError('explicit relay IDs are a debug option requiring --test-only')
    if not test_only and base.max_rounds != 10000:
        raise ValueError('official batch must keep max_rounds=10000')
    if sample_interval_s <= 0:
        raise ValueError('sampling interval must be positive')
    fingerprint = source_fingerprint(root)
    detector = DetectorConfig(**json.loads(detector_path.read_text(encoding='utf-8'))) if detector_path else None
    freeze = None
    if not test_only:
        if detector is None:
            raise ValueError('a frozen calibrated detector is required')
        freeze = verify_freeze(detector_path, root)
        lock = json.loads(detector_path.with_suffix('.lock.json').read_text(encoding='utf-8'))
        validate_calibration_basis(base.to_dict(), lock)
    jobs = []
    for case in cases:
        algorithm, attacked, detecting = SCENARIOS[case['scenario']]
        if detecting and detector is None:
            raise ValueError('SF2/SF3 require detector parameters')
        for seed in seeds:
            config = replace(base, seed=seed, routing_algorithm=algorithm, detector=detector if detecting else None, attacker_ratio=case['rho'] if attacked else 0, p_drop=case['p_drop'] if attacked else 0, attacker_ids=tuple(explicit_ids) if attacked and explicit_ids is not None else None if attacked else (), attacker_selection=case['placement'])
            values = config.to_dict()
            body = {'case': case, 'configuration': values, 'seed': seed, 'source_sha256': fingerprint['sha256'], 'freeze': freeze, 'sample_interval_s': sample_interval_s, 'full_trace': full_trace, 'scope': 'TEST_ONLY' if test_only else 'EVALUATION_MAX_ROUNDS_10000', 'pairing_hash': pairing_hash(values)}
            body['run_id'] = json_digest(body)[:24]
            jobs.append(body)
    pilot_selection = None
    if not test_only:
        pilot_selection = json.loads((root / 'configs/experiment_selection.json').read_text(encoding='utf-8'))
        if pilot_selection['selected_range_m'] != base.communication_range_m:
            raise ValueError('evaluation range does not match the recorded pilot selection')
    plan = {'version': 'wsn_experiments_v1', 'scope': 'TEST_ONLY' if test_only else 'EVALUATION', 'analysis_protocol': json.loads((root / 'configs/experiment_protocol.json').read_text(encoding='utf-8')), 'base_configuration': base.to_dict(), 'source_fingerprint': fingerprint, 'range_pilot': pilot_selection, 'detector_path': str(detector_path) if detector_path else None, 'freeze': freeze, 'seeds': seeds, 'cases': cases, 'jobs': jobs, 'expected_runs': len(jobs), 'independent_seeds_per_configuration': len(seeds), 'extension_pending': {'near_sink_full_attack_grid': 1080, 'two_additional_ranges': 2280, 'Eth_ratios_0.1_0.3': 2280, 'two_additional_channel_probabilities': 2280, 'note': 'extensions are separate explicit plans; new R/Eth require matched benign calibration'}}
    plan['plan_hash'] = json_digest(plan)
    return plan

def verify_plan(plan, root):
    content = dict(plan)
    digest = content.pop('plan_hash')
    if json_digest(content) != digest:
        raise ValueError('experiment plan content changed')
    if source_fingerprint(root)['sha256'] != plan['source_fingerprint']['sha256']:
        raise ValueError('source changed; refuse to mix code versions')
    if plan['scope'] == 'EVALUATION':
        validate_evaluation_seeds(root, plan['seeds'])
        current = verify_freeze(Path(plan['detector_path']), root)
        if current['config_file_sha256'] != plan['freeze']['config_file_sha256']:
            raise ValueError('frozen detector changed')
    for job in plan['jobs']:
        body = dict(job)
        run_id = body.pop('run_id')
        if json_digest(body)[:24] != run_id:
            raise ValueError('run configuration hash mismatch')
    return True
