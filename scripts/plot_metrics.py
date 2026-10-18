'''Plot validated WSN pilot outputs with source-data CSV files.'''

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
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
    'goodput_bps', 'offered_rate_bps', 'configured_rate_bps',
    'energy_per_delivered_bit_j', 'average_hops', 'average_end_to_end_delay_s',
    'fnd_s', 'hnd_s', 'lnd_s', 'functional_network_death_s',
    'delivered_bits_at_fnd', 'delivered_bits_at_hnd', 'delivered_bits_at_lnd',
    'relay_jain_fairness', 'route_recompute_count', 'route_change_count',
    'route_failure_count', 'validation_passed', 'output_dir',
}

SUMMARY_METRICS = (
    'actual_duration_s', 'generated_packets', 'delivered_packets',
    'dropped_packets', 'pending_packets', 'pdr_percent', 'throughput_bps',
    'goodput_bps', 'offered_rate_bps', 'configured_rate_bps',
    'energy_per_delivered_bit_j', 'average_hops', 'average_end_to_end_delay_s',
    'fnd_s', 'hnd_s', 'lnd_s', 'functional_network_death_s',
    'delivered_bits_at_fnd', 'delivered_bits_at_hnd', 'delivered_bits_at_lnd',
    'relay_jain_fairness', 'route_recompute_count', 'route_change_count',
    'route_failure_count',
)

FIGURE_BASENAMES = [
    '01_alive_sensors_over_time',
    '02_pdr_by_range',
    '03_throughput_goodput_by_range',
    '04_average_hops_by_range',
    '05_average_delay_by_range',
    '06_pilot_lifetime_milestones',
    '07_controlled_lifetime_fixture',
    '08_residual_energy_over_time',
    '09_energy_feasible_ratio_over_time',
    '10_cumulative_delivered_bits_over_time',
    '11_dropped_packets_by_reason',
    '12_energy_per_delivered_bit_by_range',
]


def _clean_managed_plot_outputs(output: Path) -> None:
    '''Remove only files owned by this plotter so stale figures cannot survive.'''
    for basename in FIGURE_BASENAMES:
        for suffix in ('.png', '.csv'):
            path = output / f'{basename}{suffix}'
            if path.exists():
                path.unlink()
    manifest = output / 'plot_manifest.json'
    if manifest.exists():
        manifest.unlink()


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


