'''Regression tests for exported metric integrity and portable pilot plotting.'''

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import networkx as nx
import pytest

from scripts.validate_metrics import InputDataError, validate_run
from wsn_sim.config import SimulationConfig
from wsn_sim.energy import RadioModel
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLOTTER = PROJECT_ROOT / 'scripts' / 'plot_metrics.py'
RUNNER = PROJECT_ROOT / 'scripts' / 'run_metrics_pilot.py'


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open('w', newline='', encoding='utf-8') as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _mutate_csv(path: Path, mutation) -> None:
    with path.open('r', newline='', encoding='utf-8') as file_handle:
        reader = csv.DictReader(file_handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    mutation(rows)
    _write_csv(path, rows, fields)


def _failed_checks(run_dir: Path) -> set[str]:
    return {
        check['metric']
        for check in validate_run(run_dir)['checks']
        if not check['passed']
    }


def _star_network(sensor_count: int = 3) -> Network:
    base = SimulationConfig.from_json(PROJECT_ROOT / 'configs' / 'default.json')
    config = replace(base, num_sensors=sensor_count, num_sinks=1)
    network = Network(config, communication_range_m=250.0)
    network.sensors = {
        f'sensor_{index}': Sensor(
            f'sensor_{index}', 20.0 * (index + 1), 0.0, config.initial_energy_j
        )
        for index in range(sensor_count)
    }
    sink = Sink('sink_00', 0.0, 0.0)
    network.sinks = {sink.node_id: sink}
    network.graph = nx.Graph()
    network.graph.add_node('sink_00', node_type='sink', x=0.0, y=0.0)
    for sensor in network.sensors.values():
        network.graph.add_node(
            sensor.node_id, node_type='sensor', x=sensor.x, y=sensor.y
        )
        network.graph.add_edge(
            sensor.node_id,
            sink.node_id,
            distance_m=sensor.distance_to(sink),
            weight=sensor.distance_to(sink),
        )
    network.communication_range_m = 250.0
    return network


def _export_valid_run(run_dir: Path) -> Path:
    simulation = Simulation(
        _star_network(), routing_algorithm='MHR', quiet=True, seed=42
    )
    simulation.run_for(11.0)
    simulation.export_results(run_dir)
    assert validate_run(run_dir)['passed'] is True
    return run_dir


def _export_simultaneous_deaths(run_dir: Path) -> Path:
    network = _star_network(sensor_count=2)
    simulation = Simulation(network, routing_algorithm='MHR', quiet=True, seed=42)

    def deplete_at_zero():
        yield simulation.env.timeout(0.0)
        bits = simulation.config.packet_size_bytes * 8
        for sensor in network.sensors.values():
            distance = (
                (sensor.energy_j - simulation.radio.e_elec * bits)
                / (simulation.radio.e_mp * bits)
            ) ** 0.25
            simulation.radio.attempt_transmission(
                sensor,
                network.sinks['sink_00'],
                simulation.config.packet_size_bytes,
                distance,
                sim_time_s=float(simulation.env.now),
                packet_id=f'controlled_{sensor.node_id}',
            )

    simulation.env.process(deplete_at_zero())
    simulation.run_for(1.0)
    simulation.export_results(run_dir)
    assert validate_run(run_dir)['passed'] is True
    return run_dir


def _export_failed_rx_sender_death(run_dir: Path) -> Path:
    base = SimulationConfig.from_json(PROJECT_ROOT / 'configs' / 'default.json')
    config = replace(base, num_sensors=2, num_sinks=1)
    radio = RadioModel()
    tx_cost = radio.compute_tx_energy(config.packet_size_bytes * 8, 50.0)
    rx_cost = radio.compute_rx_energy(config.packet_size_bytes * 8)
    network = Network(config, communication_range_m=250.0)
    sender = Sensor('sender', 0.0, 0.0, tx_cost)
    receiver = Sensor('receiver', 50.0, 0.0, rx_cost / 2.0)
    sink = Sink('sink_00', 100.0, 0.0)
    network.sensors = {'sender': sender, 'receiver': receiver}
    network.sinks = {'sink_00': sink}
    network.graph = nx.Graph()
    for node in (sender, receiver, sink):
        network.graph.add_node(
            node.node_id,
            node_type='sink' if isinstance(node, Sink) else 'sensor',
            x=node.x,
            y=node.y,
        )
    network.graph.add_edge('sender', 'receiver', distance_m=50.0, weight=50.0)
    network.graph.add_edge('receiver', 'sink_00', distance_m=50.0, weight=50.0)
    network.communication_range_m = 250.0
    simulation = Simulation(network, routing_algorithm='MHR', quiet=True, seed=42)

    def transmit_at_zero():
        yield simulation.env.timeout(0.0)
        simulation.radio.attempt_transmission(
            sender,
            receiver,
            config.packet_size_bytes,
            50.0,
            sim_time_s=float(simulation.env.now),
            packet_id='failed_rx',
        )

    simulation.env.process(transmit_at_zero())
    simulation.run_for(1.0)
    simulation.export_results(run_dir)
    return run_dir


@pytest.fixture
def valid_run(tmp_path: Path) -> Path:
    return _export_valid_run(tmp_path / 'valid_run')


@pytest.fixture
def death_run(tmp_path: Path) -> Path:
    return _export_simultaneous_deaths(tmp_path / 'death_run')


def test_valid_export_still_passes(valid_run: Path):
    assert validate_run(valid_run)['passed'] is True


def test_death_with_positive_energy_is_rejected(death_run: Path):
    _mutate_csv(
        death_run / 'node_deaths.csv',
        lambda rows: rows[0].__setitem__('energy_after_j', '5.0'),
    )
    assert 'node_death_event_integrity' in _failed_checks(death_run)


def test_death_timestamp_without_matching_debit_is_rejected(death_run: Path):
    _mutate_csv(
        death_run / 'node_deaths.csv',
        lambda rows: rows[0].__setitem__('death_time_s', '0.5'),
    )
    assert 'node_death_event_integrity' in _failed_checks(death_run)


@pytest.mark.parametrize('corruption', ['unknown', 'duplicate'])
def test_unknown_or_duplicate_death_is_rejected(death_run: Path, corruption: str):
    def mutate(rows: list[dict[str, str]]) -> None:
        if corruption == 'unknown':
            rows[0]['node_id'] = 'unknown_sensor'
        else:
            rows.append(dict(rows[0]))

    _mutate_csv(death_run / 'node_deaths.csv', mutate)
    assert 'node_death_event_integrity' in _failed_checks(death_run)


def test_reachability_ratio_inconsistent_with_counts_is_rejected(valid_run: Path):
    _mutate_csv(
        valid_run / 'reachability_events.csv',
        lambda rows: rows[0].update({'reachable_sensors': '0', 'reachability_ratio': '1.0'}),
    )
    assert 'reachability_event_integrity' in _failed_checks(valid_run)


def test_reachability_counts_matching_ratio_but_not_topology_are_rejected(valid_run: Path):
    _mutate_csv(
        valid_run / 'reachability_events.csv',
        lambda rows: rows[0].update({
            'reachable_sensors': '0',
            'reachability_ratio': '0.0',
            'state': 'below_threshold',
        }),
    )
    assert 'reachability_event_integrity' in _failed_checks(valid_run)


def test_ledger_timestamp_outside_measurement_window_is_rejected(valid_run: Path):
    _mutate_csv(
        valid_run / 'energy_ledger.csv',
        lambda rows: rows[0].__setitem__('time_s', '999.0'),
    )
    assert 'energy_ledger_integrity' in _failed_checks(valid_run)


def test_duration_mismatch_is_rejected(valid_run: Path):
    metrics_path = valid_run / 'metrics.json'
    metrics = json.loads(metrics_path.read_text(encoding='utf-8'))
    metrics['simulated_time_s'] = 12.0
    metrics_path.write_text(json.dumps(metrics, indent=2) + '\n', encoding='utf-8')
    assert 'duration_consistency' in _failed_checks(valid_run)


def test_failed_rx_still_accounts_sender_tx_and_death(tmp_path: Path):
    run_dir = _export_failed_rx_sender_death(tmp_path / 'failed_rx')
    report = validate_run(run_dir)
    assert report['passed'] is True
    ledger = list(csv.DictReader((run_dir / 'energy_ledger.csv').open(encoding='utf-8')))
    assert ledger[0]['success'] == 'False'
    assert float(ledger[0]['tx_energy_j']) > 0
    assert float(ledger[0]['rx_energy_j']) == 0


def test_zero_and_simultaneous_death_timestamps_pass(death_run: Path):
    deaths = list(csv.DictReader((death_run / 'node_deaths.csv').open(encoding='utf-8')))
    assert [float(row['death_time_s']) for row in deaths] == [0.0, 0.0]
    assert validate_run(death_run)['passed'] is True


def test_non_finite_values_are_input_errors(valid_run: Path):
    _mutate_csv(
        valid_run / 'packets.csv',
        lambda rows: rows[0].__setitem__('created_at', 'NaN'),
    )
    with pytest.raises(InputDataError, match='finite'):
        validate_run(valid_run)
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / 'scripts' / 'validate_metrics.py'),
            str(valid_run),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert 'VALIDATION ERROR' in completed.stderr


