'''Plot validated WSN pilot outputs with source-data CSV files.'''

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open('r', newline='', encoding='utf-8') as file_handle:
        return list(csv.DictReader(file_handle))


def _optional_float(value: str) -> float | None:
    return None if value == '' else float(value)


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


def _validated_summary(root: Path) -> list[dict[str, str]]:
    rows = _read_csv(root / 'pilot_summary.csv')
    for row in rows:
        validation_path = Path(row['output_dir']) / 'validation.json'
        validation = json.loads(validation_path.read_text(encoding='utf-8'))
        if not validation.get('passed'):
            raise ValueError(f'unvalidated scenario: {row["scenario"]}')
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Plot a validated WSN metrics pilot.')
    parser.add_argument('pilot_dir', type=Path)
    parser.add_argument('--output-dir', type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.pilot_dir
    output = args.output_dir or root / 'figures'
    output.mkdir(parents=True, exist_ok=True)
    try:
        summary = _validated_summary(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'PLOT ERROR: {exc}', file=sys.stderr)
        return 1
    seeds = sorted({int(row['seed']) for row in summary})
    subtitle = f'450-sensor pilot; seeds={seeds}; runs={len(summary)}'
    colors = {'MHR': 'tab:blue', 'EMHR': 'tab:orange'}

    alive_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    for row in summary:
        samples = _read_csv(Path(row['output_dir']) / 'timeseries.csv')
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
        for algorithm in sorted({row['algorithm'] for row in summary}):
            selected = [row for row in summary if row['algorithm'] == algorithm]
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
                        label=f'{algorithm} {display}',
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

    controlled_path = root / 'controlled_lifetime_run' / 'node_deaths.csv'
    controlled_validation_path = (
        root / 'controlled_lifetime_run' / 'validation.json'
    )
    if controlled_path.exists():
        controlled_validation = json.loads(
            controlled_validation_path.read_text(encoding='utf-8')
        )
        if not controlled_validation.get('passed'):
            print('PLOT ERROR: controlled lifetime run did not validate', file=sys.stderr)
            return 1
        controlled = _read_csv(controlled_path)
        controlled_metrics = json.loads(
            (root / 'controlled_lifetime_run' / 'metrics.json').read_text(
                encoding='utf-8'
            )
        )
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
        'pilot_directory': str(root),
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