def _validated_controlled_run(
    root: Path,
) -> tuple[list[dict[str, str]], dict[str, Any], dict[str, Any]] | None:
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
    manifest = json.loads((run_path / 'run_manifest.json').read_text(encoding='utf-8'))
    return deaths, metrics, manifest


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
    _clean_managed_plot_outputs(output)
    created_figures: list[str] = []
    created_tables: list[str] = []
    seeds = sorted({int(row['seed']) for row in summary})
    sensor_counts = sorted({int(row['_metrics']['total_sensors']) for row in summary})
    durations = sorted({float(row['_metrics']['measurement_duration_s']) for row in summary})
    sensors_label = '/'.join(str(value) for value in sensor_counts)
    duration_label = '/'.join(f'{value:g}' for value in durations)
    subtitle = (
        f'{sensors_label}-sensor pilot; interval [0,{duration_label}s); '
        f'seeds={seeds}; runs={len(summary)}'
    )
    algorithm_colors = {'MHR': 'tab:blue', 'EMHR': 'tab:orange'}
    algorithm_lines = {'MHR': '-', 'EMHR': '--'}
    algorithms_label = '/'.join(sorted({str(row['algorithm']) for row in summary}))
    range_values = sorted({float(row['range_m']) for row in summary})
    ranges_label = '/'.join(f'{value:g}' for value in range_values)
    palette = ['tab:blue', 'tab:green', 'tab:red', 'tab:purple', 'tab:brown']
    marker_values = ['o', 's', '^', 'D', 'v']
    range_colors = {value: palette[index % len(palette)] for index, value in enumerate(range_values)}
    range_markers = {value: marker_values[index % len(marker_values)] for index, value in enumerate(range_values)}

    def save_plot(figure: Any, basename: str) -> None:
        name = f'{basename}.png'
        _save_figure(figure, output / name)
        created_figures.append(name)

    def save_source(
        basename: str, rows: list[dict[str, Any]], fields: list[str]
    ) -> None:
        name = f'{basename}.csv'
        _write_csv(output / name, rows, fields)
        created_tables.append(name)

    # Figure 01: use exact death-event timestamps and a step representation.
    alive_source: list[dict[str, Any]] = []
    alive_curves: list[tuple[tuple[float, int], ...]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    for row in summary:
        events = _read_csv(row['_run_path'] / 'reachability_events.csv')
        duration = float(row['_metrics']['measurement_duration_s'])
        points = [(float(event['time_s']), int(event['alive_sensors'])) for event in events]
        if not points or points[-1][0] < duration:
            points.append((duration, points[-1][1]))
        alive_curves.append(tuple(points))
        range_m = float(row['range_m'])
        label = (
            f'{row["algorithm"]} R={range_m:g}m seed={row["seed"]}; '
            f'end={points[-1][1]}'
        )
        axis.step(
            [point[0] for point in points],
            [point[1] for point in points],
            where='post',
            label=label,
            color=range_colors[range_m],
            linestyle=algorithm_lines[row['algorithm']],
            marker=range_markers[range_m],
            linewidth=1.5,
            alpha=0.82,
        )
        for time_s, alive in points:
            alive_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'],
                'measurement_duration_s': duration, 'time_s': time_s,
                'alive_sensors': alive, 'sample_source': 'reachability_event_or_end',
            })
    overlap_counts = Counter(alive_curves)
    largest_overlap = max(overlap_counts.values(), default=1)
    if largest_overlap > 1:
        final_alive = alive_curves[0][-1][1]
        axis.text(
            0.99, 0.03,
            f'{largest_overlap} curves overlap; end state: {final_alive} alive sensors',
            ha='right', va='bottom', transform=axis.transAxes, fontsize=8,
            bbox={'facecolor': 'white', 'alpha': 0.8, 'edgecolor': '0.8'},
        )
    axis.set(
        title=f'Alive sensors over simulation time\n{subtitle}',
        xlabel='Simulation time (s)', ylabel='Alive sensors (count)',
    )
    axis.grid(alpha=0.25)
    axis.legend(fontsize=7, ncol=2)
    save_plot(figure, '01_alive_sensors_over_time')
    save_source(
        '01_alive_sensors_over_time', alive_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'measurement_duration_s',
         'time_s', 'alive_sensors', 'sample_source'],
    )

    groups = sorted({(row['algorithm'], int(row['seed'])) for row in summary})

    # Figure 02: full 0-100% scale plus exact counts and labels.
    pdr_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(8, 5))
    for algorithm, seed in groups:
        selected = sorted(
            (row for row in summary if row['algorithm'] == algorithm and int(row['seed']) == seed),
            key=lambda row: float(row['range_m']),
        )
        points = [
            (float(row['range_m']), _optional_float(row['pdr_percent']))
            for row in selected
        ]
        observed = [(range_m, value) for range_m, value in points if value is not None]
        if observed:
            axis.plot(
                [point[0] for point in observed], [point[1] for point in observed],
                marker='o' if algorithm == 'MHR' else 's',
                linestyle=(algorithm_lines[algorithm] if len(observed) == len(points) else 'None'),
                color=algorithm_colors[algorithm], label=f'{algorithm} seed={seed}',
            )
        for row, (range_m, value) in zip(selected, points):
            generated = int(row['generated_packets'])
            delivered = int(row['delivered_packets'])
            dropped = int(row['dropped_packets'])
            pending = int(row['pending_packets'])

            if generated != delivered + dropped + pending:
                raise ValueError(
                    f"{row['scenario']}: packet conservation failed: "
                    f"generated={generated}, delivered={delivered}, "
                    f"dropped={dropped}, pending={pending}"
                )
            if value is not None:
                if value == 0.0:
                    y_offset = 18 if algorithm == 'MHR' else 48
                    vertical_alignment = 'bottom'
                else:
                    y_offset = -18 if algorithm == 'MHR' else -48
                    vertical_alignment = 'top'
                x_offset = 28 if range_m == min(range_values) else (
                    -28 if range_m == max(range_values) else 0
                )
                axis.annotate(
                    (
                        f'{value:.6f}%\n'
                        f'{delivered}/{generated}\n'
                        f'dropped={dropped}; pending={pending}'
                    ),
                    (range_m, value), xytext=(x_offset, y_offset),
                    textcoords='offset points',
                    ha='center', va=vertical_alignment, fontsize=7,
                )
            pdr_source.append({
                'scenario': row['scenario'], 'algorithm': algorithm,
                'range_m': range_m, 'seed': seed,
                'measurement_duration_s': row['actual_duration_s'],
                'generated_packets': generated, 'delivered_packets': delivered,
                'dropped_packets': dropped, 'pending_packets': pending,
                'pdr_percent': value,
                'status': 'observed' if value is not None else 'not_observed',
            })
    axis.set(
        title=f'Packet delivery ratio by communication range\n{subtitle}',
        xlabel='Communication range R (m)', ylabel='PDR (%)', ylim=(0, 101),
    )
    axis.grid(alpha=0.25)
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend()
    else:
        axis.text(
            0.5, 0.5, f'PDR not observed in [0,{duration_label}s): no packets generated',
            ha='center', va='center', transform=axis.transAxes,
        )
    save_plot(figure, '02_pdr_by_range')
    save_source(
        '02_pdr_by_range', pdr_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'measurement_duration_s',
         'generated_packets', 'delivered_packets', 'dropped_packets',
         'pending_packets', 'pdr_percent', 'status'],
    )

    # Figure 03: throughput/goodput remain separate series even when they overlap.
    rate_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(8, 5))
    all_equal = True
    for algorithm, seed in groups:
        selected = sorted(
            (row for row in summary if row['algorithm'] == algorithm and int(row['seed']) == seed),
            key=lambda row: float(row['range_m']),
        )
        for key, display, marker, line in (
            ('throughput_bps', 'throughput', 'o', '-'),
            ('goodput_bps', 'goodput', 'x', ':'),
        ):
            x = [float(row['range_m']) for row in selected]
            y = [float(row[key]) for row in selected]
            axis.plot(
                x, y, marker=marker, linestyle=line,
                color=algorithm_colors[algorithm],
                label=f'{algorithm} {display} seed={seed}',
            )
            for row, range_m, value in zip(selected, x, y):
                rate_source.append({
                    'scenario': row['scenario'], 'algorithm': algorithm,
                    'range_m': range_m, 'seed': seed,
                    'measurement_duration_s': row['actual_duration_s'],
                    'metric': key, 'rate_bps': value,
                    'packet_size_bytes': row['_manifest']['configuration']['packet_size_bytes'],
                    'payload_size_bytes': row['_manifest']['configuration']['payload_size_bytes'],
                })
        all_equal = all_equal and all(
            _same_optional_number(row['throughput_bps'], row['goodput_bps'])
            for row in selected
        )
    max_rate_diff = max(
        (abs(float(row['throughput_bps']) - float(row['goodput_bps'])) for row in summary),
        default=0.0,
    )
    if all_equal:
        size_pairs = {
            (
                int(row['_manifest']['configuration']['packet_size_bytes']),
                int(row['_manifest']['configuration']['payload_size_bytes']),
            )
            for row in summary
        }
        size_text = '/'.join(
            f'{packet} B packet = {payload} B payload'
            for packet, payload in sorted(size_pairs)
        )
        axis.text(
            0.02, 0.03,
            f'Throughput and goodput overlap (diff = 0 bit/s): {size_text}.',
            transform=axis.transAxes, fontsize=8,
            bbox={'facecolor': 'white', 'alpha': 0.8, 'edgecolor': '0.8'},
        )
    else:
        axis.text(
            0.02, 0.03,
            f'Max rate difference: {max_rate_diff:.2f} bit/s.',
            transform=axis.transAxes, fontsize=8,
            bbox={'facecolor': 'white', 'alpha': 0.8, 'edgecolor': '0.8'},
        )
    axis.set(
        title=f'Sink throughput and goodput by communication range\n{subtitle}',
        xlabel='Communication range R (m)', ylabel='Rate (bit/s)',
    )
    max_rate = max(
        (
            float(row[key])
            for row in summary
            for key in ('throughput_bps', 'goodput_bps')
        ),
        default=0.0,
    )
    axis.set_ylim(0, max_rate * 1.05 if max_rate > 0 else 1.0)
    axis.grid(alpha=0.25)
    axis.legend(fontsize=8)
    save_plot(figure, '03_throughput_goodput_by_range')
    save_source(
        '03_throughput_goodput_by_range', rate_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'measurement_duration_s',
         'metric', 'rate_bps', 'packet_size_bytes', 'payload_size_bytes'],
    )

    def single_metric_plot(
        basename: str,
        metric_key: str,
        title: str,
        ylabel: str,
        output_field: str,
        multiplier: float = 1.0,
    ) -> None:
        source_rows: list[dict[str, Any]] = []
        figure, axis = plt.subplots(figsize=(8, 5))
        coordinate_counts: Counter[tuple[float, float]] = Counter()
        for algorithm, seed in groups:
            selected = sorted(
                (row for row in summary if row['algorithm'] == algorithm and int(row['seed']) == seed),
                key=lambda row: float(row['range_m']),
            )
            points = [
                (float(row['range_m']), float(row[metric_key]) * multiplier)
                for row in selected if _optional_float(row[metric_key]) is not None
            ]
            coordinate_counts.update(points)
            if points:
                axis.plot(
                    [point[0] for point in points], [point[1] for point in points],
                    marker='o' if algorithm == 'MHR' else 's',
                    linestyle=algorithm_lines[algorithm], color=algorithm_colors[algorithm],
                    label=f'{algorithm} seed={seed}',
                )
            for row in selected:
                value = _optional_float(row[metric_key])
                source_rows.append({
                    'scenario': row['scenario'], 'algorithm': algorithm,
                    'range_m': row['range_m'], 'seed': seed,
                    'measurement_duration_s': row['actual_duration_s'],
                    output_field: None if value is None else value * multiplier,
                    'status': 'observed' if value is not None else 'not_observed',
                })
        overlap_points = sum(1 for count in coordinate_counts.values() if count > 1)
        if overlap_points:
            axis.text(
                0.02, 0.03, f'{overlap_points} plotted coordinates contain overlapping runs',
                ha='left', va='bottom', transform=axis.transAxes, fontsize=8,
                bbox={'facecolor': 'white', 'alpha': 0.8, 'edgecolor': '0.8'},
            )
        axis.set(title=f'{title}\n{subtitle}', xlabel='Communication range R (m)', ylabel=ylabel)
        axis.grid(alpha=0.25)
        axis.legend(fontsize=8)
        save_plot(figure, basename)
        save_source(
            basename, source_rows,
            ['scenario', 'algorithm', 'range_m', 'seed', 'measurement_duration_s',
             output_field, 'status'],
        )

    single_metric_plot(
        '04_average_hops_by_range', 'average_hops',
        'Average actual hops of delivered packets (edges, not relays)',
        'Average actual path length (hop) [delivered packets only]', 'average_hops',
    )
    single_metric_plot(
        '05_average_delay_by_range', 'average_end_to_end_delay_s',
        'Average end-to-end delay of delivered packets',
        'Average end-to-end delay (ms) [delivered packets only]', 'average_end_to_end_delay_ms', 1000.0,
    )

    # Figure 06: never invent values or connect across missing observations.
    milestone_specs = [
        ('fnd_s', 'FND'), ('hnd_s', 'HND'), ('lnd_s', 'LND'),
        ('functional_network_death_s', 'Physical-connectivity lifetime'),
    ]
    lifetime_source: list[dict[str, Any]] = []
    observed_points: list[tuple[dict[str, Any], str, str, float]] = []
    for row in summary:
        for key, label in milestone_specs:
            value = _optional_float(row[key])
            status = 'observed' if value is not None else 'not_observed'
            lifetime_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': row['range_m'], 'seed': row['seed'],
                'measurement_duration_s': row['actual_duration_s'],
                'observation_interval': f'[0,{float(row["actual_duration_s"]):g} s)',
                'metric': key, 'status': status, 'time_s': value,
            })
            if value is not None:
                observed_points.append((row, key, label, value))
    figure, axis = plt.subplots(figsize=(9, 5))
    if not observed_points:
        axis.axis('off')
        intervals = sorted({item['observation_interval'] for item in lifetime_source})
        axis.text(
            0.5, 0.62, 'No pilot lifetime milestones were observed',
            ha='center', va='center', fontsize=15, weight='bold', transform=axis.transAxes,
        )
        axis.text(
            0.5, 0.45,
            f'FND · HND · LND · physical-connectivity lifetime\n'
            f'Not observed in {", ".join(intervals)}\n'
            f'{algorithms_label}; R={ranges_label} m; seeds={seeds}',
            ha='center', va='center', fontsize=11, transform=axis.transAxes,
            bbox={'facecolor': '#f3f4f6', 'edgecolor': '#9ca3af', 'pad': 12},
        )
        axis.set_title(f'Pilot lifetime status\n{subtitle}')
    else:
        metric_markers = {'fnd_s': 'o', 'hnd_s': 's', 'lnd_s': '^',
                          'functional_network_death_s': 'D'}
        for row, key, label, value in observed_points:
            axis.scatter(
                float(row['range_m']), value,
                marker=metric_markers[key], color=algorithm_colors[row['algorithm']],
                label=f'{row["algorithm"]} {label} seed={row["seed"]}',
            )
        missing = len(lifetime_source) - len(observed_points)
        axis.text(
            0.99, 0.03, f'{missing} missing milestone values are not plotted',
            ha='right', va='bottom', transform=axis.transAxes, fontsize=8,
        )
        axis.set(
            title=f'Observed pilot lifetime milestones (points only)\n{subtitle}',
            xlabel='Communication range R (m)', ylabel='Simulation time (s)',
        )
        axis.grid(alpha=0.25)
        handles, labels = axis.get_legend_handles_labels()
        unique = dict(zip(labels, handles))
        axis.legend(unique.values(), unique.keys(), fontsize=7)
    save_plot(figure, '06_pilot_lifetime_milestones')
    save_source(
        '06_pilot_lifetime_milestones', lifetime_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'measurement_duration_s',
         'observation_interval', 'metric', 'status', 'time_s'],
    )

    if controlled_data is not None:
        controlled, controlled_metrics, controlled_manifest = controlled_data
        controlled_duration = float(controlled_metrics['measurement_duration_s'])
        controlled_algorithm = str(controlled_manifest['routing_algorithm'])
        controlled_range = float(controlled_manifest['communication_range_m'])
        controlled_seed = int(controlled_manifest['topology_seed'])
        figure, axis = plt.subplots(figsize=(8, 5))
        death_times = [float(row['death_time_s']) for row in controlled]
        x = [0.0, *death_times, controlled_duration]
        y = [0, *range(1, len(controlled) + 1), len(controlled)]
        axis.step(x, y, where='post', marker='o', color='tab:red', label='Cumulative deaths')
        milestone_styles = [
            ('fnd_s', 'FND', 'tab:blue', '--'),
            ('hnd_s', 'HND', 'tab:green', '-.'),
            ('lnd_s', 'LND', 'tab:purple', ':'),
            ('functional_network_death_s', 'Physical-connectivity lifetime', 'tab:orange', (0, (3, 1, 1, 1))),
        ]
        for index, (key, label, color, line) in enumerate(milestone_styles):
            value = controlled_metrics.get(key)
            if value is not None:
                axis.axvline(
                    float(value), color=color, linestyle=line, alpha=0.9,
                    label=f'{label}={float(value):g}s',
                )
                axis.annotate(
                    label, (float(value), 0.15 + index * 0.33),
                    xytext=(3, 0), textcoords='offset points', rotation=90,
                    va='bottom', color=color, fontsize=7,
                )
        axis.set(
            title='Controlled 4-sensor lifetime test (not the 450-sensor pilot)\n'
                  'Intentional battery-depletion schedule validates milestone logic\n'
                  f'{controlled_algorithm}; R={controlled_range:g}m; '
                  f'seed={controlled_seed}; interval [0,{controlled_duration:g}s)',
            xlabel='Simulation time (s)', ylabel='Cumulative dead sensors (count)',
            xlim=(0, controlled_duration), ylim=(-0.1, len(controlled) + 0.5),
        )
        axis.grid(alpha=0.25)
        axis.legend(fontsize=7, ncol=2)
        save_plot(figure, '07_controlled_lifetime_fixture')
        controlled_source = [{
            'record_type': 'state', 'label': 'initial', 'time_s': 0.0,
            'cumulative_dead_sensors': 0, 'status': 'observed',
            'algorithm': controlled_algorithm, 'range_m': controlled_range,
            'seed': controlled_seed,
            'measurement_duration_s': controlled_duration,
        }]
        controlled_source.extend({
            'record_type': 'node_death', 'label': row['node_id'],
            'time_s': row['death_time_s'], 'cumulative_dead_sensors': index,
            'status': 'observed', 'algorithm': controlled_algorithm,
            'range_m': controlled_range, 'seed': controlled_seed,
            'measurement_duration_s': controlled_duration,
        } for index, row in enumerate(controlled, start=1))
        controlled_source.append({
            'record_type': 'state', 'label': 'observation_end',
            'time_s': controlled_duration, 'cumulative_dead_sensors': len(controlled),
            'status': 'observed', 'algorithm': controlled_algorithm,
            'range_m': controlled_range, 'seed': controlled_seed,
            'measurement_duration_s': controlled_duration,
        })
        controlled_source.extend({
            'record_type': 'milestone', 'label': label,
            'time_s': controlled_metrics.get(key), 'cumulative_dead_sensors': None,
            'status': ('observed' if controlled_metrics.get(key) is not None else 'not_observed'),
            'algorithm': controlled_algorithm, 'range_m': controlled_range,
            'seed': controlled_seed,
            'measurement_duration_s': controlled_duration,
        } for key, label, _, _ in milestone_styles)
        save_source(
            '07_controlled_lifetime_fixture', controlled_source,
            ['record_type', 'label', 'time_s', 'cumulative_dead_sensors', 'status',
             'algorithm', 'range_m', 'seed', 'measurement_duration_s'],
        )

    # Figure 08: Residual energy over time
    energy_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    for row in summary:
        timeseries = _read_csv(row['_run_path'] / 'timeseries.csv')
        points = [(float(entry['time_s']), float(entry['total_energy_j'])) for entry in timeseries]
        range_m = float(row['range_m'])
        axis.plot(
            [p[0] for p in points], [p[1] for p in points],
            label=f'{row["algorithm"]} R={range_m:g}m seed={row["seed"]}',
            color=range_colors[range_m],
            linestyle=algorithm_lines[row['algorithm']],
            linewidth=1.5,
        )
        for time_s, energy in points:
            energy_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'],
                'time_s': time_s, 'total_energy_j': energy,
            })
    axis.set(
        title=f'Residual network energy over simulation time\n{subtitle}',
        xlabel='Simulation time (s)', ylabel='Residual energy (J)',
    )
    axis.grid(alpha=0.25)
    axis.legend(fontsize=7, ncol=2)
    save_plot(figure, '08_residual_energy_over_time')
    save_source(
        '08_residual_energy_over_time', energy_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'time_s', 'total_energy_j'],
    )

    # Figure 09: Energy feasible ratio over time
    feasibility_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    for row in summary:
        timeseries = _read_csv(row['_run_path'] / 'timeseries.csv')
        points = [
            (float(entry['time_s']), float(entry['energy_feasible_ratio']) * 100.0, int(entry['energy_feasible_sensors']))
            for entry in timeseries if 'energy_feasible_ratio' in entry
        ]
        range_m = float(row['range_m'])
        if points:
            axis.plot(
                [p[0] for p in points], [p[1] for p in points],
                label=f'{row["algorithm"]} R={range_m:g}m seed={row["seed"]}',
                color=range_colors[range_m],
                linestyle=algorithm_lines[row['algorithm']],
                linewidth=1.5,
            )
        for time_s, ratio, count in points:
            feasibility_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'],
                'time_s': time_s, 'energy_feasible_sensors': count,
                'energy_feasible_ratio': ratio / 100.0,
            })
    axis.text(
        0.02, 0.03,
        'Feasibility measures independent single-packet send capability at snapshot;\n'
        'does not guarantee concurrent transmissions succeed.',
        transform=axis.transAxes, fontsize=8,
        bbox={'facecolor': 'white', 'alpha': 0.8, 'edgecolor': '0.8'},
    )
    axis.set(
        title=f'Ratio of sensors with sufficient transmission energy over time\n{subtitle}',
        xlabel='Simulation time (s)', ylabel='Feasible sensors ratio (%)',
        ylim=(0, 105),
    )
    axis.grid(alpha=0.25)
    axis.legend(fontsize=7, ncol=2)
    save_plot(figure, '09_energy_feasible_ratio_over_time')
    save_source(
        '09_energy_feasible_ratio_over_time', feasibility_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'time_s', 'energy_feasible_sensors', 'energy_feasible_ratio'],
    )

    # Figure 10: Cumulative delivered bits over time
    bits_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    for row in summary:
        timeseries = _read_csv(row['_run_path'] / 'timeseries.csv')
        points = [(float(entry['time_s']), int(entry['delivered_bytes']) * 8) for entry in timeseries]
        range_m = float(row['range_m'])
        axis.step(
            [p[0] for p in points], [p[1] for p in points],
            where='post',
            label=f'{row["algorithm"]} R={range_m:g}m seed={row["seed"]}',
            color=range_colors[range_m],
            linestyle=algorithm_lines[row['algorithm']],
            linewidth=1.5,
        )
        for time_s, bits in points:
            bits_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'],
                'time_s': time_s, 'delivered_bytes': bits // 8, 'delivered_bits': bits,
            })
    axis.set(
        title=f'Cumulative delivered bits to sink over simulation time\n{subtitle}',
        xlabel='Simulation time (s)', ylabel='Cumulative delivered bits (bit)',
    )
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25)
    axis.legend(fontsize=7, ncol=2)
    save_plot(figure, '10_cumulative_delivered_bits_over_time')
    save_source(
        '10_cumulative_delivered_bits_over_time', bits_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'time_s', 'delivered_bytes', 'delivered_bits'],
    )

    # Figure 11: Dropped packets by reason
    dropped_source: list[dict[str, Any]] = []
    scenario_drop_reasons: dict[str, dict[str, int]] = {}
    all_reasons: set[str] = set()
    for row in summary:
        scenario = row['scenario']
        packets = _read_csv(row['_run_path'] / 'packets.csv')
        reasons_counter = Counter(
            p['drop_reason'].strip()
            for p in packets
            if p['status'] == 'dropped' or p['drop_reason'].strip()
        )
        scenario_drop_reasons[scenario] = dict(reasons_counter)
        all_reasons.update(reasons_counter.keys())
        if not reasons_counter:
            dropped_source.append({
                'scenario': scenario, 'algorithm': row['algorithm'],
                'range_m': row['range_m'], 'seed': row['seed'],
                'drop_reason': 'none', 'dropped_packets': 0,
            })
        else:
            for reason, count in sorted(reasons_counter.items()):
                dropped_source.append({
                    'scenario': scenario, 'algorithm': row['algorithm'],
                    'range_m': row['range_m'], 'seed': row['seed'],
                    'drop_reason': reason, 'dropped_packets': count,
                })
    figure, axis = plt.subplots(figsize=(10, 5))
    scenarios_list = [row['scenario'] for row in summary]
    x_indices = list(range(len(scenarios_list)))
    if all_reasons:
        sorted_reasons = sorted(all_reasons)
        reason_colors = ['tab:red', 'tab:purple', 'tab:olive', 'tab:gray']
        for idx, reason in enumerate(sorted_reasons):
            counts = [scenario_drop_reasons[sc].get(reason, 0) for sc in scenarios_list]
            offset = (idx - len(sorted_reasons) / 2 + 0.5) * (0.8 / len(sorted_reasons))
            axis.bar(
                [x + offset for x in x_indices], counts,
                width=0.8 / len(sorted_reasons),
                label=reason,
                color=reason_colors[idx % len(reason_colors)],
            )
        axis.legend(title='Drop reason', fontsize=8)
    else:
        axis.text(0.5, 0.5, 'Zero packets dropped in all scenarios', ha='center', va='center', transform=axis.transAxes)

    axis.text(
        0.02, 0.88,
        'Authentic behavior note: Drops in EMHR (e.g. at R=350m)\n'
        'are caused by candidate relay nodes falling below threshold Eth.',
        transform=axis.transAxes, fontsize=8,
        bbox={'facecolor': 'white', 'alpha': 0.85, 'edgecolor': '0.8'},
    )
    axis.set_xticks(x_indices)
    axis.set_xticklabels(scenarios_list, rotation=25, ha='right', fontsize=8)
    axis.set(
        title=f'Dropped packets by drop reason\n{subtitle}',
        xlabel='Scenario', ylabel='Dropped packets (count)',
    )
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25, axis='y')
    save_plot(figure, '11_dropped_packets_by_reason')
    save_source(
        '11_dropped_packets_by_reason', dropped_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'drop_reason', 'dropped_packets'],
    )

    # Figure 12: Energy consumed per delivered bit by range
    energy_bit_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(8, 5))
    for algorithm, seed in groups:
        selected = sorted(
            (row for row in summary if row['algorithm'] == algorithm and int(row['seed']) == seed),
            key=lambda row: float(row['range_m']),
        )
        points = [
            (float(row['range_m']), _optional_float(row.get('energy_per_delivered_bit_j')))
            for row in selected
        ]
        observed = [(r, val) for r, val in points if val is not None]
        if observed:
            axis.plot(
                [p[0] for p in observed], [p[1] for p in observed],
                marker='o' if algorithm == 'MHR' else 's',
                linestyle=algorithm_lines[algorithm],
                color=algorithm_colors[algorithm],
                label=f'{algorithm} seed={seed}',
            )
            for r, val in observed:
                axis.annotate(
                    f'{val:.2e} J/bit', (r, val),
                    xytext=(0, 10 if algorithm == 'MHR' else -15),
                    textcoords='offset points', ha='center', fontsize=7,
                )
        for row, (range_m, val) in zip(selected, points):
            energy_bit_source.append({
                'scenario': row['scenario'], 'algorithm': algorithm,
                'range_m': range_m, 'seed': seed,
                'measurement_duration_s': row['actual_duration_s'],
                'energy_per_delivered_bit_j': val,
                'status': 'observed' if val is not None else 'not_observed',
            })
    axis.set(
        title=f'Energy consumed per delivered bit by communication range\n{subtitle}',
        xlabel='Communication range R (m)', ylabel='Energy per delivered bit (J/bit)',
    )
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25)
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(fontsize=8)
    save_plot(figure, '12_energy_per_delivered_bit_by_range')
    save_source(
        '12_energy_per_delivered_bit_by_range', energy_bit_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'measurement_duration_s',
         'energy_per_delivered_bit_j', 'status'],
    )

    manifest = {
        'pilot_directory': '.',
        'validated_runs': len(summary),
        'seeds': seeds,
        'classification': 'pilot_not_main_experiment',
        'figures': created_figures,
        'source_tables': created_tables,
    }
    (output / 'plot_manifest.json').write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + '\n',
        encoding='utf-8',
    )
    print(f'Created {len(manifest["figures"])} figures in {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