def test_payload_larger_than_packet_is_rejected(valid_run: Path):
    _mutate_csv(
        valid_run / 'packets.csv',
        lambda rows: rows[0].__setitem__('payload_size_bytes', '129'),
    )
    assert 'packet_field_and_domain_validity' in _failed_checks(valid_run)


def _make_pilot(root: Path) -> Path:
    root.mkdir(parents=True)
    scenario = 'MHR_R250m_seed42'
    run_dir = _export_valid_run(root / scenario)
    metrics = json.loads((run_dir / 'metrics.json').read_text(encoding='utf-8'))
    summary = {
        'scenario': scenario,
        'algorithm': 'MHR',
        'range_m': 250.0,
        'seed': 42,
        'requested_duration_s': 11.0,
        'actual_duration_s': metrics['measurement_duration_s'],
        'generated_packets': metrics['generated_packets'],
        'delivered_packets': metrics['delivered_packets'],
        'dropped_packets': metrics['dropped_packets'],
        'pending_packets': metrics['pending_packets'],
        'pdr_percent': metrics['pdr_percent'],
        'throughput_bps': metrics['throughput_bps'],
        'goodput_bps': metrics['goodput_bps'],
        'average_hops': metrics['average_hops'],
        'average_end_to_end_delay_s': metrics['average_end_to_end_delay_s'],
        'fnd_s': metrics['fnd_s'],
        'hnd_s': metrics['hnd_s'],
        'lnd_s': metrics['lnd_s'],
        'functional_network_death_s': metrics['functional_network_death_s'],
        'validation_passed': True,
        'output_dir': scenario,
    }
    _write_csv(root / 'pilot_summary.csv', [summary], list(summary))
    (root / 'pilot_manifest.json').write_text(
        json.dumps({'requested_scenarios': 1, 'completed_scenarios': 1}) + '\n',
        encoding='utf-8',
    )
    return root


