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
    'fnd_status', 'hnd_status', 'lnd_status',
    'functional_network_death_status', 'network_lifetime_s',
    'network_lifetime_status', 'network_lifetime_definition',
    'energy_service_lifetime_sampled_s', 'energy_service_lifetime_status',
    'energy_service_lifetime_definition', 'serviceability_sample_interval_s',
    'measurement_interval',
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
    'network_lifetime_s', 'energy_service_lifetime_sampled_s',
    'serviceability_sample_interval_s',
    'delivered_bits_at_fnd', 'delivered_bits_at_hnd', 'delivered_bits_at_lnd',
    'relay_jain_fairness', 'route_recompute_count', 'route_change_count',
    'route_failure_count',
)

SUMMARY_TEXT_METRICS = (
    'fnd_status', 'hnd_status', 'lnd_status',
    'functional_network_death_status', 'network_lifetime_status',
    'network_lifetime_definition', 'energy_service_lifetime_status',
    'energy_service_lifetime_definition', 'measurement_interval',
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
    '13_throughput_goodput_over_time',
    '14_delivered_bits_at_lifetime_milestones',
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


def _cumulative_delivery_points(
    packets: list[dict[str, Any]], measurement_duration_s: float
) -> list[dict[str, Any]]:
    '''Build the sink-bit step series from actual packet delivery events.'''
    duration = float(measurement_duration_s)
    if not math.isfinite(duration) or duration < 0:
        raise ValueError('measurement duration must be finite and non-negative')

    packet_ids: set[str] = set()
    deliveries: list[tuple[float, int, int, str]] = []
    for index, packet in enumerate(packets, start=2):
        packet_id = str(packet.get('packet_id', '')).strip()
        if not packet_id:
            raise ValueError(f'packets.csv:{index}: packet_id must not be empty')
        if packet_id in packet_ids:
            raise ValueError(f'packets.csv:{index}: duplicate packet_id {packet_id!r}')
        packet_ids.add(packet_id)
        if packet.get('status') != 'DELIVERED':
            continue
        try:
            delivered_at = float(packet['delivered_at'])
            delivered_seq = int(packet['delivered_event_seq'])
            size_bytes = int(packet['size_bytes'])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f'packets.csv:{index}: invalid delivered event fields'
            ) from exc
        if (
            not math.isfinite(delivered_at)
            or not 0 <= delivered_at < duration
            or delivered_seq < 0
            or size_bytes < 0
        ):
            raise ValueError(
                f'packets.csv:{index}: delivered event is outside the valid domain'
            )
        deliveries.append((delivered_at, delivered_seq, size_bytes, packet_id))

    deliveries.sort(key=lambda item: (item[0], item[1]))
    points: list[dict[str, Any]] = [{
        'time_s': 0.0,
        'delivered_bytes': 0,
        'delivered_bits': 0,
        'point_kind': 'initial',
        'delivery_events': 0,
    }]
    total_bytes = 0
    for delivered_at, _, size_bytes, _ in deliveries:
        total_bytes += size_bytes
        if points[-1]['point_kind'] == 'delivery' and points[-1]['time_s'] == delivered_at:
            points[-1].update({
                'delivered_bytes': total_bytes,
                'delivered_bits': total_bytes * 8,
                'delivery_events': points[-1]['delivery_events'] + 1,
            })
        else:
            points.append({
                'time_s': delivered_at,
                'delivered_bytes': total_bytes,
                'delivered_bits': total_bytes * 8,
                'point_kind': 'delivery',
                'delivery_events': 1,
            })
    if points[-1]['time_s'] < duration:
        points.append({
            'time_s': duration,
            'delivered_bytes': total_bytes,
            'delivered_bits': total_bytes * 8,
            'point_kind': 'observation_end',
            'delivery_events': 0,
        })
    return points


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _windowed_rates(
    packets: list[dict[str, Any]],
    measurement_duration_s: float,
    window_size_s: float = 10.0,
) -> list[dict[str, Any]]:
    '''Calculate half-open offered/delivered rate windows, including a short final window.'''
    duration = float(measurement_duration_s)
    if duration <= 0 or window_size_s <= 0:
        raise ValueError('duration and window size must be positive')
    window_count = math.ceil(duration / window_size_s)
    rows = []
    for index in range(window_count):
        start = index * window_size_s
        end = min(duration, start + window_size_s)
        rows.append({
            'window_index': index,
            'window_start_s': start,
            'window_end_s': end,
            'duration_s': end - start,
            'offered_bytes': 0,
            'delivered_bytes': 0,
            'delivered_payload_bytes': 0,
        })

    def window_index(event_time: float) -> int:
        if not 0 <= event_time < duration:
            raise ValueError(f'packet event time {event_time} is outside [0,{duration})')
        return min(int(event_time // window_size_s), window_count - 1)

    for packet in packets:
        created_at = float(packet['created_at'])
        rows[window_index(created_at)]['offered_bytes'] += int(packet['size_bytes'])
        if packet['status'] == 'DELIVERED':
            delivered_at = float(packet['delivered_at'])
            bucket = rows[window_index(delivered_at)]
            bucket['delivered_bytes'] += int(packet['size_bytes'])
            bucket['delivered_payload_bytes'] += int(packet['payload_size_bytes'])
    for row in rows:
        duration_s = row['duration_s']
        row['offered_rate_bps'] = 8.0 * row['offered_bytes'] / duration_s
        row['throughput_bps'] = 8.0 * row['delivered_bytes'] / duration_s
        row['goodput_bps'] = 8.0 * row['delivered_payload_bytes'] / duration_s
    return rows


def _energy_ledger_points(
    nodes: list[dict[str, Any]],
    ledger: list[dict[str, Any]],
    measurement_duration_s: float,
) -> list[dict[str, Any]]:
    initial = sum(
        float(node['initial_energy_j']) for node in nodes if node['type'] == 'sensor'
    )
    points = [{
        'time_s': 0.0, 'event_seq': None, 'debit_j': 0.0,
        'cumulative_debit_j': 0.0, 'residual_energy_j': initial,
        'point_kind': 'initial',
    }]
    cumulative = 0.0
    ordered = sorted(ledger, key=lambda row: (float(row['time_s']), int(row['event_seq'])))
    for entry in ordered:
        debit = float(entry['tx_energy_j']) + float(entry['rx_energy_j'])
        cumulative += debit
        points.append({
            'time_s': float(entry['time_s']),
            'event_seq': int(entry['event_seq']),
            'debit_j': debit,
            'cumulative_debit_j': cumulative,
            'residual_energy_j': max(0.0, initial - cumulative),
            'point_kind': 'energy_transaction',
        })
    points.append({
        'time_s': float(measurement_duration_s), 'event_seq': None, 'debit_j': 0.0,
        'cumulative_debit_j': cumulative,
        'residual_energy_j': max(0.0, initial - cumulative),
        'point_kind': 'observation_end',
    })
    return points


def _drop_category_breakdown(
    packets: list[dict[str, Any]],
) -> tuple[Counter[str], Counter[tuple[str, str]], int]:
    dropped = [
        packet for packet in packets
        if packet['status'] in {'DROPPED', 'NO_ROUTE'}
    ]
    categories: Counter[str] = Counter()
    details: Counter[tuple[str, str]] = Counter()
    for packet in dropped:
        category = str(packet.get('drop_category', '')).strip() or 'unspecified'
        detail = str(packet.get('drop_detail', '')).strip() or 'unspecified'
        categories[category] += 1
        details[(category, detail)] += 1
    if sum(categories.values()) != len(dropped):
        raise ValueError('drop category counts do not conserve dropped packets')
    return categories, details, len(dropped)


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
    for name in SUMMARY_TEXT_METRICS:
        if row[name] != str(metrics[name]):
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
            f'end={points[-1][1]} alive/{int(row["_metrics"]["dead_sensors"])} dead; '
            f'FND/HND/LND={row["fnd_status"]}/'
            f'{row["hnd_status"]}/{row["lnd_status"]}'
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
                'final_dead_sensors': row['_metrics']['dead_sensors'],
                'fnd_status': row['fnd_status'], 'hnd_status': row['hnd_status'],
                'lnd_status': row['lnd_status'],
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
         'time_s', 'alive_sensors', 'sample_source', 'final_dead_sensors',
         'fnd_status', 'hnd_status', 'lnd_status'],
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
                    'delivered_packets': row['delivered_packets'],
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
             'delivered_packets', output_field, 'status'],
        )

    single_metric_plot(
        '04_average_hops_by_range', 'average_hops',
        'Average actual hops of delivered packets (edges, not relays)',
        'Average actual path length (hop) [delivered packets only]', 'average_hops',
    )
    # Figure 05: summary statistics and the full delivered-packet delay ECDF.
    delay_source: list[dict[str, Any]] = []
    figure, (summary_axis, ecdf_axis) = plt.subplots(1, 2, figsize=(13, 5))
    for row in summary:
        packets = _read_csv(row['_run_path'] / 'packets.csv')
        latencies_ms = sorted(
            float(packet['latency_s']) * 1000.0
            for packet in packets if packet['status'] == 'DELIVERED'
        )
        average_ms = _optional_float(row['average_end_to_end_delay_s'])
        average_ms = None if average_ms is None else average_ms * 1000.0
        median_ms = _percentile(latencies_ms, 0.5)
        p95_ms = _percentile(latencies_ms, 0.95)
        range_m = float(row['range_m'])
        if average_ms is not None:
            summary_axis.scatter(range_m, average_ms, marker='o',
                                 color=algorithm_colors[row['algorithm']])
            summary_axis.scatter(range_m, median_ms, marker='s',
                                 color=algorithm_colors[row['algorithm']])
            summary_axis.scatter(range_m, p95_ms, marker='^',
                                 color=algorithm_colors[row['algorithm']])
            probabilities = [(index + 1) / len(latencies_ms)
                             for index in range(len(latencies_ms))]
            ecdf_axis.step(
                latencies_ms, probabilities, where='post',
                color=range_colors[range_m],
                linestyle=algorithm_lines[row['algorithm']],
                label=f'{row["algorithm"]} R={range_m:g}m seed={row["seed"]}',
                alpha=0.85,
            )
        delay_source.append({
            'scenario': row['scenario'], 'algorithm': row['algorithm'],
            'range_m': range_m, 'seed': row['seed'], 'record_type': 'summary',
            'packet_id': None, 'sample_index': None,
            'delivered_packets': len(latencies_ms), 'delay_ms': None,
            'ecdf_probability': None, 'average_end_to_end_delay_ms': average_ms,
            'median_delay_ms': median_ms, 'p95_delay_ms': p95_ms,
        })
        for index, (packet, delay_ms) in enumerate(zip(
            sorted(
                (packet for packet in packets if packet['status'] == 'DELIVERED'),
                key=lambda packet: float(packet['latency_s']),
            ),
            latencies_ms,
        ), start=1):
            delay_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'],
                'record_type': 'delivered_packet', 'packet_id': packet['packet_id'],
                'sample_index': index, 'delivered_packets': len(latencies_ms),
                'delay_ms': delay_ms,
                'ecdf_probability': index / len(latencies_ms),
                'average_end_to_end_delay_ms': None, 'median_delay_ms': None,
                'p95_delay_ms': None,
            })
    summary_axis.set(
        title='Delay summary by range\nmarkers: mean=o, median=s, p95=^',
        xlabel='Communication range R (m)', ylabel='End-to-end delay (ms)',
    )
    summary_axis.grid(alpha=0.25)
    ecdf_axis.set(
        title='Delivered-packet delay ECDF', xlabel='End-to-end delay (ms)',
        ylabel='Empirical cumulative probability', ylim=(0, 1.02),
    )
    ecdf_axis.grid(alpha=0.25)
    ecdf_axis.legend(fontsize=7)
    figure.suptitle(f'Delay distribution of delivered packets\n{subtitle}')
    save_plot(figure, '05_average_delay_by_range')
    save_source(
        '05_average_delay_by_range', delay_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'record_type', 'packet_id',
         'sample_index', 'delivered_packets', 'delay_ms', 'ecdf_probability',
         'average_end_to_end_delay_ms', 'median_delay_ms', 'p95_delay_ms'],
    )

    # Figure 06: never invent values or connect across missing observations.
    milestone_specs = [
        ('fnd_s', 'FND', 'fnd_status'),
        ('hnd_s', 'HND', 'hnd_status'),
        ('lnd_s', 'LND', 'lnd_status'),
        ('functional_network_death_s', 'Physical-connectivity lifetime',
         'functional_network_death_status'),
        ('energy_service_lifetime_sampled_s', 'Energy-service lifetime (sampled)',
         'energy_service_lifetime_status'),
    ]
    lifetime_source: list[dict[str, Any]] = []
    observed_points: list[tuple[dict[str, Any], str, str, float]] = []
    for row in summary:
        for key, label, status_key in milestone_specs:
            value = _optional_float(row[key])
            status = row[status_key]
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
            f'FND · HND · LND · physical-connectivity · sampled energy-service lifetime\n'
            f'Not observed in {", ".join(intervals)}\n'
            f'{algorithms_label}; R={ranges_label} m; seeds={seeds}',
            ha='center', va='center', fontsize=11, transform=axis.transAxes,
            bbox={'facecolor': '#f3f4f6', 'edgecolor': '#9ca3af', 'pad': 12},
        )
        axis.set_title(f'Pilot lifetime status\n{subtitle}')
    else:
        metric_markers = {'fnd_s': 'o', 'hnd_s': 's', 'lnd_s': '^',
                          'functional_network_death_s': 'D',
                          'energy_service_lifetime_sampled_s': 'P'}
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
                  'Real periodic traffic with test-sized batteries validates milestones\n'
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

    # Figure 08: exact residual energy reconstructed from every ledger debit.
    energy_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    for row in summary:
        nodes = _read_csv(row['_run_path'] / 'nodes.csv')
        ledger = _read_csv(row['_run_path'] / 'energy_ledger.csv')
        duration = float(row['_metrics']['measurement_duration_s'])
        points = _energy_ledger_points(nodes, ledger, duration)
        expected_final = float(row['_metrics']['residual_total_energy_j'])
        if not math.isclose(
            points[-1]['residual_energy_j'], expected_final,
            rel_tol=0.0, abs_tol=ABSOLUTE_TOLERANCE,
        ):
            raise ValueError(
                f'{row["scenario"]}: ledger energy curve ends at '
                f'{points[-1]["residual_energy_j"]}, metrics reports {expected_final}'
            )
        range_m = float(row['range_m'])
        axis.step(
            [p['time_s'] for p in points],
            [p['residual_energy_j'] for p in points],
            where='post',
            label=f'{row["algorithm"]} R={range_m:g}m seed={row["seed"]}',
            color=range_colors[range_m],
            linestyle=algorithm_lines[row['algorithm']],
            linewidth=1.5,
        )
        for point in points:
            energy_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'],
                **point,
            })
    axis.set(
        title=f'Exact residual network energy from TX/RX ledger events\n{subtitle}',
        xlabel='Simulation time (s)', ylabel='Residual energy (J)',
    )
    axis.text(
        0.02, 0.03,
        'Every TX+RX debit is included, including failed transactions with sender TX cost.',
        transform=axis.transAxes, fontsize=8,
        bbox={'facecolor': 'white', 'alpha': 0.8, 'edgecolor': '0.8'},
    )
    axis.grid(alpha=0.25)
    axis.legend(fontsize=7, ncol=2)
    save_plot(figure, '08_residual_energy_over_time')
    save_source(
        '08_residual_energy_over_time', energy_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'time_s', 'event_seq',
         'debit_j', 'cumulative_debit_j', 'residual_energy_j', 'point_kind'],
    )

    # Figure 09: Energy feasible ratio over time
    feasibility_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    observed_feasibility = False
    undefined_no_alive = 0
    for row in summary:
        timeseries = _read_csv(row['_run_path'] / 'serviceability_snapshots.csv')
        points = []
        for entry in timeseries:
            ratio = _optional_float(entry.get('energy_feasible_ratio'))
            physical_ratio = _optional_float(entry.get('reachability_ratio'))
            count = int(entry['energy_feasible_sensors'])
            alive = int(entry['alive_sensors'])
            status = (
                'undefined_no_alive_sensors'
                if ratio is None and alive == 0
                else 'observed'
                if ratio is not None
                else 'undefined'
            )
            observed_feasibility = observed_feasibility or ratio is not None
            undefined_no_alive += status == 'undefined_no_alive_sensors'
            points.append((
                float(entry['time_s']),
                math.nan if ratio is None else 100.0 * ratio,
                count,
                ratio,
                alive,
                status,
                physical_ratio,
            ))
        range_m = float(row['range_m'])
        if points:
            axis.plot(
                [p[0] for p in points], [p[1] for p in points],
                label=f'{row["algorithm"]} R={range_m:g}m energy-feasible',
                color=range_colors[range_m],
                linestyle=algorithm_lines[row['algorithm']],
                linewidth=1.5,
            )
            axis.plot(
                [p[0] for p in points],
                [math.nan if p[6] is None else 100.0 * p[6] for p in points],
                label=f'{row["algorithm"]} R={range_m:g}m physical reachability',
                color=range_colors[range_m], linestyle=':', linewidth=1.1, alpha=0.8,
            )
        for time_s, _, count, ratio, alive, status, physical_ratio in points:
            feasibility_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'],
                'alive_sensors': alive,
                'time_s': time_s, 'energy_feasible_sensors': count,
                'energy_feasible_ratio': ratio,
                'physical_reachability_ratio': physical_ratio,
                'status': status,
            })
    if not observed_feasibility:
        axis.text(
            0.5, 0.55, 'Feasibility ratio undefined: no alive sensors',
            ha='center', va='center', transform=axis.transAxes,
        )
    elif undefined_no_alive:
        axis.text(
            0.98, 0.97,
            f'{undefined_no_alive} all-dead snapshot(s): ratio undefined; line interrupted',
            ha='right', va='top', transform=axis.transAxes, fontsize=8,
        )
    axis.text(
        0.02, 0.03,
        'Solid/dashed: sampled energy-feasible path; dotted: physical reachability.\n'
        'Feasibility is an independent one-packet snapshot, not a delivery guarantee.',
        transform=axis.transAxes, fontsize=8,
        bbox={'facecolor': 'white', 'alpha': 0.8, 'edgecolor': '0.8'},
    )
    axis.set(
        title=f'Physical reachability versus sampled energy serviceability\n{subtitle}',
        xlabel='Simulation time (s)', ylabel='Alive-sensor ratio (%)',
        ylim=(0, 105),
    )
    axis.grid(alpha=0.25)
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(fontsize=7, ncol=2)
    save_plot(figure, '09_energy_feasible_ratio_over_time')
    save_source(
        '09_energy_feasible_ratio_over_time', feasibility_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'time_s', 'alive_sensors',
         'energy_feasible_sensors', 'energy_feasible_ratio',
         'physical_reachability_ratio', 'status'],
    )

    # Figure 10: Cumulative delivered bits over time
    bits_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(9, 5))
    for row in summary:
        packets = _read_csv(row['_run_path'] / 'packets.csv')
        duration = float(row['_metrics']['measurement_duration_s'])
        points = _cumulative_delivery_points(packets, duration)
        final_bits = points[-1]['delivered_bits']
        expected_bits = int(row['_metrics']['total_delivered_bits'])
        if final_bits != expected_bits:
            raise ValueError(
                f'{row["scenario"]}: delivery-event series ends at {final_bits} bit, '
                f'metrics reports {expected_bits} bit'
            )
        range_m = float(row['range_m'])
        axis.step(
            [p['time_s'] for p in points], [p['delivered_bits'] for p in points],
            where='post',
            label=f'{row["algorithm"]} R={range_m:g}m seed={row["seed"]}',
            color=range_colors[range_m],
            linestyle=algorithm_lines[row['algorithm']],
            linewidth=1.5,
        )
        for milestone_key, marker in (('fnd_s', 'o'), ('hnd_s', 's'), ('lnd_s', '^')):
            milestone_time = _optional_float(row[milestone_key])
            if milestone_time is None:
                continue
            milestone_bits = max(
                point['delivered_bits'] for point in points
                if point['time_s'] <= milestone_time + ABSOLUTE_TOLERANCE
            )
            axis.scatter(
                [milestone_time], [milestone_bits], marker=marker,
                color=range_colors[range_m], edgecolors='black', linewidths=0.4,
                zorder=4,
            )
        for point in points:
            bits_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'],
                **point,
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
        ['scenario', 'algorithm', 'range_m', 'seed', 'time_s', 'delivered_bytes',
         'delivered_bits', 'point_kind', 'delivery_events'],
    )

    # Figure 11: one canonical category per dropped packet, rendered as stacked bars.
    dropped_source: list[dict[str, Any]] = []
    scenario_drop_categories: dict[str, dict[str, int]] = {}
    all_categories: set[str] = set()
    for row in summary:
        scenario = row['scenario']
        packets = _read_csv(row['_run_path'] / 'packets.csv')
        categories_counter, detail_counter, dropped_total = (
            _drop_category_breakdown(packets)
        )
        scenario_drop_categories[scenario] = dict(categories_counter)
        all_categories.update(categories_counter.keys())
        if not categories_counter:
            dropped_source.append({
                'scenario': scenario, 'algorithm': row['algorithm'],
                'range_m': row['range_m'], 'seed': row['seed'],
                'drop_category': 'none', 'drop_detail': 'none',
                'dropped_packets': 0, 'scenario_dropped_total': 0,
            })
        else:
            total = dropped_total
            for (category, detail), count in sorted(detail_counter.items()):
                dropped_source.append({
                    'scenario': scenario, 'algorithm': row['algorithm'],
                    'range_m': row['range_m'], 'seed': row['seed'],
                    'drop_category': category, 'drop_detail': detail,
                    'dropped_packets': count, 'scenario_dropped_total': total,
                })
    figure, axis = plt.subplots(figsize=(10, 5))
    scenarios_list = [row['scenario'] for row in summary]
    x_indices = list(range(len(scenarios_list)))
    if all_categories:
        sorted_categories = sorted(all_categories)
        reason_colors = ['tab:red', 'tab:purple', 'tab:olive', 'tab:gray']
        bottom = [0] * len(scenarios_list)
        for idx, category in enumerate(sorted_categories):
            counts = [
                scenario_drop_categories[scenario].get(category, 0)
                for scenario in scenarios_list
            ]
            axis.bar(
                x_indices, counts, bottom=bottom, label=category,
                color=reason_colors[idx % len(reason_colors)],
            )
            bottom = [previous + count for previous, count in zip(bottom, counts)]
        axis.legend(title='Drop category', fontsize=8)
        for x_value, total in zip(x_indices, bottom):
            axis.annotate(
                str(total), (x_value, total), xytext=(0, 4),
                textcoords='offset points', ha='center', va='bottom', fontsize=8,
            )
    else:
        axis.text(0.5, 0.5, 'Zero packets dropped in all scenarios', ha='center', va='center', transform=axis.transAxes)

    if all_categories:
        axis.text(
            0.02, 0.88,
            f'Observed drop categories: {", ".join(sorted(all_categories))}',
            transform=axis.transAxes, fontsize=8,
            bbox={'facecolor': 'white', 'alpha': 0.85, 'edgecolor': '0.8'},
        )
    axis.set_xticks(x_indices)
    axis.set_xticklabels(scenarios_list, rotation=25, ha='right', fontsize=8)
    axis.set(
        title=f'Dropped packets by canonical category (stacked totals)\n{subtitle}',
        xlabel='Scenario', ylabel='Dropped packets (count)',
    )
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25, axis='y')
    save_plot(figure, '11_dropped_packets_by_reason')
    save_source(
        '11_dropped_packets_by_reason', dropped_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'drop_category',
         'drop_detail', 'dropped_packets', 'scenario_dropped_total'],
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
                x_offset = 24 if r == min(range_values) else (
                    -24 if r == max(range_values) else 0
                )
                axis.annotate(
                    f'{val:.2e} J/bit', (r, val),
                    xytext=(x_offset, 10 if algorithm == 'MHR' else -15),
                    textcoords='offset points', ha='center', fontsize=7,
                )
        for row, (range_m, val) in zip(selected, points):
            energy_bit_source.append({
                'scenario': row['scenario'], 'algorithm': algorithm,
                'range_m': range_m, 'seed': seed,
                'measurement_duration_s': row['actual_duration_s'],
                'energy_per_delivered_bit_j': val,
                'denominator_definition': 'delivered_full_packet_bits',
                'status': 'observed' if val is not None else 'not_observed',
            })
    axis.set(
        title=f'Energy consumed per delivered full-packet bit by range\n{subtitle}',
        xlabel='Communication range R (m)',
        ylabel='Energy per delivered full-packet bit (J/bit)',
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
         'energy_per_delivered_bit_j', 'denominator_definition', 'status'],
    )

    # Figure 13: delivered and payload rates in half-open time windows.
    window_source: list[dict[str, Any]] = []
    figure, axis = plt.subplots(figsize=(10, 5.5))
    for row in summary:
        packets = _read_csv(row['_run_path'] / 'packets.csv')
        duration = float(row['_metrics']['measurement_duration_s'])
        windows = _windowed_rates(packets, duration, window_size_s=10.0)
        weighted_throughput = sum(
            window['throughput_bps'] * window['duration_s'] for window in windows
        ) / duration
        if not math.isclose(
            weighted_throughput, float(row['_metrics']['throughput_bps']),
            rel_tol=0.0, abs_tol=ABSOLUTE_TOLERANCE,
        ):
            raise ValueError(
                f'{row["scenario"]}: duration-weighted window throughput '
                'does not match aggregate throughput'
            )
        range_m = float(row['range_m'])
        x = [window['window_start_s'] for window in windows] + [duration]
        for key, label, line in (
            ('throughput_bps', 'throughput', algorithm_lines[row['algorithm']]),
            ('goodput_bps', 'goodput', ':'),
        ):
            y = [window[key] for window in windows]
            axis.step(
                x, [*y, y[-1]], where='post',
                color=range_colors[range_m], linestyle=line, alpha=0.82,
                label=f'{row["algorithm"]} R={range_m:g}m {label}',
            )
        for window in windows:
            window_source.append({
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': range_m, 'seed': row['seed'], **window,
            })
    axis.set(
        title=f'Throughput and goodput in 10-second windows\n{subtitle}',
        xlabel='Simulation time (s)', ylabel='Rate (bit/s)',
    )
    axis.text(
        0.02, 0.03,
        'Half-open windows [start,end); events on a boundary enter the next window.\n'
        'The final [100,101) window is divided by its actual 1-second duration.',
        transform=axis.transAxes, fontsize=8,
        bbox={'facecolor': 'white', 'alpha': 0.8, 'edgecolor': '0.8'},
    )
    axis.set_ylim(bottom=0)
    axis.grid(alpha=0.25)
    axis.legend(fontsize=6, ncol=3)
    save_plot(figure, '13_throughput_goodput_over_time')
    save_source(
        '13_throughput_goodput_over_time', window_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'window_index',
         'window_start_s', 'window_end_s', 'duration_s', 'offered_bytes',
         'delivered_bytes', 'delivered_payload_bytes', 'offered_rate_bps',
         'throughput_bps', 'goodput_bps'],
    )

    # Figure 14: data delivered at physical node-death milestones.
    milestone_bits_source: list[dict[str, Any]] = []
    observed_milestone_bits: list[dict[str, Any]] = []
    for row in summary:
        for milestone, label in (('fnd', 'FND'), ('hnd', 'HND'), ('lnd', 'LND')):
            time_value = _optional_float(row[f'{milestone}_s'])
            bits_value = _optional_float(row[f'delivered_bits_at_{milestone}'])
            status = row[f'{milestone}_status']
            record = {
                'scenario': row['scenario'], 'algorithm': row['algorithm'],
                'range_m': row['range_m'], 'seed': row['seed'],
                'milestone': label, 'milestone_time_s': time_value,
                'delivered_bits': bits_value, 'status': status,
                'observation_interval': f'[0,{float(row["actual_duration_s"]):g} s)',
            }
            milestone_bits_source.append(record)
            if time_value is not None and bits_value is not None:
                observed_milestone_bits.append(record)
    figure, axis = plt.subplots(figsize=(11, 5.5))
    if observed_milestone_bits:
        labels = [f'{item["scenario"]}\n{item["milestone"]}'
                  for item in observed_milestone_bits]
        values = [item['delivered_bits'] for item in observed_milestone_bits]
        axis.bar(range(len(values)), values, color='tab:blue')
        axis.set_xticks(range(len(values)))
        axis.set_xticklabels(labels, rotation=30, ha='right', fontsize=7)
        axis.set_ylabel('Delivered full-packet bits at milestone (bit)')
        axis.grid(alpha=0.25, axis='y')
    else:
        axis.axis('off')
        axis.text(
            0.5, 0.58, 'No FND/HND/LND milestone was observed',
            ha='center', va='center', fontsize=15, weight='bold',
            transform=axis.transAxes,
        )
        axis.text(
            0.5, 0.42,
            f'Delivered bits remain undefined; no zero-valued bars are drawn.\n'
            f'Not observed in [0,{duration_label} s).',
            ha='center', va='center', fontsize=10, transform=axis.transAxes,
        )
    axis.set_title(f'Data delivered at physical lifetime milestones\n{subtitle}')
    save_plot(figure, '14_delivered_bits_at_lifetime_milestones')
    save_source(
        '14_delivered_bits_at_lifetime_milestones', milestone_bits_source,
        ['scenario', 'algorithm', 'range_m', 'seed', 'milestone',
         'milestone_time_s', 'delivered_bits', 'status', 'observation_interval'],
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
