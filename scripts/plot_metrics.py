'''Plot validated WSN pilot outputs with source-data CSV files.'''

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    from scripts.validate_metrics import ABSOLUTE_TOLERANCE, validate_run
except ModuleNotFoundError:  # Direct execution: python scripts/plot_metrics.py
    from validate_metrics import ABSOLUTE_TOLERANCE, validate_run


SUMMARY_FIELDS = {
    'scenario', 'algorithm', 'range_m', 'seed', 'requested_duration_s',
    'actual_duration_s', 'generated_packets', 'delivered_packets',
    'dropped_packets', 'pending_packets', 'pdr_percent', 'throughput_bps',
    'goodput_bps', 'average_hops', 'average_end_to_end_delay_s', 'fnd_s',
    'hnd_s', 'lnd_s', 'functional_network_death_s', 'validation_passed',
    'output_dir',
}

SUMMARY_METRICS = (
    'actual_duration_s', 'generated_packets', 'delivered_packets',
    'dropped_packets', 'pending_packets', 'pdr_percent', 'throughput_bps',
    'goodput_bps', 'average_hops', 'average_end_to_end_delay_s', 'fnd_s',
    'hnd_s', 'lnd_s', 'functional_network_death_s',
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open('r', newline='', encoding='utf-8') as file_handle:
        reader = csv.DictReader(file_handle)
        if reader.fieldnames is None:
            raise ValueError(f'{path}: missing CSV header')
        return list(reader)


def _optional_float(value: Any) -> float | None:
    if value is None or value == '':
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'non-finite numeric value: {value!r}')
    return result


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open('w', newline='', encoding='utf-8') as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=fields,
            extrasaction='ignore',
        )
        writer.writeheader()
        writer.writerows(rows)


def _save_figure(figure, path: Path) -> None:
    figure.tight_layout()
    figure.savefig(path, dpi=160, bbox_inches='tight')
    plt.close(figure)


def _resolve_run_path(root: Path, row: dict[str, str]) -> Path:
    scenario = row['scenario'].strip()
    declared = row['output_dir'].strip()
    if not scenario or not declared:
        raise ValueError('summary scenario and output_dir must not be empty')
    declared_name = PureWindowsPath(declared.replace('/', '\\')).name
    if declared_name != scenario:
        raise ValueError(
            f'{scenario}: output_dir basename {declared_name!r} does not match scenario'
        )
    run_path = root / scenario
    if not run_path.is_dir():
        raise ValueError(f'{scenario}: run directory not found under pilot root: {run_path}')
    return run_path


def _same_optional_number(left: Any, right: Any) -> bool:
    parsed_left = _optional_float(left)
    parsed_right = _optional_float(right)
    if parsed_left is None or parsed_right is None:
        return parsed_left is None and parsed_right is None
    return math.isclose(
        parsed_left, parsed_right, rel_tol=0.0, abs_tol=ABSOLUTE_TOLERANCE
    )


def _check_summary_row(
    row: dict[str, Any], metrics: dict[str, Any], manifest: dict[str, Any]
) -> None:
    scenario = row['scenario']
    metadata_pairs = {
        'algorithm': manifest['routing_algorithm'],
        'range_m': manifest['communication_range_m'],
        'seed': manifest['topology_seed'],
        'requested_duration_s': manifest['requested_duration_s'],
    }
    metric_pairs = {
        'actual_duration_s': metrics['measurement_duration_s'],
        **{name: metrics[name] for name in SUMMARY_METRICS if name != 'actual_duration_s'},
    }
    mismatches: list[str] = []
    if row['algorithm'] != str(metadata_pairs['algorithm']):
        mismatches.append('algorithm')
    for name in ('range_m', 'seed', 'requested_duration_s'):
        if not _same_optional_number(row[name], metadata_pairs[name]):
            mismatches.append(name)
    for name, expected in metric_pairs.items():
        if not _same_optional_number(row[name], expected):
            mismatches.append(name)
    if row['validation_passed'].strip().lower() != 'true':
        mismatches.append('validation_passed')
    if mismatches:
        raise ValueError(
            f'{scenario}: pilot_summary.csv does not match current run data for '
            f'{sorted(set(mismatches))}'
        )


