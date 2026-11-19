from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest

@pytest.mark.parametrize('script,stage,case_count', [('check_recovery.py', 5, 7), ('check_metrics.py', 6, 5)])
def test_stage_commands_export_live_cases_and_replayable_raw_logs(project_root, tmp_path, script, stage, case_count):
    result = subprocess.run([sys.executable, f'scripts/{script}', '--output', str(tmp_path)], cwd=project_root, check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report['stage'] == stage
    assert report['checks_passed'] and all(report['cases'].values())
    assert len(report['cases']) == case_count
    assert report['evaluation_runs'] == 0
    directory = Path(report['output_directory'])
    manifest = json.loads((directory / 'run_manifest.json').read_text(encoding='utf-8'))
    assert all((Path(name).exists() for name in manifest['generated_files']))
    assert manifest['metric_schema'] == 'wsn_metrics_event_ordered_v2'
    if stage == 6:
        case = json.loads((directory / 'known_delivery/case_check.json').read_text(encoding='utf-8'))
        assert case['saved_raw_event_replay_passed']
        assert case['summary']['performance']['received_payload_bits'] == 1024

def test_cli_refuses_calibrated_detector_from_different_code_before_simulation(project_root, detector_config, tmp_path):
    parameters = asdict(detector_config)
    parameters['calibration_status'] = 'CALIBRATED'
    config_file = tmp_path / 'frozen.json'
    config_file.write_text(json.dumps(parameters), encoding='utf-8')
    lock = {'config_file_sha256': hashlib.sha256(config_file.read_bytes()).hexdigest(), 'source_fingerprint': {'sha256': 'different-source'}}
    config_file.with_suffix('.lock.json').write_text(json.dumps(lock), encoding='utf-8')
    output = tmp_path / 'runs'
    result = subprocess.run([sys.executable, 'main.py', '--duration', '0.1', '--detector-config', str(config_file), '--output', str(output)], cwd=project_root, capture_output=True, text=True)
    assert result.returncode != 0 and 'source changed since calibration' in result.stderr
    assert not output.exists()