def _mutate_summary(root: Path, field: str, value: str) -> None:
    _mutate_csv(
        root / 'pilot_summary.csv',
        lambda rows: rows[0].__setitem__(field, value),
    )


def _run_plotter(root: Path, *, cwd: Path | None = None, output: Path | None = None):
    command = [sys.executable, str(PLOTTER), str(root)]
    if output is not None:
        command.extend(['--output-dir', str(output)])
    return subprocess.run(
        command,
        cwd=cwd or PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_plotter_revalidates_raw_data_despite_stale_pass(tmp_path: Path):
    pilot = _make_pilot(tmp_path / 'pilot')
    _mutate_csv(
        pilot / 'MHR_R250m_seed42' / 'energy_ledger.csv',
        lambda rows: rows[0].__setitem__('time_s', '999.0'),
    )
    output = tmp_path / 'figures'
    completed = _run_plotter(pilot, output=output)
    assert completed.returncode != 0
    assert not output.exists()


@pytest.mark.parametrize(
    ('field', 'value'),
    [('pdr_percent', '150.0'), ('pdr_percent', '90.0'), ('throughput_bps', '1.0')],
)
def test_plotter_rejects_tampered_summary(
    tmp_path: Path, field: str, value: str
):
    pilot = _make_pilot(tmp_path / 'pilot')
    _mutate_summary(pilot, field, value)
    output = tmp_path / 'figures'
    completed = _run_plotter(pilot, output=output)
    assert completed.returncode != 0
    assert field in completed.stderr
    assert not output.exists()


def test_plotter_missing_run_has_nonzero_exit_and_no_figures(tmp_path: Path):
    pilot = _make_pilot(tmp_path / 'pilot')
    _mutate_summary(pilot, 'scenario', 'missing_scenario')
    output = tmp_path / 'figures'
    completed = _run_plotter(pilot, output=output)
    assert completed.returncode != 0
    assert not output.exists()


def test_plotter_valid_run_has_zero_exit_and_creates_figures(tmp_path: Path):
    pilot = _make_pilot(tmp_path / 'pilot')
    completed = _run_plotter(pilot)
    assert completed.returncode == 0, completed.stderr
    assert len(list((pilot / 'figures').glob('*.png'))) == 6


def test_plotter_resolves_legacy_windows_path_under_current_root(tmp_path: Path):
    pilot = _make_pilot(tmp_path / 'pilot')
    _mutate_summary(
        pilot,
        'output_dir',
        r'results\metrics_pilot_old\MHR_R250m_seed42',
    )
    run_dir = pilot / 'MHR_R250m_seed42'
    (run_dir / 'topology_edges.csv').unlink()
    manifest_path = run_dir / 'run_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest.pop('export_schema_version')
    manifest['generated_files'].remove('topology_edges.csv')
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    completed = _run_plotter(pilot)
    assert completed.returncode == 0, completed.stderr


def test_copied_pilot_plots_from_different_cwd(tmp_path: Path):
    original = _make_pilot(tmp_path / 'original')
    copied = tmp_path / 'moved' / 'copied_pilot'
    copied.parent.mkdir()
    shutil.copytree(original, copied)
    other_cwd = tmp_path / 'other_cwd'
    other_cwd.mkdir()
    completed = _run_plotter(copied, cwd=other_cwd)
    assert completed.returncode == 0, completed.stderr
    assert (copied / 'figures' / '02_pdr_by_range.png').exists()


def test_copied_pilot_corruption_does_not_fall_back_to_original(tmp_path: Path):
    original = _make_pilot(tmp_path / 'original')
    copied = tmp_path / 'copied'
    shutil.copytree(original, copied)
    _mutate_csv(
        copied / 'MHR_R250m_seed42' / 'energy_ledger.csv',
        lambda rows: rows[0].__setitem__('time_s', '999.0'),
    )
    output = copied / 'new_figures'
    completed = _run_plotter(copied, output=output)
    assert completed.returncode != 0
    assert not output.exists()


def test_runner_writes_portable_relative_output_paths(tmp_path: Path):
    config = json.loads((PROJECT_ROOT / 'configs' / 'default.json').read_text())
    config.update({'num_sensors': 4, 'num_sinks': 1})
    config_path = tmp_path / 'small_config.json'
    config_path.write_text(json.dumps(config), encoding='utf-8')
    output = tmp_path / 'runner_output'
    completed = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            '--config',
            str(config_path),
            '--seeds',
            '42',
            '--algorithms',
            'MHR',
            '--ranges',
            '250',
            '--duration',
            '1',
            '--output-dir',
            str(output),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    summary = list(csv.DictReader((output / 'pilot_summary.csv').open(encoding='utf-8')))
    assert summary[0]['output_dir'] == 'MHR_R250m_seed42'
    pilot_manifest = json.loads((output / 'pilot_manifest.json').read_text())
    assert pilot_manifest['controlled_lifetime_run'] == 'controlled_lifetime_run'