def _validated_summary(root: Path) -> list[dict[str, Any]]:
    rows = _read_csv(root / 'pilot_summary.csv')
    if not rows:
        raise ValueError('pilot_summary.csv contains no requested runs')
    missing = sorted(SUMMARY_FIELDS - set(rows[0]))
    if missing:
        raise ValueError(f'pilot_summary.csv missing columns {missing}')
    scenarios = [row['scenario'] for row in rows]
    if len(scenarios) != len(set(scenarios)):
        raise ValueError('pilot_summary.csv contains duplicate scenarios')

    pilot_manifest_path = root / 'pilot_manifest.json'
    if pilot_manifest_path.exists():
        pilot_manifest = json.loads(pilot_manifest_path.read_text(encoding='utf-8'))
        requested = int(pilot_manifest['requested_scenarios'])
        completed = int(pilot_manifest['completed_scenarios'])
        if len(rows) != requested or completed != requested:
            raise ValueError(
                f'pilot run list incomplete: summary={len(rows)}, completed={completed}, '
                f'requested={requested}'
            )

    for row in rows:
        run_path = _resolve_run_path(root, row)
        validation = validate_run(run_path, write_report=False)
        if not validation['passed']:
            failed = [
                check['metric'] for check in validation['checks'] if not check['passed']
            ]
            raise ValueError(
                f'{row["scenario"]}: current raw data failed validation checks {failed}'
            )
        metrics = json.loads((run_path / 'metrics.json').read_text(encoding='utf-8'))
        manifest = json.loads((run_path / 'run_manifest.json').read_text(encoding='utf-8'))
        _check_summary_row(row, metrics, manifest)
        row['_run_path'] = run_path
        row['_metrics'] = metrics
        row['_manifest'] = manifest
    return rows


