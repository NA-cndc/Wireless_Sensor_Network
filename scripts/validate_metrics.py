'''Independently recalculate exported WSN metrics from CSV and JSON files.'''

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

ABSOLUTE_TOLERANCE = 1e-9


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open('r', newline='', encoding='utf-8') as file_handle:
        return list(csv.DictReader(file_handle))


def _optional_float(value: Any) -> float | None:
    if value is None or value == '':
        return None
    return float(value)


def _same_number(left: Any, right: Any, tolerance: float) -> tuple[float | None, bool]:
    if left is None or right is None:
        return None, left is None and right is None
    difference = float(left) - float(right)
    return difference, math.isclose(
        float(left),
        float(right),
        rel_tol=0.0,
        abs_tol=tolerance,
    )


def validate_run(
    run_dir: str | Path,
    output_path: str | Path | None = None,
    tolerance: float = ABSOLUTE_TOLERANCE,
) -> dict[str, Any]:
    '''Validate one exported run without importing production metric helpers.'''
    run_path = Path(run_dir)
    metrics = json.loads((run_path / 'metrics.json').read_text(encoding='utf-8'))
    packets = _read_csv(run_path / 'packets.csv')
    nodes = _read_csv(run_path / 'nodes.csv')
    ledger = _read_csv(run_path / 'energy_ledger.csv')
    deaths = _read_csv(run_path / 'node_deaths.csv')
    timeseries = _read_csv(run_path / 'timeseries.csv')
    reachability = _read_csv(run_path / 'reachability_events.csv')

    checks: list[dict[str, Any]] = []

    def add(
        metric: str,
        recalculated: Any,
        reported: Any,
        *,
        exact: bool = False,
        passed: bool | None = None,
        detail: str = '',
    ) -> None:
        difference: float | None = None
        if passed is None:
            if exact:
                passed = recalculated == reported
            else:
                difference, passed = _same_number(
                    recalculated,
                    reported,
                    tolerance,
                )
        elif (
            isinstance(recalculated, (int, float))
            and not isinstance(recalculated, bool)
            and isinstance(reported, (int, float))
            and not isinstance(reported, bool)
        ):
            difference = float(recalculated) - float(reported)
        checks.append(
            {
                'metric': metric,
                'recalculated_value': recalculated,
                'reported_value': reported,
                'difference': difference,
                'passed': bool(passed),
                'detail': detail,
            }
        )

    packet_ids = [row['packet_id'] for row in packets]
    add(
        'unique_packet_ids',
        len(set(packet_ids)),
        len(packet_ids),
        exact=True,
    )

    delivered_rows = [row for row in packets if row['status'] == 'DELIVERED']
    dropped_rows = [
        row for row in packets if row['status'] in {'DROPPED', 'NO_ROUTE'}
    ]
    pending_rows = [
        row for row in packets if row['status'] in {'CREATED', 'IN_TRANSIT'}
    ]
    delivered_ids = {row['packet_id'] for row in delivered_rows}
    dropped_ids = {row['packet_id'] for row in dropped_rows}
    pending_ids = {row['packet_id'] for row in pending_rows}
    generated_ids = set(packet_ids)
    partition_union = delivered_ids | dropped_ids | pending_ids
    sets_disjoint = not (
        delivered_ids & dropped_ids
        or delivered_ids & pending_ids
        or dropped_ids & pending_ids
    )
    add(
        'packet_status_partition',
        len(partition_union),
        len(generated_ids),
        passed=sets_disjoint and partition_union == generated_ids,
    )

    counts = {
        'generated_packets': len(packets),
        'delivered_packets': len(delivered_rows),
        'dropped_packets': len(dropped_rows),
        'pending_packets': len(pending_rows),
    }
    for name, value in counts.items():
        add(name, value, metrics.get(name), exact=True)
    add(
        'packet_conservation',
        len(packets),
        len(delivered_rows) + len(dropped_rows) + len(pending_rows),
        exact=True,
    )

    sink_ids = {row['node_id'] for row in nodes if row['type'] == 'sink'}
    timestamps_and_sinks_valid = True
    hops_match = True
    delays_match = True
    total_hops = 0
    total_delay = 0.0
    total_bytes = 0
    total_payload_bytes = 0
    for row in delivered_rows:
        created = _optional_float(row['created_at'])
        delivered_at = _optional_float(row['delivered_at'])
        path = [part for part in row['path'].split('->') if part]
        if (
            created is None
            or delivered_at is None
            or delivered_at < created
            or not path
            or path[-1] not in sink_ids
            or row['sink_id'] != path[-1]
        ):
            timestamps_and_sinks_valid = False
            continue
        calculated_hops = len(path) - 1
        calculated_delay = delivered_at - created
        if calculated_hops != int(row['hop_count']):
            hops_match = False
        logged_delay = _optional_float(row['latency_s'])
        if logged_delay is None or not math.isclose(
            calculated_delay,
            logged_delay,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            delays_match = False
        total_hops += calculated_hops
        total_delay += calculated_delay
        total_bytes += int(row['size_bytes'])
        total_payload_bytes += int(row['payload_size_bytes'])

    add(
        'delivered_timestamp_and_sink_validity',
        timestamps_and_sinks_valid,
        True,
        exact=True,
    )
    add('per_packet_hop_count', hops_match, True, exact=True)
    add('per_packet_latency', delays_match, True, exact=True)
    add('total_hops_delivered', total_hops, metrics.get('total_hops_delivered'))
    add(
        'total_end_to_end_delay_s',
        total_delay,
        metrics.get('total_end_to_end_delay_s'),
    )
    add('total_delivered_bytes', total_bytes, metrics.get('total_delivered_bytes'))
    add(
        'total_delivered_payload_bytes',
        total_payload_bytes,
        metrics.get('total_delivered_payload_bytes'),
    )

    duration = float(metrics['measurement_duration_s'])
    throughput = 8.0 * total_bytes / duration if duration > 0 else None
    goodput = 8.0 * total_payload_bytes / duration if duration > 0 else None
    pdr = 100.0 * len(delivered_rows) / len(packets) if packets else None
    average_hops = total_hops / len(delivered_rows) if delivered_rows else None
    average_delay = total_delay / len(delivered_rows) if delivered_rows else None
    add('throughput_bps', throughput, metrics.get('throughput_bps'))
    add('goodput_bps', goodput, metrics.get('goodput_bps'))
    add('pdr_percent', pdr, metrics.get('pdr_percent'))
    add('average_hops', average_hops, metrics.get('average_hops'))
    add(
        'average_end_to_end_delay_s',
        average_delay,
        metrics.get('average_end_to_end_delay_s'),
    )

    sensor_rows = [row for row in nodes if row['type'] == 'sensor']
    initial_count = len(sensor_rows)
    death_by_node: dict[str, float] = {}
    duplicate_death = False
    for row in deaths:
        node_id = row['node_id']
        if node_id in death_by_node:
            duplicate_death = True
        death_by_node[node_id] = float(row['death_time_s'])
    ordered_deaths = sorted(death_by_node.values())
    half_count = math.ceil(initial_count / 2)
    fnd = ordered_deaths[0] if ordered_deaths else None
    hnd = ordered_deaths[half_count - 1] if len(ordered_deaths) >= half_count else None
    lnd = ordered_deaths[initial_count - 1] if len(ordered_deaths) >= initial_count else None
    add('unique_node_death_events', not duplicate_death, True, exact=True)
    add('fnd_s', fnd, metrics.get('fnd_s'))
    add('hnd_s', hnd, metrics.get('hnd_s'))
    add('lnd_s', lnd, metrics.get('lnd_s'))

    node_death_times_match = True
    for row in sensor_rows:
        logged = _optional_float(row['death_time_s'])
        expected = death_by_node.get(row['node_id'])
        _, same = _same_number(logged, expected, tolerance)
        if not same:
            node_death_times_match = False
            break
    add(
        'node_deaths_match_nodes_csv',
        node_death_times_match,
        True,
        exact=True,
    )

    functional_death = None
    for row in reachability:
        ratio = _optional_float(row['reachability_ratio'])
        if int(row['alive_sensors']) > 0 and ratio is not None and ratio < 0.5:
            functional_death = float(row['time_s'])
            break
    add(
        'functional_network_death_s',
        functional_death,
        metrics.get('functional_network_death_s'),
    )
    all_dead_ratios_empty = all(
        row['reachability_ratio'] == ''
        for row in reachability
        if int(row['alive_sensors']) == 0
    )
    add(
        'all_dead_reachability_is_undefined',
        all_dead_ratios_empty,
        True,
        exact=True,
    )

    debit_by_sensor = {row['node_id']: 0.0 for row in sensor_rows}
    failed_transaction_tx_debit = 0.0
    for row in ledger:
        tx = float(row['tx_energy_j'])
        rx = float(row['rx_energy_j'])
        sender_id = row['sender_id']
        receiver_id = row['receiver_id']
        if sender_id in debit_by_sensor:
            debit_by_sensor[sender_id] += tx
        if receiver_id in debit_by_sensor:
            debit_by_sensor[receiver_id] += rx
        if row['success'].lower() == 'false':
            failed_transaction_tx_debit += tx

    max_energy_difference = 0.0
    energy_matches = True
    for row in sensor_rows:
        battery_drop = float(row['initial_energy_j']) - float(row['energy_j'])
        difference = battery_drop - debit_by_sensor[row['node_id']]
        max_energy_difference = max(max_energy_difference, abs(difference))
        if not math.isclose(
            battery_drop,
            debit_by_sensor[row['node_id']],
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            energy_matches = False
    add(
        'sensor_energy_debit_balance',
        max_energy_difference,
        0.0,
        passed=energy_matches,
        detail=(
            f'failed-transaction TX debit included: {failed_transaction_tx_debit!r} J'
        ),
    )

    if timeseries:
        final = timeseries[-1]
        final_matches = (
            math.isclose(
                float(final['time_s']),
                duration,
                rel_tol=0.0,
                abs_tol=tolerance,
            )
            and int(final['alive_sensors']) == int(metrics['alive_sensors'])
            and int(final['dead_sensors']) == int(metrics['dead_sensors'])
            and int(final['generated_packets']) == len(packets)
            and int(final['delivered_packets']) == len(delivered_rows)
            and int(final['dropped_packets']) == len(dropped_rows)
            and int(final['pending_packets']) == len(pending_rows)
        )
    else:
        final_matches = False
    add('final_timeseries_snapshot', final_matches, True, exact=True)

    report = {
        'run_directory': str(run_path),
        'absolute_tolerance': tolerance,
        'passed': all(check['passed'] for check in checks),
        'checks': checks,
    }
    destination = Path(output_path) if output_path else run_path / 'validation.json'
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n',
        encoding='utf-8',
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Independently validate one exported WSN run.',
    )
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--tolerance', type=float, default=ABSOLUTE_TOLERANCE)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = validate_run(args.run_dir, args.output, args.tolerance)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f'VALIDATION ERROR: {exc}', file=sys.stderr)
        return 2
    passed = sum(1 for check in report['checks'] if check['passed'])
    total = len(report['checks'])
    print(f'Validation: {passed}/{total} checks passed')
    print(f'Result: {"PASS" if report["passed"] else "FAIL"}')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
