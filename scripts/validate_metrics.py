'''Independently recalculate and validate exported WSN run data.'''

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ABSOLUTE_TOLERANCE = 1e-9
DEATH_ENERGY_TOLERANCE_J = 1e-14

CSV_FIELDS = {
    'nodes.csv': {
        'node_id', 'type', 'x', 'y', 'initial_energy_j', 'energy_j', 'is_alive',
        'death_time_s', 'generated_packets', 'received_packets', 'forwarded_packets',
        'dropped_packets', 'tx_energy_total_j', 'rx_energy_total_j',
    },
    'topology_edges.csv': {'source_id', 'target_id', 'distance_m'},
    'packets.csv': {
        'packet_id', 'source_id', 'sink_id', 'sequence_number', 'size_bytes',
        'payload_size_bytes', 'created_at', 'delivered_at', 'latency_s', 'hop_count',
        'status', 'drop_reason', 'drop_node_id', 'route', 'path',
    },
    'energy_ledger.csv': {
        'time_s', 'packet_id', 'sender_id', 'receiver_id', 'distance_m', 'tx_energy_j',
        'rx_energy_j', 'success', 'reason', 'sender_energy_before',
        'sender_energy_after', 'receiver_energy_before', 'receiver_energy_after',
    },
    'node_deaths.csv': {
        'node_id', 'death_time_s', 'energy_before_j', 'energy_after_j', 'cause',
    },
    'reachability_events.csv': {
        'time_s', 'alive_sensors', 'reachable_sensors', 'reachability_ratio', 'state',
        'trigger', 'death_node_id',
    },
    'timeseries.csv': {
        'time_s', 'alive_sensors', 'dead_sensors', 'total_energy_j',
        'generated_packets', 'delivered_packets', 'dropped_packets', 'pending_packets',
        'reachable_sensors', 'reachability_ratio', 'reachability_state',
        'delivered_bytes', 'delivered_payload_bytes', 'snapshot_kind',
    },
}

METRIC_FIELDS = {
    'simulated_time_s', 'measurement_duration_s', 'measurement_interval',
    'total_sensors', 'total_sinks', 'alive_sensors', 'dead_sensors',
    'generated_packets', 'delivered_packets', 'dropped_packets', 'pending_packets',
    'packet_conservation_holds', 'drop_reasons', 'total_delivered_bytes',
    'total_delivered_bits', 'total_delivered_payload_bytes',
    'total_delivered_payload_bits', 'total_hops_delivered',
    'total_end_to_end_delay_s', 'throughput_bps', 'goodput_bps', 'pdr_percent',
    'average_hops', 'average_end_to_end_delay_s', 'initial_total_energy_j',
    'residual_total_energy_j', 'consumed_energy_sensors_j', 'route_change_count',
    'functional_network_death_s', 'functional_network_death_status',
    'network_lifetime_s', 'network_lifetime_definition', 'current_reachable_sensors',
    'current_reachability_ratio', 'current_reachability_state',
    'initial_sensor_count', 'hnd_dead_sensor_count', 'fnd_s', 'fnd_status', 'hnd_s',
    'hnd_status', 'lnd_s', 'lnd_status',
}

MANIFEST_FIELDS = {
    'configuration', 'generated_files', 'routing_algorithm', 'communication_range_m',
    'topology_seed', 'traffic_seed', 'requested_duration_s', 'actual_duration_s',
}


class InputDataError(ValueError):
    '''Raised when an exported file cannot be parsed as the published schema.'''


def _read_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open('r', newline='', encoding='utf-8') as file_handle:
            reader = csv.DictReader(file_handle)
            fields = reader.fieldnames
            if fields is None:
                raise InputDataError(f'{path.name}: missing CSV header')
            duplicates = sorted(name for name, count in Counter(fields).items() if count > 1)
            if duplicates:
                raise InputDataError(f'{path.name}: duplicate columns {duplicates}')
            missing = sorted(required - set(fields))
            if missing:
                raise InputDataError(f'{path.name}: missing required columns {missing}')
            rows = list(reader)
    except FileNotFoundError as exc:
        raise InputDataError(f'missing required file: {path.name}') from exc
    for index, row in enumerate(rows, start=2):
        if None in row:
            raise InputDataError(f'{path.name}:{index}: unexpected extra columns')
    return rows