def _validated_controlled_run(root: Path) -> tuple[list[dict[str, str]], dict[str, Any]] | None:
    run_path = root / 'controlled_lifetime_run'
    if not run_path.exists():
        return None
    if not (run_path / 'topology_edges.csv').exists():
        print(
            'PLOT WARNING: legacy controlled_lifetime_run has no exported topology; '
            'skipping the controlled-only figure',
            file=sys.stderr,
        )
        return None
    validation = validate_run(run_path, write_report=False)
    if not validation['passed']:
        failed = [check['metric'] for check in validation['checks'] if not check['passed']]
        raise ValueError(f'controlled_lifetime_run failed validation checks {failed}')
    deaths = _read_csv(run_path / 'node_deaths.csv')
    metrics = json.loads((run_path / 'metrics.json').read_text(encoding='utf-8'))
    return deaths, metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Plot a validated WSN metrics pilot.')
    parser.add_argument('pilot_dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.pilot_dir.resolve()
    output = args.output_dir or root / 'figures'
    try:
        summary = _validated_summary(root)
        controlled_data = _validated_controlled_run(root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f'PLOT ERROR: {exc}', file=sys.stderr)
        return 1
    output.mkdir(parents=True, exist_ok=True)
    seeds = sorted({int(row['seed']) for row in summary})
    sensor_counts = sorted({int(row['_metrics']['total_sensors']) for row in summary})
    durations = sorted({float(row['_metrics']['measurement_duration_s']) for row in summary})
    sensors_label = '/'.join(str(value) for value in sensor_counts)
    duration_label = '/'.join(f'{value:g}' for value in durations)
    subtitle = (
        f'{sensors_label}-sensor pilot; T={duration_label}s; '
        f'seeds={seeds}; runs={len(summary)}'
    )
    colors = {'MHR': 'tab:blue', 'EMHR': 'tab:orange'}

    alive_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    for row in summary:
        samples = _read_csv(row['_run_path'] / 'timeseries.csv')
        x = [float(sample['time_s']) for sample in samples]
        y = [int(sample['alive_sensors']) for sample in samples]
        label = f'{row["algorithm"]} R={float(row["range_m"]):g} seed={row["seed"]}'
        axis.plot(
            x,
            y,
            label=label,
            color=colors.get(row['algorithm']),
            linestyle='-' if row['algorithm'] == 'MHR' else '--',
            alpha=0.8,
        )
        for sample in samples:
            alive_source.append(
                {
                    'scenario': row['scenario'],
                    'algorithm': row['algorithm'],
                    'range_m': row['range_m'],
                    'seed': row['seed'],
                    'time_s': sample['time_s'],
                    'alive_sensors': sample['alive_sensors'],
                }
            )
    axis.set(
        title=f'Alive sensors over simulation time\n{subtitle}',
        xlabel='Simulation time (s)',
        ylabel='Alive sensors (count)',
    )
    axis.grid(alpha=0.25)
    axis.legend(fontsize=7, ncol=2)
    _save_figure(figure, output / '01_alive_sensors_over_time.png')
    _write_csv(
        output / '01_alive_sensors_over_time.csv',
        alive_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'time_s', 'alive_sensors'],
    )

    def metric_plot(
        filename: str,
        metrics: list[tuple[str, str]],
        title: str,
        ylabel: str,
    ) -> None:
        source_rows: list[dict[str, Any]] = []
        figure, axis = plt.subplots(figsize=(8, 5))
        groups = sorted({(row['algorithm'], int(row['seed'])) for row in summary})
        for algorithm, seed in groups:
            selected = [
                row for row in summary
                if row['algorithm'] == algorithm and int(row['seed']) == seed
            ]
            selected.sort(key=lambda row: float(row['range_m']))
            for key, display in metrics:
                points = [
                    (float(row['range_m']), _optional_float(row[key]))
                    for row in selected
                ]
                observed = [(x, y) for x, y in points if y is not None]
                if observed:
                    axis.plot(
                        [point[0] for point in observed],
                        [point[1] for point in observed],
                        marker='o',
                        label=f'{algorithm} {display} seed={seed}',
                        color=colors.get(algorithm),
                        linestyle='-' if key == metrics[0][0] else '--',
                    )
                for row, (range_m, value) in zip(selected, points):
                    source_rows.append(
                        {
                            'scenario': row['scenario'],
                            'algorithm': algorithm,
                            'range_m': range_m,
                            'seed': row['seed'],
                            'metric': key,
                            'value': value,
                        }
                    )
        axis.set(title=f'{title}\n{subtitle}', xlabel='Communication range R (m)', ylabel=ylabel)
        axis.grid(alpha=0.25)
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend()
        else:
            axis.text(
                0.5,
                0.5,
                'No observed values by the measurement end',
                ha='center',
                va='center',
                transform=axis.transAxes,
            )
        _save_figure(figure, output / f'{filename}.png')
        _write_csv(
            output / f'{filename}.csv',
            source_rows,
            ['scenario', 'algorithm', 'range_m', 'seed', 'metric', 'value'],
        )

    metric_plot(
        '02_pdr_by_range',
        [('pdr_percent', 'PDR')],
        'Packet delivery ratio by communication range',
        'PDR (%)',
    )
    metric_plot(
        '03_throughput_goodput_by_range',
        [('throughput_bps', 'throughput'), ('goodput_bps', 'goodput')],
        'Sink throughput and goodput by communication range',
        'Rate (bit/s)',
    )
    metric_plot(
        '04_average_hops_by_range',
        [('average_hops', 'average hops')],
        'Average actual delivered-path hops by communication range',
        'Average hops (hop)',
    )
    metric_plot(
        '05_average_delay_by_range',
        [('average_end_to_end_delay_s', 'end-to-end delay')],
        'Average end-to-end delay by communication range',
        'Average delay (s)',
    )
    metric_plot(
        '06_pilot_lifetime_milestones',
        [
            ('fnd_s', 'FND'),
            ('hnd_s', 'HND'),
            ('lnd_s', 'LND'),
            ('functional_network_death_s', 'functional death'),
        ],
        'Observed lifetime milestones by communication range',
        'Simulation time (s)',
    )

    if controlled_data is not None:
        controlled, controlled_metrics = controlled_data
        figure, axis = plt.subplots(figsize=(7, 4))
        x = [float(row['death_time_s']) for row in controlled]
        y = list(range(1, len(controlled) + 1))
        axis.step(x, y, where='post', marker='o', color='tab:red')
        milestone_styles = [
            ('fnd_s', 'FND', 'tab:blue'),
            ('hnd_s', 'HND', 'tab:green'),
            ('lnd_s', 'LND', 'tab:purple'),
            (
                'functional_network_death_s',
                'Functional death',
                'tab:orange',
            ),
        ]
        for key, label, color in milestone_styles:
            value = controlled_metrics.get(key)
            if value is not None:
                axis.axvline(
                    float(value),
                    color=color,
                    linestyle='--',
                    alpha=0.8,
                    label=f'{label}={float(value):g}s',
                )
        axis.set(
            title='Controlled lifetime fixture (not 450-sensor pilot)',
            xlabel='Simulation time (s)',
            ylabel='Cumulative dead sensors (count)',
        )
        axis.grid(alpha=0.25)
        axis.legend(fontsize=8)
        _save_figure(figure, output / '07_controlled_lifetime_fixture.png')
        controlled_source = [
            {
                'record_type': 'node_death',
                'label': row['node_id'],
                'time_s': row['death_time_s'],
            }
            for row in controlled
        ]
        controlled_source.extend(
            {
                'record_type': 'milestone',
                'label': label,
                'time_s': controlled_metrics.get(key),
            }
            for key, label, _ in milestone_styles
        )
        _write_csv(
            output / '07_controlled_lifetime_fixture.csv',
            controlled_source,
            ['record_type', 'label', 'time_s'],
        )

    manifest = {
        'pilot_directory': '.',
        'validated_runs': len(summary),
        'seeds': seeds,
        'classification': 'pilot_not_main_experiment',
        'figures': sorted(path.name for path in output.glob('*.png')),
        'source_tables': sorted(path.name for path in output.glob('*.csv')),
    }
    (output / 'plot_manifest.json').write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + '\n',
        encoding='utf-8',
    )
    print(f'Created {len(manifest["figures"])} figures in {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
