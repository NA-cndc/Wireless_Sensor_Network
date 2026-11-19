import json
from pathlib import Path
from wsn_sim.verification import run_verification

def test_verification_demo_reports_live_packet_observations_and_reroutes(project_root, tmp_path, capsys):
    report = run_verification(project_root, tmp_path)
    printed = json.loads(capsys.readouterr().out)
    assert printed == report
    metrics = report['summary']['performance']
    assert (metrics['generated'], metrics['delivered'], metrics['dropped']) == (8, 5, 3)
    assert metrics['pending_in_flight'] == 0
    assert report['battery'] == {'initial_energy_j': 5, 'energy_threshold_j': 1}
    attack = report['attack_example']
    assert attack['events'][-2]['event'] == 'rx'
    assert attack['events'][-2]['energy_j'] > 0
    assert attack['events'][-1]['reason'] == 'selective_forwarding'
    rerouting = report['in_flight_reroute']
    assert rerouting['status'] == 'DELIVERED'
    assert rerouting['packet_id'] == 'source_p1'
    assert rerouting['actual_path'] == ['source', 'bridge', 'holder', 'backup', 'sink']
    assert rerouting['reroutes'][0]['time_s'] == 2
    assert rerouting['reroutes'][0]['reason'] == 'isolation'
    assert report['summary']['security']['TP'] == 1
    assert report['summary']['security']['FP'] == 0
    directory = Path(report['output_directory'])
    manifest = json.loads((directory / 'run_manifest.json').read_text(encoding='utf-8'))
    assert all((Path(path).exists() for path in manifest['generated_files']))
    assert manifest['attack']['attacker_ids'] == ['sensor_attacker']
    assert (directory / 'in_flight' / 'run_manifest.json').exists()