def _read_json(path: Path, required: set[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise InputDataError(f'missing required file: {path.name}') from exc
    except json.JSONDecodeError as exc:
        raise InputDataError(f'{path.name}: invalid JSON: {exc}') from exc
    if not isinstance(value, dict):
        raise InputDataError(f'{path.name}: top-level value must be an object')
    missing = sorted(required - set(value))
    if missing:
        raise InputDataError(f'{path.name}: missing required fields {missing}')
    return value


def _number(
    value: Any,
    location: str,
    *,
    optional: bool = False,
    non_negative: bool = False,
) -> float | None:
    if value is None or value == '':
        if optional:
            return None
        raise InputDataError(f'{location}: numeric value is required')
    if isinstance(value, bool):
        raise InputDataError(f'{location}: boolean is not a numeric value')
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InputDataError(f'{location}: invalid numeric value {value!r}') from exc
    if not math.isfinite(result):
        raise InputDataError(f'{location}: value must be finite, got {value!r}')
    if non_negative and result < 0:
        raise InputDataError(f'{location}: value must be non-negative, got {value!r}')
    return result


def _integer(value: Any, location: str, *, non_negative: bool = False) -> int:
    if isinstance(value, bool):
        raise InputDataError(f'{location}: boolean is not an integer counter')
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        try:
            result = int(value.strip())
        except ValueError as exc:
            raise InputDataError(f'{location}: invalid integer value {value!r}') from exc
    else:
        raise InputDataError(f'{location}: invalid integer value {value!r}')
    if non_negative and result < 0:
        raise InputDataError(f'{location}: counter must be non-negative, got {result}')
    return result


def _boolean(value: Any, location: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == 'true':
            return True
        if normalized == 'false':
            return False
    raise InputDataError(f'{location}: expected true or false, got {value!r}')


def _same_number(left: Any, right: Any, tolerance: float) -> tuple[float | None, bool]:
    if left is None or right is None:
        return None, left is None and right is None
    difference = float(left) - float(right)
    return difference, math.isclose(
        float(left), float(right), rel_tol=0.0, abs_tol=tolerance
    )


def _physical_snapshot(
    adjacency: dict[str, set[str]],
    sensor_ids: set[str],
    sink_ids: set[str],
    dead_ids: set[str],
) -> tuple[int, int, float | None, str]:
    alive_ids = sensor_ids - dead_ids
    active_ids = alive_ids | sink_ids
    stack = list(sink_ids)
    visited = set(stack)
    while stack:
        current = stack.pop()
        for neighbor in adjacency[current]:
            if neighbor in active_ids and neighbor not in visited:
                visited.add(neighbor)
                stack.append(neighbor)
    reachable = len(alive_ids & visited)
    alive = len(alive_ids)
    ratio = reachable / alive if alive else None
    if alive == 0:
        state = 'all_dead'
    elif ratio is not None and ratio < 0.5:
        state = 'below_threshold'
    else:
        state = 'operational'
    return alive, reachable, ratio, state


def validate_run(
    run_dir: str | Path,
    output_path: str | Path | None = None,
    tolerance: float = ABSOLUTE_TOLERANCE,
    *,
    write_report: bool = True,
) -> dict[str, Any]:
    '''Validate one exported run without importing production metric helpers.'''
    if not math.isfinite(tolerance) or tolerance < 0:
        raise InputDataError('tolerance must be finite and non-negative')

    run_path = Path(run_dir)
    metrics = _read_json(run_path / 'metrics.json', METRIC_FIELDS)
    manifest = _read_json(run_path / 'run_manifest.json', MANIFEST_FIELDS)
    generated_files = manifest['generated_files']
    if not isinstance(generated_files, list) or not all(
        isinstance(item, str) for item in generated_files
    ):
        raise InputDataError('run_manifest.json.generated_files: expected a list of strings')
    schema_version = _integer(
        manifest.get('export_schema_version', 1),
        'run_manifest.json.export_schema_version',
        non_negative=True,
    )
    topology_path = run_path / 'topology_edges.csv'
    legacy_topology = (
        schema_version < 2
        and 'topology_edges.csv' not in generated_files
        and not topology_path.exists()
    )
    tables = {
        name: _read_csv(run_path / name, fields)
        for name, fields in CSV_FIELDS.items()
        if name != 'topology_edges.csv'
    }
    tables['topology_edges.csv'] = (
        []
        if legacy_topology
        else _read_csv(topology_path, CSV_FIELDS['topology_edges.csv'])
    )
    nodes = tables['nodes.csv']
    topology = tables['topology_edges.csv']
    packets = tables['packets.csv']
    ledger = tables['energy_ledger.csv']
    deaths = tables['node_deaths.csv']
    reachability = tables['reachability_events.csv']
    timeseries = tables['timeseries.csv']
    if not nodes:
        raise InputDataError('nodes.csv: at least one node is required')
    if not timeseries:
        raise InputDataError('timeseries.csv: at least one snapshot is required')
    if not reachability:
        raise InputDataError('reachability_events.csv: initial snapshot is required')

    checks: list[dict[str, Any]] = []

    def add(
        metric: str,
        recalculated: Any,
        reported: Any,
        *,
        exact: bool = False,
        passed: bool | None = None,
        detail: str = '',
        category: str = 'cross_check',
    ) -> None:
        difference: float | None = None
        if passed is None:
            if exact:
                passed = recalculated == reported
            else:
                difference, passed = _same_number(recalculated, reported, tolerance)
        elif (
            isinstance(recalculated, (int, float))
            and not isinstance(recalculated, bool)
            and isinstance(reported, (int, float))
            and not isinstance(reported, bool)
        ):
            difference = float(recalculated) - float(reported)
        checks.append({
            'metric': metric,
            'category': category,
            'recalculated_value': recalculated,
            'reported_value': reported,
            'difference': difference,
            'passed': bool(passed),
            'detail': detail,
        })

    def metric_number(
        name: str, *, optional: bool = False, non_negative: bool = True
    ) -> float | None:
        return _number(
            metrics[name], f'metrics.json.{name}', optional=optional,
            non_negative=non_negative,
        )

    def metric_integer(name: str) -> int:
        return _integer(metrics[name], f'metrics.json.{name}', non_negative=True)

    actual_duration = _number(
        manifest['actual_duration_s'], 'run_manifest.json.actual_duration_s',
        non_negative=True,
    )
    requested_duration = _number(
        manifest['requested_duration_s'], 'run_manifest.json.requested_duration_s',
        non_negative=True,
    )
    measurement_duration = metric_number('measurement_duration_s')
    simulated_time = metric_number('simulated_time_s')
    final_time = _number(
        timeseries[-1]['time_s'], f'timeseries.csv:{len(timeseries) + 1}.time_s',
        non_negative=True,
    )
    assert actual_duration is not None
    duration_values = [requested_duration, measurement_duration, simulated_time, final_time]
    duration_ok = all(
        value is not None
        and math.isclose(actual_duration, value, rel_tol=0.0, abs_tol=tolerance)
        for value in duration_values
    )
    add(
        'duration_consistency', actual_duration, duration_values,
        passed=duration_ok,
        detail='manifest requested/actual, metrics measurement/simulated and final snapshot must match',
    )
    add('measurement_interval', '[0, T)', metrics['measurement_interval'], exact=True)

    node_ids: set[str] = set()
    sensor_ids: set[str] = set()
    sink_ids: set[str] = set()
    node_by_id: dict[str, dict[str, Any]] = {}
    node_values: dict[str, dict[str, Any]] = {}
    duplicate_nodes: list[str] = []
    for index, row in enumerate(nodes, start=2):
        location = f'nodes.csv:{index}'
        node_id = row['node_id'].strip()
        if not node_id:
            raise InputDataError(f'{location}.node_id: value must not be empty')
        if node_id in node_ids:
            duplicate_nodes.append(node_id)
        node_ids.add(node_id)
        node_by_id[node_id] = row
        node_type = row['type']
        if node_type not in {'sensor', 'sink'}:
            raise InputDataError(f'{location}.type: expected sensor or sink')
        _number(row['x'], f'{location}.x')
        _number(row['y'], f'{location}.y')
        for field in (
            'generated_packets', 'received_packets', 'forwarded_packets', 'dropped_packets'
        ):
            _integer(row[field], f'{location}.{field}', non_negative=True)
        if node_type == 'sensor':
            sensor_ids.add(node_id)
            initial = _number(
                row['initial_energy_j'], f'{location}.initial_energy_j', non_negative=True
            )
            final = _number(row['energy_j'], f'{location}.energy_j', non_negative=True)
            alive = _boolean(row['is_alive'], f'{location}.is_alive')
            death_time = _number(
                row['death_time_s'], f'{location}.death_time_s', optional=True,
                non_negative=True,
            )
            tx_total = _number(
                row['tx_energy_total_j'], f'{location}.tx_energy_total_j',
                non_negative=True,
            )
            rx_total = _number(
                row['rx_energy_total_j'], f'{location}.rx_energy_total_j',
                non_negative=True,
            )
            node_values[node_id] = {
                'initial': initial, 'final': final, 'alive': alive,
                'death_time': death_time, 'tx_total': tx_total, 'rx_total': rx_total,
            }
        else:
            sink_ids.add(node_id)
    add(
        'unique_node_ids', len(node_ids), len(nodes),
        passed=not duplicate_nodes and len(node_ids) == len(nodes),
        detail=f'duplicates={sorted(set(duplicate_nodes))}', category='schema',
    )
    add('total_sensors', len(sensor_ids), metric_integer('total_sensors'), exact=True)
    add('total_sinks', len(sink_ids), metric_integer('total_sinks'), exact=True)
    add(
        'node_type_id_sets_disjoint', True, not bool(sensor_ids & sink_ids),
        passed=not bool(sensor_ids & sink_ids), category='schema',
    )

    communication_range = _number(
        manifest['communication_range_m'],
        'run_manifest.json.communication_range_m',
        non_negative=True,
    )
    if legacy_topology:
        sensor_rows = [node_by_id[node_id] for node_id in sorted(sensor_ids)]
        sink_rows = [node_by_id[node_id] for node_id in sorted(sink_ids)]
        reconstructed: list[dict[str, Any]] = []
        for left_index, left in enumerate(sensor_rows):
            candidates = sensor_rows[left_index + 1:] + sink_rows
            for right in candidates:
                distance = math.hypot(
                    float(left['x']) - float(right['x']),
                    float(left['y']) - float(right['y']),
                )
                if distance <= float(communication_range):
                    reconstructed.append({
                        'source_id': left['node_id'],
                        'target_id': right['node_id'],
                        'distance_m': distance,
                    })
        topology = reconstructed
    add(
        'topology_data_source',
        'legacy_reconstruction' if legacy_topology else 'exported_edges',
        'legacy_reconstruction' if legacy_topology else 'exported_edges',
        exact=True,
        detail=(
            'legacy schema: deterministically reconstructed from nodes.csv and '
            'run_manifest.json.communication_range_m'
            if legacy_topology else 'schema v2 topology_edges.csv'
        ),
        category='schema',
    )

    adjacency = {node_id: set() for node_id in node_ids}
    edge_distances: dict[frozenset[str], float] = {}
    topology_errors: list[str] = []
    for index, row in enumerate(topology, start=2):
        location = f'topology_edges.csv:{index}'
        source = row['source_id'].strip()
        target = row['target_id'].strip()
        distance = _number(row['distance_m'], f'{location}.distance_m', non_negative=True)
        if source not in node_ids or target not in node_ids:
            topology_errors.append(f'{location}: unknown endpoint {source!r}->{target!r}')
            continue
        edge_key = frozenset((source, target))
        if source == target:
            topology_errors.append(f'{location}: self edge {source!r}')
            continue
        if edge_key in edge_distances:
            topology_errors.append(f'{location}: duplicate undirected edge {source!r}-{target!r}')
            continue
        if source in sink_ids and target in sink_ids:
            topology_errors.append(f'{location}: sink-to-sink edge is not physical topology')
        source_row = node_by_id[source]
        target_row = node_by_id[target]
        coordinate_distance = math.hypot(
            float(source_row['x']) - float(target_row['x']),
            float(source_row['y']) - float(target_row['y']),
        )
        if not math.isclose(
            coordinate_distance, distance, rel_tol=0.0, abs_tol=tolerance
        ):
            topology_errors.append(
                f'{location}.distance_m: {distance!r} != coordinate distance '
                f'{coordinate_distance!r}'
            )
        edge_distances[edge_key] = float(distance)
        adjacency[source].add(target)
        adjacency[target].add(source)
    add(
        'topology_edge_validity', len(topology_errors), 0,
        passed=not topology_errors, detail='; '.join(topology_errors[:10]),
        category='schema',
    )
    required_output_names = (
        set(CSV_FIELDS) | {'metrics.json', 'run_manifest.json'}
    )
    if legacy_topology:
        required_output_names.remove('topology_edges.csv')
    missing_manifest_outputs = sorted(required_output_names - set(generated_files))
    add(
        'manifest_generated_files', len(missing_manifest_outputs), 0,
        passed=not missing_manifest_outputs,
        detail=f'missing={missing_manifest_outputs}', category='schema',
    )

    packet_ids: list[str] = []
    delivered_rows: list[dict[str, Any]] = []
    dropped_rows: list[dict[str, Any]] = []
    pending_rows: list[dict[str, Any]] = []
    packet_errors: list[str] = []
    total_hops = 0
    total_delay = 0.0
    total_bytes = 0
    total_payload_bytes = 0
    drop_reasons: Counter[str] = Counter()
    for index, row in enumerate(packets, start=2):
        location = f'packets.csv:{index}'
        packet_id = row['packet_id'].strip()
        if not packet_id:
            raise InputDataError(f'{location}.packet_id: value must not be empty')
        packet_ids.append(packet_id)
        source_id = row['source_id'].strip()
        if source_id not in sensor_ids:
            packet_errors.append(f'{location}.source_id: unknown sensor {source_id!r}')
        sequence = _integer(
            row['sequence_number'], f'{location}.sequence_number', non_negative=True
        )
        size = _integer(row['size_bytes'], f'{location}.size_bytes', non_negative=True)
        payload = _integer(
            row['payload_size_bytes'], f'{location}.payload_size_bytes', non_negative=True
        )
        if payload > size:
            packet_errors.append(
                f'{location}.payload_size_bytes: {payload} exceeds size_bytes={size}'
            )
        if sequence < 0:
            packet_errors.append(f'{location}.sequence_number: negative')
        created = _number(row['created_at'], f'{location}.created_at', non_negative=True)
        if created is not None and not (0 <= created < actual_duration):
            packet_errors.append(
                f'{location}.created_at: {created} outside [0,{actual_duration})'
            )
        status = row['status']
        if status not in {'CREATED', 'IN_TRANSIT', 'DELIVERED', 'DROPPED', 'NO_ROUTE'}:
            raise InputDataError(f'{location}.status: unsupported value {status!r}')
        path = [part for part in row['path'].split('->') if part]
        route = [part for part in row['route'].split('->') if part]
        unknown_path = [node_id for node_id in path + route if node_id not in node_ids]
        if unknown_path:
            packet_errors.append(f'{location}: path/route has unknown nodes {unknown_path}')
        hop_count = _integer(row['hop_count'], f'{location}.hop_count', non_negative=True)
        if hop_count != max(0, len(path) - 1):
            packet_errors.append(
                f'{location}.hop_count: {hop_count} != path hops {max(0, len(path) - 1)}'
            )
        sink_id = row['sink_id'].strip()
        delivered_at = _number(
            row['delivered_at'], f'{location}.delivered_at', optional=True,
            non_negative=True,
        )
        latency = _number(
            row['latency_s'], f'{location}.latency_s', optional=True,
            non_negative=True,
        )
        if status == 'DELIVERED':
            delivered_rows.append(row)
            if (
                delivered_at is None or created is None or delivered_at < created
                or not (0 <= delivered_at < actual_duration)
            ):
                packet_errors.append(f'{location}: invalid delivered timestamp interval')
            if not path or path[-1] not in sink_ids or sink_id != path[-1]:
                packet_errors.append(f'{location}: delivered path does not end at sink_id')
            calculated_delay = (
                delivered_at - created
                if delivered_at is not None and created is not None else None
            )
            if calculated_delay is None or not math.isclose(
                calculated_delay, latency if latency is not None else math.inf,
                rel_tol=0.0, abs_tol=tolerance,
            ):
                packet_errors.append(f'{location}.latency_s: does not match timestamps')
            total_hops += hop_count
            total_delay += calculated_delay or 0.0
            total_bytes += size
            total_payload_bytes += payload
        elif status in {'DROPPED', 'NO_ROUTE'}:
            dropped_rows.append(row)
            drop_reasons[row['drop_reason'] or 'unspecified'] += 1
            if delivered_at is not None or latency is not None:
                packet_errors.append(f'{location}: dropped packet has delivery fields')
        else:
            pending_rows.append(row)
            if delivered_at is not None or latency is not None:
                packet_errors.append(f'{location}: pending packet has delivery fields')
    duplicate_packet_ids = sorted(
        packet_id for packet_id, count in Counter(packet_ids).items() if count > 1
    )
    add(
        'unique_packet_ids', len(set(packet_ids)), len(packet_ids),
        passed=not duplicate_packet_ids,
        detail=f'duplicates={duplicate_packet_ids[:10]}', category='schema',
    )
    add(
        'packet_field_and_domain_validity', len(packet_errors), 0,
        passed=not packet_errors, detail='; '.join(packet_errors[:10]), category='schema',
    )

    counts = {
        'generated_packets': len(packets),
        'delivered_packets': len(delivered_rows),
        'dropped_packets': len(dropped_rows),
        'pending_packets': len(pending_rows),
    }
    for name, value in counts.items():
        add(name, value, metric_integer(name), exact=True)
    add(
        'packet_conservation', len(packets),
        len(delivered_rows) + len(dropped_rows) + len(pending_rows), exact=True,
    )
    add(
        'packet_conservation_holds', True, metrics['packet_conservation_holds'], exact=True
    )
    if not isinstance(metrics['drop_reasons'], dict):
        raise InputDataError('metrics.json.drop_reasons: expected an object')
    reported_drop_reasons = {
        str(key): _integer(value, f'metrics.json.drop_reasons.{key}', non_negative=True)
        for key, value in metrics['drop_reasons'].items()
    }
    add('drop_reasons', dict(drop_reasons), reported_drop_reasons, exact=True)

    add('total_hops_delivered', total_hops, metric_integer('total_hops_delivered'), exact=True)
    add('total_end_to_end_delay_s', total_delay, metric_number('total_end_to_end_delay_s'))
    add('total_delivered_bytes', total_bytes, metric_integer('total_delivered_bytes'), exact=True)
    add(
        'total_delivered_bits', total_bytes * 8, metric_integer('total_delivered_bits'),
        exact=True,
    )
    add(
        'total_delivered_payload_bytes', total_payload_bytes,
        metric_integer('total_delivered_payload_bytes'), exact=True,
    )
    add(
        'total_delivered_payload_bits', total_payload_bytes * 8,
        metric_integer('total_delivered_payload_bits'), exact=True,
    )
    throughput = 8.0 * total_bytes / actual_duration if actual_duration > 0 else None
    goodput = 8.0 * total_payload_bytes / actual_duration if actual_duration > 0 else None
    pdr = 100.0 * len(delivered_rows) / len(packets) if packets else None
    average_hops = total_hops / len(delivered_rows) if delivered_rows else None
    average_delay = total_delay / len(delivered_rows) if delivered_rows else None
    add('throughput_bps', throughput, metric_number('throughput_bps', optional=True))
    add('goodput_bps', goodput, metric_number('goodput_bps', optional=True))
    reported_pdr = metric_number('pdr_percent', optional=True)
    add(
        'pdr_domain', reported_pdr, '[0, 100] or null',
        passed=reported_pdr is None or 0 <= reported_pdr <= 100,
        category='domain',
    )
    add('pdr_percent', pdr, reported_pdr)
    add('average_hops', average_hops, metric_number('average_hops', optional=True))
    add(
        'average_end_to_end_delay_s', average_delay,
        metric_number('average_end_to_end_delay_s', optional=True),
    )

    energy_state = {
        node_id: float(values['initial']) for node_id, values in node_values.items()
    }
    tx_debit = {node_id: 0.0 for node_id in sensor_ids}
    rx_debit = {node_id: 0.0 for node_id in sensor_ids}
    ledger_transitions: list[dict[str, Any]] = []
    ledger_errors: list[str] = []
    previous_ledger_time = -math.inf
    failed_transaction_tx_debit = 0.0
    for index, row in enumerate(ledger, start=2):
        location = f'energy_ledger.csv:{index}'
        time_s = _number(row['time_s'], f'{location}.time_s', non_negative=True)
        distance = _number(row['distance_m'], f'{location}.distance_m', non_negative=True)
        tx = _number(row['tx_energy_j'], f'{location}.tx_energy_j', non_negative=True)
        rx = _number(row['rx_energy_j'], f'{location}.rx_energy_j', non_negative=True)
        sender = row['sender_id'].strip()
        receiver = row['receiver_id'].strip()
        success = _boolean(row['success'], f'{location}.success')
        sender_before = _number(
            row['sender_energy_before'], f'{location}.sender_energy_before', non_negative=True
        )
        sender_after = _number(
            row['sender_energy_after'], f'{location}.sender_energy_after', non_negative=True
        )
        if sender not in sensor_ids:
            ledger_errors.append(f'{location}.sender_id: unknown sensor {sender!r}')
            continue
        if receiver not in node_ids:
            ledger_errors.append(f'{location}.receiver_id: unknown node {receiver!r}')
            continue
        if frozenset((sender, receiver)) not in edge_distances:
            ledger_errors.append(f'{location}: endpoints are not a topology edge')
        if time_s is not None and not (0 <= time_s < actual_duration):
            ledger_errors.append(
                f'{location}.time_s: {time_s} outside [0,{actual_duration})'
            )
        if time_s is not None and time_s < previous_ledger_time:
            ledger_errors.append(f'{location}.time_s: ledger is not chronological')
        previous_ledger_time = float(time_s)
        if not math.isclose(
            energy_state[sender], sender_before, rel_tol=0.0, abs_tol=tolerance
        ):
            ledger_errors.append(
                f'{location}.sender_energy_before: discontinuity for {sender}'
            )
        expected_sender_after = max(0.0, float(sender_before) - float(tx))
        if not math.isclose(
            expected_sender_after, sender_after, rel_tol=0.0, abs_tol=tolerance
        ):
            ledger_errors.append(
                f'{location}.sender_energy_after: does not equal before minus TX debit'
            )
        tx_debit[sender] += float(tx)
        energy_state[sender] = expected_sender_after
        if sender_before > DEATH_ENERGY_TOLERANCE_J and (
            expected_sender_after <= DEATH_ENERGY_TOLERANCE_J
        ):
            ledger_transitions.append({
                'node_id': sender, 'death_time_s': time_s,
                'energy_before_j': sender_before, 'energy_after_j': expected_sender_after,
                'cause': 'tx',
            })

        if receiver in sensor_ids:
            receiver_before = _number(
                row['receiver_energy_before'], f'{location}.receiver_energy_before',
                non_negative=True,
            )
            receiver_after = _number(
                row['receiver_energy_after'], f'{location}.receiver_energy_after',
                non_negative=True,
            )
            if not math.isclose(
                energy_state[receiver], receiver_before, rel_tol=0.0,
                abs_tol=tolerance,
            ):
                ledger_errors.append(
                    f'{location}.receiver_energy_before: discontinuity for {receiver}'
                )
            expected_receiver_after = max(0.0, float(receiver_before) - float(rx))
            if not math.isclose(
                expected_receiver_after, receiver_after, rel_tol=0.0,
                abs_tol=tolerance,
            ):
                ledger_errors.append(
                    f'{location}.receiver_energy_after: does not equal before minus RX debit'
                )
            rx_debit[receiver] += float(rx)
            energy_state[receiver] = expected_receiver_after
            if receiver_before > DEATH_ENERGY_TOLERANCE_J and (
                expected_receiver_after <= DEATH_ENERGY_TOLERANCE_J
            ):
                ledger_transitions.append({
                    'node_id': receiver, 'death_time_s': time_s,
                    'energy_before_j': receiver_before,
                    'energy_after_j': expected_receiver_after, 'cause': 'rx',
                })
        else:
            if row['receiver_energy_before'] != '' or row['receiver_energy_after'] != '':
                ledger_errors.append(f'{location}: sink energy fields must be empty')
            if not math.isclose(float(rx), 0.0, rel_tol=0.0, abs_tol=tolerance):
                ledger_errors.append(f'{location}.rx_energy_j: sink RX debit must be zero')

        reason = row['reason']
        if success and reason != 'OK':
            ledger_errors.append(f'{location}.reason: successful transaction must be OK')
        if not success:
            failed_transaction_tx_debit += float(tx)
            if reason == 'TX_INSUFFICIENT_ENERGY':
                if not math.isclose(float(tx) + float(rx), 0.0, abs_tol=tolerance):
                    ledger_errors.append(f'{location}: insufficient TX must debit zero')
            elif reason == 'RX_INSUFFICIENT_ENERGY':
                if receiver not in sensor_ids or not math.isclose(
                    float(rx), 0.0, abs_tol=tolerance
                ):
                    ledger_errors.append(
                        f'{location}: insufficient RX must target sensor and debit RX zero'
                    )
            else:
                ledger_errors.append(f'{location}.reason: unsupported failure {reason!r}')
        if distance is None:
            ledger_errors.append(f'{location}.distance_m: required')
    add(
        'energy_ledger_integrity', len(ledger_errors), 0,
        passed=not ledger_errors, detail='; '.join(ledger_errors[:10]),
        category='schema',
    )
    add(
        'failed_transaction_tx_debit_accounted', failed_transaction_tx_debit,
        sum(
            float(row['tx_energy_j']) for row in ledger
            if row['success'].strip().lower() == 'false'
        ),
        detail='TX emitted before an RX failure remains part of the sender debit',
    )

    energy_errors: list[str] = []
    for node_id, values in node_values.items():
        final = float(values['final'])
        debit = tx_debit[node_id] + rx_debit[node_id]
        if not math.isclose(
            float(values['initial']) - final, debit, rel_tol=0.0, abs_tol=tolerance
        ):
            energy_errors.append(f'{node_id}: battery drop does not match TX+RX debit')
        if not math.isclose(energy_state[node_id], final, rel_tol=0.0, abs_tol=tolerance):
            energy_errors.append(f'{node_id}: ledger final energy does not match nodes.csv')
        if not math.isclose(
            tx_debit[node_id], float(values['tx_total']), rel_tol=0.0,
            abs_tol=tolerance,
        ):
            energy_errors.append(f'{node_id}: TX aggregate does not match nodes.csv')
        if not math.isclose(
            rx_debit[node_id], float(values['rx_total']), rel_tol=0.0,
            abs_tol=tolerance,
        ):
            energy_errors.append(f'{node_id}: RX aggregate does not match nodes.csv')
    add(
        'sensor_energy_debit_balance', len(energy_errors), 0,
        passed=not energy_errors, detail='; '.join(energy_errors[:10]),
    )
    initial_total_energy = sum(float(values['initial']) for values in node_values.values())
    residual_total_energy = sum(float(values['final']) for values in node_values.values())
    consumed_energy = initial_total_energy - residual_total_energy
    add(
        'initial_total_energy_j', initial_total_energy,
        metric_number('initial_total_energy_j')
    )
    add(
        'residual_total_energy_j', residual_total_energy,
        metric_number('residual_total_energy_j')
    )
    add(
        'consumed_energy_sensors_j', consumed_energy,
        metric_number('consumed_energy_sensors_j')
    )

    death_rows: list[dict[str, Any]] = []
    death_ids: list[str] = []
    death_errors: list[str] = []
    for index, row in enumerate(deaths, start=2):
        location = f'node_deaths.csv:{index}'
        node_id = row['node_id'].strip()
        time_s = _number(row['death_time_s'], f'{location}.death_time_s', non_negative=True)
        energy_before = _number(
            row['energy_before_j'], f'{location}.energy_before_j', non_negative=True
        )
        energy_after = _number(
            row['energy_after_j'], f'{location}.energy_after_j', non_negative=True
        )
        cause = row['cause']
        death_ids.append(node_id)
        parsed = {
            'node_id': node_id, 'death_time_s': time_s,
            'energy_before_j': energy_before, 'energy_after_j': energy_after,
            'cause': cause,
        }
        death_rows.append(parsed)
        if node_id not in sensor_ids:
            death_errors.append(f'{location}.node_id: unknown sensor {node_id!r}')
            continue
        if time_s is not None and not (0 <= time_s < actual_duration):
            death_errors.append(
                f'{location}.death_time_s: {time_s} outside [0,{actual_duration})'
            )
        if energy_before is not None and energy_before <= DEATH_ENERGY_TOLERANCE_J:
            death_errors.append(f'{location}.energy_before_j: node was not alive')
        if energy_after is not None and energy_after > DEATH_ENERGY_TOLERANCE_J:
            death_errors.append(
                f'{location}.energy_after_j: {energy_after} exceeds death threshold '
                f'{DEATH_ENERGY_TOLERANCE_J}'
            )
        if cause not in {'tx', 'rx'}:
            death_errors.append(f'{location}.cause: unsupported value {cause!r}')
        values = node_values[node_id]
        if values['alive'] or float(values['final']) > DEATH_ENERGY_TOLERANCE_J:
            death_errors.append(f'{location}: nodes.csv still marks {node_id} alive')
        _, same_time = _same_number(values['death_time'], time_s, tolerance)
        if not same_time:
            death_errors.append(f'{location}: death_time_s does not match nodes.csv')
        transition_match = any(
            transition['node_id'] == node_id
            and transition['cause'] == cause
            and _same_number(transition['death_time_s'], time_s, tolerance)[1]
            and _same_number(transition['energy_before_j'], energy_before, tolerance)[1]
            and _same_number(transition['energy_after_j'], energy_after, tolerance)[1]
            for transition in ledger_transitions
        )
        if not transition_match:
            death_errors.append(
                f'{location}: no matching alive-to-dead TX/RX ledger transition'
            )
    duplicate_deaths = sorted(
        node_id for node_id, count in Counter(death_ids).items() if count > 1
    )
    if duplicate_deaths:
        death_errors.append(f'duplicate death events for {duplicate_deaths}')
    death_id_set = set(death_ids)
    for node_id, values in node_values.items():
        should_be_dead = node_id in death_id_set
        if should_be_dead != (not bool(values['alive'])):
            death_errors.append(f'{node_id}: final alive state does not match death event set')
        if not should_be_dead and values['death_time'] is not None:
            death_errors.append(f'{node_id}: alive sensor has death_time_s')
    add(
        'node_death_event_integrity', len(death_errors), 0,
        passed=not death_errors, detail='; '.join(death_errors[:10]),
    )

    ordered_deaths = sorted(float(row['death_time_s']) for row in death_rows)
    initial_count = len(sensor_ids)
    half_count = math.ceil(initial_count / 2)
    fnd = ordered_deaths[0] if ordered_deaths else None
    hnd = ordered_deaths[half_count - 1] if len(ordered_deaths) >= half_count else None
    lnd = ordered_deaths[initial_count - 1] if len(ordered_deaths) >= initial_count else None
    add('initial_sensor_count', initial_count, metric_integer('initial_sensor_count'), exact=True)
    add('hnd_dead_sensor_count', half_count, metric_integer('hnd_dead_sensor_count'), exact=True)
    for name, value in (('fnd_s', fnd), ('hnd_s', hnd), ('lnd_s', lnd)):
        reported = metric_number(name, optional=True)
        add(name, value, reported)
        add(
            f'{name}_status', 'observed' if value is not None else 'not_observed',
            metrics[f'{name[:-2]}_status'], exact=True,
        )

    reachability_errors: list[str] = []
    replayed_reachability: list[dict[str, Any]] = []
    dead_ids: set[str] = set()
    previous_reach_time = -math.inf
    if len(reachability) != len(death_rows) + 1:
        reachability_errors.append(
            f'row count {len(reachability)} != initial + death events {len(death_rows) + 1}'
        )
    for offset, row in enumerate(reachability):
        index = offset + 2
        location = f'reachability_events.csv:{index}'
        time_s = _number(row['time_s'], f'{location}.time_s', non_negative=True)
        alive = _integer(row['alive_sensors'], f'{location}.alive_sensors', non_negative=True)
        reachable = _integer(
            row['reachable_sensors'], f'{location}.reachable_sensors', non_negative=True
        )
        ratio = _number(
            row['reachability_ratio'], f'{location}.reachability_ratio', optional=True,
            non_negative=True,
        )
        if time_s is not None and not (0 <= time_s < actual_duration):
            reachability_errors.append(
                f'{location}.time_s: {time_s} outside [0,{actual_duration})'
            )
        if time_s is not None and time_s < previous_reach_time:
            reachability_errors.append(f'{location}.time_s: events are not chronological')
        previous_reach_time = float(time_s)
        if reachable > alive or alive > initial_count:
            reachability_errors.append(
                f'{location}: require 0 <= reachable <= alive <= {initial_count}'
            )
        if offset == 0:
            if row['trigger'] != 'initial' or row['death_node_id'] != '' or time_s != 0.0:
                reachability_errors.append(f'{location}: invalid initial reachability event')
        elif offset - 1 < len(death_rows):
            death = death_rows[offset - 1]
            if (
                row['trigger'] != 'node_death'
                or row['death_node_id'] != death['node_id']
                or not _same_number(time_s, death['death_time_s'], tolerance)[1]
            ):
                reachability_errors.append(
                    f'{location}: event does not match ordered node death '
                    f'{death["node_id"]!r}'
                )
            dead_ids.add(str(death['node_id']))
        expected_alive, expected_reachable, expected_ratio, expected_state = (
            _physical_snapshot(adjacency, sensor_ids, sink_ids, dead_ids)
        )
        replayed_reachability.append({
            'time_s': time_s, 'alive': expected_alive, 'reachable': expected_reachable,
            'ratio': expected_ratio, 'state': expected_state,
        })
        if alive != expected_alive or reachable != expected_reachable:
            reachability_errors.append(
                f'{location}: counts ({alive},{reachable}) != topology replay '
                f'({expected_alive},{expected_reachable})'
            )
        if not _same_number(ratio, expected_ratio, tolerance)[1]:
            reachability_errors.append(
                f'{location}.reachability_ratio: {ratio!r} != {expected_ratio!r}'
            )
        if row['state'] != expected_state:
            reachability_errors.append(
                f'{location}.state: {row["state"]!r} != {expected_state!r}'
            )
    add(
        'reachability_event_integrity', len(reachability_errors), 0,
        passed=not reachability_errors,
        detail='; '.join(reachability_errors[:10]),
    )
    functional_death = next(
        (
            float(item['time_s']) for item in replayed_reachability
            if item['alive'] > 0 and item['ratio'] is not None and item['ratio'] < 0.5
        ),
        None,
    )
    reported_functional_death = metric_number(
        'functional_network_death_s', optional=True
    )
    add('functional_network_death_s', functional_death, reported_functional_death)
    add('network_lifetime_s', functional_death, metric_number('network_lifetime_s', optional=True))
    add(
        'functional_network_death_status',
        'observed' if functional_death is not None else 'not_observed',
        metrics['functional_network_death_status'], exact=True,
    )
    add(
        'network_lifetime_definition',
        'time_to_first_physical_reachability_ratio_below_0.5',
        metrics['network_lifetime_definition'], exact=True,
    )
    final_reachability = replayed_reachability[-1]
    add(
        'current_reachable_sensors', final_reachability['reachable'],
        metric_integer('current_reachable_sensors'), exact=True,
    )
    add(
        'current_reachability_ratio', final_reachability['ratio'],
        metric_number('current_reachability_ratio', optional=True),
    )
    add(
        'current_reachability_state', final_reachability['state'],
        metrics['current_reachability_state'], exact=True,
    )

    timeseries_errors: list[str] = []
    previous_snapshot_time = -math.inf
    deaths_with_order = list(enumerate(death_rows))
    for offset, row in enumerate(timeseries):
        index = offset + 2
        location = f'timeseries.csv:{index}'
        time_s = _number(row['time_s'], f'{location}.time_s', non_negative=True)
        is_final = offset == len(timeseries) - 1
        expected_kind = 'final' if is_final else ('initial' if offset == 0 else 'periodic')
        if row['snapshot_kind'] != expected_kind:
            timeseries_errors.append(
                f'{location}.snapshot_kind: {row["snapshot_kind"]!r} != {expected_kind!r}'
            )
        if is_final:
            if not _same_number(time_s, actual_duration, tolerance)[1]:
                timeseries_errors.append(f'{location}.time_s: final snapshot must be T')
        elif time_s is not None and not (0 <= time_s < actual_duration):
            timeseries_errors.append(
                f'{location}.time_s: non-final snapshot outside [0,{actual_duration})'
            )
        if time_s is not None and time_s < previous_snapshot_time:
            timeseries_errors.append(f'{location}.time_s: snapshots are not chronological')
        previous_snapshot_time = float(time_s)
        counters = {
            field: _integer(row[field], f'{location}.{field}', non_negative=True)
            for field in (
                'alive_sensors', 'dead_sensors', 'generated_packets',
                'delivered_packets', 'dropped_packets', 'pending_packets',
                'reachable_sensors', 'delivered_bytes', 'delivered_payload_bytes',
            )
        }
        _number(row['total_energy_j'], f'{location}.total_energy_j', non_negative=True)
        ratio = _number(
            row['reachability_ratio'], f'{location}.reachability_ratio', optional=True,
            non_negative=True,
        )
        if counters['alive_sensors'] + counters['dead_sensors'] != initial_count:
            timeseries_errors.append(f'{location}: alive + dead does not equal sensor count')
        if counters['reachable_sensors'] > counters['alive_sensors']:
            timeseries_errors.append(f'{location}: reachable exceeds alive')
        if (
            counters['delivered_packets'] + counters['dropped_packets']
            + counters['pending_packets'] != counters['generated_packets']
        ):
            timeseries_errors.append(f'{location}: packet counters do not conserve')
        dead_at_snapshot = set()
        if offset != 0:
            dead_at_snapshot = {
                str(death['node_id']) for _, death in deaths_with_order
                if float(death['death_time_s']) <= float(time_s)
            }
        expected_alive, expected_reachable, expected_ratio, expected_state = (
            _physical_snapshot(adjacency, sensor_ids, sink_ids, dead_at_snapshot)
        )
        if (
            counters['alive_sensors'] != expected_alive
            or counters['reachable_sensors'] != expected_reachable
            or not _same_number(ratio, expected_ratio, tolerance)[1]
            or row['reachability_state'] != expected_state
        ):
            timeseries_errors.append(f'{location}: reachability does not match topology replay')
    add(
        'timeseries_integrity', len(timeseries_errors), 0,
        passed=not timeseries_errors, detail='; '.join(timeseries_errors[:10]),
    )
    final = timeseries[-1]
    final_matches = (
        _integer(final['alive_sensors'], 'timeseries.final.alive_sensors', non_negative=True)
        == metric_integer('alive_sensors')
        and _integer(final['dead_sensors'], 'timeseries.final.dead_sensors', non_negative=True)
        == metric_integer('dead_sensors')
        and _integer(final['generated_packets'], 'timeseries.final.generated_packets', non_negative=True)
        == len(packets)
        and _integer(final['delivered_packets'], 'timeseries.final.delivered_packets', non_negative=True)
        == len(delivered_rows)
        and _integer(final['dropped_packets'], 'timeseries.final.dropped_packets', non_negative=True)
        == len(dropped_rows)
        and _integer(final['pending_packets'], 'timeseries.final.pending_packets', non_negative=True)
        == len(pending_rows)
        and _same_number(
            _number(final['total_energy_j'], 'timeseries.final.total_energy_j'),
            residual_total_energy, tolerance,
        )[1]
    )
    add('final_timeseries_snapshot', final_matches, True, exact=True)
    add(
        'alive_sensors', initial_count - len(death_id_set), metric_integer('alive_sensors'),
        exact=True,
    )
    add('dead_sensors', len(death_id_set), metric_integer('dead_sensors'), exact=True)
    metric_integer('route_change_count')

    report = {
        'run_directory': str(run_path),
        'absolute_tolerance': tolerance,
        'death_energy_tolerance_j': DEATH_ENERGY_TOLERANCE_J,
        'passed': all(check['passed'] for check in checks),
        'checks': checks,
    }
    if write_report:
        destination = Path(output_path) if output_path else run_path / 'validation.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
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
    except (OSError, InputDataError) as exc:
        print(f'VALIDATION ERROR: {exc}', file=sys.stderr)
        return 2
    passed = sum(1 for check in report['checks'] if check['passed'])
    total = len(report['checks'])
    print(f'Validation: {passed}/{total} checks passed')
    if not report['passed']:
        for check in report['checks']:
            if not check['passed']:
                print(f'FAIL {check["metric"]}: {check["detail"]}')
    print(f'Result: {"PASS" if report["passed"] else "FAIL"}')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
