from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import pandas as pd
import pytest
from wsn_sim.experiment_execution import execute_worker, valid_completion
from wsn_sim.experiment_plan import build_plan, choose_range, definitions, parse_seeds, validate_evaluation_seeds, verify_plan
from wsn_sim.experiment_report import render_report
from wsn_sim.experiment_tables import collect_batch, make_tables
from wsn_sim.experiments import run_batch
from wsn_sim.storage import save_json

@pytest.fixture
def tiny_plan(config, project_root):
    base = replace(config, config_profile='TEST_ONLY', num_sensors=8, num_sinks=1, area_width_m=100, area_height_m=100, communication_range_m=50, max_rounds=3)
    return build_plan(project_root, base, project_root / 'configs/detector_test_only.json', [61001, 61002], definitions(core_only=True)[:1], test_only=True, sample_interval_s=10)

def test_matrix_is_38_definitions_and_30_seeds_not_repeated_runs(project_root):
    cases = definitions()
    assert len(cases) == 38 and len({row['case_id'] for row in cases}) == 38
    assert len(definitions(placements=['random', 'near_sink'])) == 74
    assert len(definitions(core_only=True)) == 6
    seeds = parse_seeds('51001:51030')
    assert len(seeds) == len(set(seeds)) == 30
    validate_evaluation_seeds(project_root, seeds)
    for invalid in ([51001] * 30, [41001] + list(range(51001, 51030)), [45001] + list(range(51001, 51030)), [1, 2]):
        with pytest.raises(ValueError):
            validate_evaluation_seeds(project_root, invalid)
    with pytest.raises(ValueError):
        parse_seeds('1,1')

def test_range_selection_keeps_bad_topologies_and_uses_preregistered_thresholds():
    rows = []
    for radius, fractions in ((250, [1, 1, 0.98, 0.98, 0.98]), (300, [1, 1, 1, 1, 0.995]), (350, [1] * 5)):
        rows.extend(({'communication_range_m': radius, 'routable_fraction': value} for value in fractions))
    selected = choose_range(rows)
    assert selected['selected_range_m'] == 300 and selected['criteria_met']
    assert selected['all_radii'][0]['not_fully_reachable_rate'] == 0.6
    assert selected['topologies_discarded'] == 0
    bad = [{'communication_range_m': radius, 'routable_fraction': value} for radius, value in ((250, 0.5), (300, 0.7), (350, 0.8))]
    fallback = choose_range(bad)
    assert fallback['selected_range_m'] == 350 and (not fallback['criteria_met'])

def test_plan_hash_detects_config_change_and_official_rounds_cannot_be_shortened(tiny_plan, project_root, config):
    assert verify_plan(tiny_plan, project_root)
    changed = deepcopy(tiny_plan)
    changed['jobs'][0]['configuration']['packet_size_bytes'] = 256
    with pytest.raises(ValueError, match='plan content'):
        verify_plan(changed, project_root)
    with pytest.raises(ValueError, match='max_rounds'):
        build_plan(project_root, replace(config, max_rounds=2), project_root / 'configs/detector_stage56.json', list(range(51001, 51031)), definitions())

def test_batch_resume_skips_valid_runs_retries_corrupt_run_and_reports_actual_statistics(tiny_plan, project_root, tmp_path):
    directory = tmp_path / 'batch'
    directory.mkdir()
    save_json(tiny_plan, directory / 'plan.json')
    first = run_batch(tiny_plan, directory, project_root, workers=1, retries=0, timeout_s=60)
    assert first['counts'] == {'expected': 2, 'completed': 2, 'failed': 0, 'pending': 0, 'running': 0}
    attempts = len(first['attempts'])
    second = run_batch(tiny_plan, directory, project_root, workers=1, retries=0, timeout_s=60)
    assert len(second['attempts']) == attempts
    spec = tiny_plan['jobs'][0]
    old = Path(second['runs'][spec['run_id']]['directory'])
    with (old / 'summary.json').open('a', encoding='utf-8') as handle:
        handle.write(' ')
    assert not valid_completion(old, spec)
    third = run_batch(tiny_plan, directory, project_root, workers=1, retries=0, timeout_s=60)
    assert third['counts']['completed'] == 2
    assert third['runs'][spec['run_id']]['directory'] != str(old)
    assert old.exists()
    plan, checkpoint, records = collect_batch(directory, project_root)
    tables = tmp_path / 'tables'
    _, aggregate, completeness, _ = make_tables(plan, checkpoint, records, tables)
    assert completeness[0]['completed'] == 2 and (not completeness[0]['meets_30_independent_seeds'])
    pdr = next((row for row in aggregate if row['metric'] == 'pdr'))
    assert pdr['n_used'] == 2 and (not pdr['meets_30_seed_requirement'])
    assert len(pd.read_csv(tables / 'runs.csv')) == 2
    report = render_report(directory, tmp_path / 'reports')
    assert not report['all_main_evaluation_complete'] and report['scope'] == 'TEST_ONLY'
    assert report['counts']['completed'] == 2
    manifest = json.loads((Path(report['output_directory']) / 'figure_manifest.json').read_text(encoding='utf-8'))
    assert len(manifest) == 6 and all((Path(item['data_csv']).is_file() for item in manifest))

@pytest.mark.parametrize('timed_out', [False, True])
def test_failed_or_timed_out_attempt_is_preserved_not_counted_as_completed(tiny_plan, project_root, tmp_path, monkeypatch, timed_out):
    plan = deepcopy(tiny_plan)
    plan['jobs'] = plan['jobs'][:1]
    plan['expected_runs'] = 1
    from wsn_sim.calibration import json_digest
    plan.pop('plan_hash')
    plan['plan_hash'] = json_digest(plan)

    class FailedProcess:
        next_pid = 10000

        def __init__(self, *args, **kwargs):
            self.pid = FailedProcess.next_pid
            FailedProcess.next_pid += 1
            self.returncode = None if timed_out else 1

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            self.returncode = -15
            return self.returncode
    monkeypatch.setattr('wsn_sim.experiments.subprocess.Popen', FailedProcess)
    state = run_batch(plan, tmp_path / 'failed', project_root, workers=1, retries=1, timeout_s=0.001 if timed_out else 60)
    assert state['counts']['completed'] == 0 and state['counts']['failed'] == 1
    assert len([row for row in state['attempts'] if row['status'] in {'FAILED', 'TIMEOUT'}]) == 2
    assert all(((Path(row['directory']) / 'spec.json').exists() for row in state['attempts']))

def test_worker_rejects_configuration_hash_change_and_preserves_failure(tiny_plan, project_root, tmp_path):
    spec = deepcopy(tiny_plan['jobs'][0])
    spec['configuration']['num_sensors'] = 9
    with pytest.raises(ValueError, match='configuration hash'):
        execute_worker(spec, tmp_path, project_root)
    failure = json.loads((tmp_path / 'failure.json').read_text(encoding='utf-8'))
    assert failure['status'] == 'FAILED'
