'''Run a reproducible MHR/EMHR metrics pilot and validate every scenario.'''

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx
from validate_metrics import validate_run

from wsn_sim.config import SimulationConfig
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation


def _parse_csv(value: str, cast):
    items = [item.strip() for item in value.split(',') if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError('list must not be empty')
    try:
        return [cast(item) for item in items]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open('w', newline='', encoding='utf-8') as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fairness_fingerprint(simulation: Simulation) -> str:
    state = {
        'coordinates': simulation.network.coordinates(),
        'initial_energy_j': simulation.config.initial_energy_j,
        'packet_size_bytes': simulation.config.packet_size_bytes,
        'payload_size_bytes': simulation.config.payload_size_bytes,
        'packet_interval_s': simulation.config.packet_interval_s,
        'topology_seed': simulation.config.seed,
        'traffic_seed': simulation.traffic_seed,
    }
    encoded = json.dumps(state, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def _controlled_lifetime_network(config: SimulationConfig) -> Network:
    network = Network(config, communication_range_m=250.0)
    network.sensors = {
        'relay': Sensor('relay', 100.0, 0.0, config.initial_energy_j),
        'sensor_1': Sensor('sensor_1', 200.0, 50.0, config.initial_energy_j),
        'sensor_2': Sensor('sensor_2', 200.0, 0.0, config.initial_energy_j),
        'sensor_3': Sensor('sensor_3', 200.0, -50.0, config.initial_energy_j),
    }
    network.sinks = {'sink_00': Sink('sink_00', 0.0, 0.0)}
    network.graph = nx.Graph()
    for sensor in network.sensors.values():
        network.graph.add_node(
            sensor.node_id,
            node_type='sensor',
            x=sensor.x,
            y=sensor.y,
        )
    network.graph.add_node('sink_00', node_type='sink', x=0.0, y=0.0)
    network.graph.add_edges_from(
        [
            ('sink_00', 'relay'),
            ('relay', 'sensor_1'),
            ('relay', 'sensor_2'),
            ('relay', 'sensor_3'),
        ]
    )
    return network


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Run the WSN metrics pilot.')
    parser.add_argument('--config', type=Path, default=Path('configs/default.json'))
    parser.add_argument('--seeds', default='42')
    parser.add_argument('--algorithms', default='MHR,EMHR')
    parser.add_argument('--ranges', default='250,300,350')
    parser.add_argument('--duration', type=float, default=101.0)
    parser.add_argument('--output-dir', type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.duration <= 0:
        print('duration must be greater than zero', file=sys.stderr)
        return 2
    seeds = _parse_csv(args.seeds, int)
    algorithms = [item.upper() for item in _parse_csv(args.algorithms, str)]
    ranges = _parse_csv(args.ranges, float)
    if any(algorithm not in {'MHR', 'EMHR'} for algorithm in algorithms):
        print('algorithms must contain only MHR and EMHR', file=sys.stderr)
        return 2

    if args.output_dir is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        root = Path('results') / f'metrics_pilot_{stamp}'
    else:
        root = args.output_dir
    if root.exists() and any(root.iterdir()):
        print(f'refusing to overwrite non-empty output directory: {root}', file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)

    base_config = SimulationConfig.from_json(args.config)
    summaries: list[dict[str, Any]] = []
    fairness_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for seed in seeds:
        config = replace(base_config, seed=seed)
        for algorithm in algorithms:
            for range_m in ranges:
                scenario = f'{algorithm}_R{range_m:g}m_seed{seed}'
                run_dir = root / scenario
                print(f'[RUN] {scenario} T={args.duration:g}s')
                try:
                    simulation = Simulation(
                        config,
                        current_range_m=range_m,
                        routing_algorithm=algorithm,
                        quiet=True,
                        csv_log_path=run_dir / 'timeseries.csv',
                        seed=seed,
                    )
                    fingerprint = _fairness_fingerprint(simulation)
                    simulation.run_for(args.duration)
                    simulation.export_results(run_dir)
                    validation = validate_run(run_dir)
                    manifest_path = run_dir / 'run_manifest.json'
                    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                    if 'validation.json' not in manifest['generated_files']:
                        manifest['generated_files'].append('validation.json')
                    manifest['validation_passed'] = validation['passed']
                    manifest_path.write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False)
                        + '\n',
                        encoding='utf-8',
                    )
                    metrics = simulation.get_metrics()
                    summaries.append(
                        {
                            'scenario': scenario,
                            'algorithm': algorithm,
                            'range_m': range_m,
                            'seed': seed,
                            'requested_duration_s': args.duration,
                            'actual_duration_s': metrics['measurement_duration_s'],
                            'generated_packets': metrics['generated_packets'],
                            'delivered_packets': metrics['delivered_packets'],
                            'dropped_packets': metrics['dropped_packets'],
                            'pending_packets': metrics['pending_packets'],
                            'pdr_percent': metrics['pdr_percent'],
                            'throughput_bps': metrics['throughput_bps'],
                            'goodput_bps': metrics['goodput_bps'],
                            'average_hops': metrics['average_hops'],
                            'average_end_to_end_delay_s': (
                                metrics['average_end_to_end_delay_s']
                            ),
                            'fnd_s': metrics['fnd_s'],
                            'hnd_s': metrics['hnd_s'],
                            'lnd_s': metrics['lnd_s'],
                            'functional_network_death_s': (
                                metrics['functional_network_death_s']
                            ),
                            'validation_passed': validation['passed'],
                            'output_dir': str(run_dir),
                        }
                    )
                    fairness_rows.append(
                        {
                            'scenario': scenario,
                            'algorithm': algorithm,
                            'range_m': range_m,
                            'seed': seed,
                            'fingerprint': fingerprint,
                        }
                    )
                    if not validation['passed']:
                        failures.append(
                            {'scenario': scenario, 'reason': 'validation failed'}
                        )
                except Exception as exc:
                    failures.append({'scenario': scenario, 'reason': repr(exc)})
                    print(f'[FAIL] {scenario}: {exc}', file=sys.stderr)

    _write_csv(root / 'pilot_summary.csv', summaries)

    fingerprints_by_seed_range: dict[tuple[int, float], set[str]] = {}
    for row in fairness_rows:
        key = (int(row['seed']), float(row['range_m']))
        fingerprints_by_seed_range.setdefault(key, set()).add(row['fingerprint'])
    for row in fairness_rows:
        key = (int(row['seed']), float(row['range_m']))
        row['fair_across_algorithms'] = len(fingerprints_by_seed_range[key]) == 1
        if not row['fair_across_algorithms']:
            failures.append(
                {
                    'scenario': row['scenario'],
                    'reason': 'topology/traffic fairness fingerprint mismatch',
                }
            )
    _write_csv(root / 'fairness_checks.csv', fairness_rows)

    controlled_dir = root / 'controlled_lifetime_run'
    controlled_config = replace(
        base_config,
        num_sensors=4,
        num_sinks=1,
        seed=42,
    )
    controlled_network = _controlled_lifetime_network(controlled_config)
    controlled_simulation = Simulation(
        controlled_network,
        routing_algorithm='MHR',
        quiet=True,
        csv_log_path=controlled_dir / 'timeseries.csv',
        seed=42,
    )

    def scheduled_deaths():
        previous_time = 0.0
        for death_time, node_id in [
            (2.0, 'relay'),
            (4.0, 'sensor_1'),
            (6.0, 'sensor_2'),
            (8.0, 'sensor_3'),
        ]:
            yield controlled_simulation.env.timeout(death_time - previous_time)
            sensor = controlled_network.sensors[node_id]
            bits = controlled_config.packet_size_bytes * 8
            distance = (
                (sensor.energy_j - controlled_simulation.radio.e_elec * bits)
                / (controlled_simulation.radio.e_mp * bits)
            ) ** 0.25
            controlled_simulation.radio.attempt_transmission(
                sensor,
                controlled_network.sinks['sink_00'],
                controlled_config.packet_size_bytes,
                distance,
                sim_time_s=float(controlled_simulation.env.now),
                packet_id=f'controlled_death_{node_id}',
            )
            previous_time = death_time

    controlled_simulation.env.process(scheduled_deaths())
    controlled_simulation.run_for(9.0)
    controlled_simulation.export_results(controlled_dir)
    controlled_validation = validate_run(controlled_dir)
    controlled_manifest_path = controlled_dir / 'run_manifest.json'
    controlled_manifest = json.loads(
        controlled_manifest_path.read_text(encoding='utf-8')
    )
    controlled_manifest['data_classification'] = (
        'controlled_test_fixture_not_450_sensor_pilot'
    )
    controlled_manifest['validation_passed'] = controlled_validation['passed']
    controlled_manifest['generated_files'].append('validation.json')
    controlled_manifest_path.write_text(
        json.dumps(
            controlled_manifest,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + '\n',
        encoding='utf-8',
    )
    if not controlled_validation['passed']:
        failures.append(
            {'scenario': 'controlled_lifetime_run', 'reason': 'validation failed'}
        )
    controlled_rows = [
        {
            'node_id': event['node_id'],
            'death_time_s': event['death_time_s'],
        }
        for event in controlled_simulation.radio.death_events
    ]
    _write_csv(root / 'controlled_lifetime_fixture.csv', controlled_rows)
    controlled_result = controlled_simulation.get_metrics()
    controlled_result.update({
        'data_classification': 'controlled_test_fixture_not_450_sensor_pilot',
        'observation_end_s': 9.0,
        'run_directory': str(controlled_dir),
        'validation_passed': controlled_validation['passed'],
    })
    (root / 'controlled_lifetime_metrics.json').write_text(
        json.dumps(controlled_result, indent=2, allow_nan=False) + '\n',
        encoding='utf-8',
    )

    pilot_manifest = {
        'data_classification': 'pilot_not_main_experiment',
        'requested_scenarios': len(seeds) * len(algorithms) * len(ranges),
        'completed_scenarios': len(summaries),
        'seeds': seeds,
        'algorithms': algorithms,
        'ranges_m': ranges,
        'duration_s': args.duration,
        'minimum_main_experiment_seeds_per_configuration': 30,
        'controlled_lifetime_run': str(controlled_dir),
        'controlled_lifetime_validation_passed': controlled_validation['passed'],
        'failures': failures,
    }
    (root / 'pilot_manifest.json').write_text(
        json.dumps(pilot_manifest, indent=2, allow_nan=False) + '\n',
        encoding='utf-8',
    )

    if failures or len(summaries) != pilot_manifest['requested_scenarios']:
        print(f'Pilot failed; see {root / "pilot_manifest.json"}', file=sys.stderr)
        return 1
    print(f'Pilot PASS: {len(summaries)} scenarios -> {root}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
