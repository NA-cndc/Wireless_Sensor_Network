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

from scripts.plot_metrics import (
    _cumulative_delivery_points,
    _drop_category_breakdown,
    _windowed_rates,
)
from scripts.validate_metrics import InputDataError, validate_run
from wsn_sim.config import SimulationConfig
from wsn_sim.energy import RadioModel
from wsn_sim.models import Packet, Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.validation_fixtures import build_real_traffic_lifetime_network

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


def _export_changed_reroute(run_dir: Path) -> Path:
    base = SimulationConfig.from_json(PROJECT_ROOT / 'configs' / 'default.json')
    config = replace(
        base, num_sensors=3, num_sinks=1, packet_interval_s=10.0
    )
    tx_cost = RadioModel().compute_tx_energy(config.packet_size_bytes * 8, 50.0)
    network = Network(config, communication_range_m=120.0)
    source = Sensor('S1', 0.0, 0.0, 5.0)
    first_relay = Sensor('R1', 50.0, 0.0, tx_cost)
    alternate = Sensor('R2', 0.0, 50.0, 5.0)
    sink = Sink('sink_00', 100.0, 0.0)
    network.sensors = {'S1': source, 'R1': first_relay, 'R2': alternate}
    network.sinks = {'sink_00': sink}
    network.graph = nx.Graph()
    for node in (source, first_relay, alternate, sink):
        network.graph.add_node(
            node.node_id,
            node_type='sink' if isinstance(node, Sink) else 'sensor',
            x=node.x,
            y=node.y,
        )
    for left, right in (
        ('S1', 'R1'), ('R1', 'sink_00'),
        ('S1', 'R2'), ('R2', 'sink_00'),
    ):
        left_node = network.sensors.get(left) or network.sinks[left]
        right_node = network.sensors.get(right) or network.sinks[right]
        distance = left_node.distance_to(right_node)
        network.graph.add_edge(left, right, distance_m=distance, weight=distance)
    network.communication_range_m = 120.0

    simulation = Simulation(network, routing_algorithm='MHR', quiet=True, seed=42)
    assert simulation.traffic_gen is not None
    packet = Packet(
        'reroute_packet', 'S1', created_at=0.0,
        size_bytes=128, payload_size_bytes=128, sequence_number=1,
        created_event_seq=simulation.next_event_seq(),
    )
    route = simulation.router.get_route('S1', is_source=True)
    assert route == ['S1', 'R1', 'sink_00']
    simulation.router.record_route_event(
        time_s=0.0, source_id='S1', packet_id=packet.packet_id,
        current_node_id='S1', old_route='', new_route=route,
        reason='initial_route', outcome='initial_route',
    )
    packet.assign_route(route)
    simulation.traffic_gen.generated_packets.append(packet)
    simulation.traffic_gen.queues['S1'].append(packet)
    source.generated_packets += 1

    death = simulation.radio.attempt_transmission(
        first_relay, sink, 128, 50.0, sim_time_s=0.0,
        packet_id='setup_relay_death',
    )
    assert death['success'] is True
    assert first_relay.is_alive is False
    simulation.run_for(1.0)
    simulation.export_results(run_dir)
    assert any(
        event['outcome'] == 'changed' for event in simulation.router.route_events
    )
    assert validate_run(run_dir)['passed'] is True
    return run_dir


def _export_real_traffic_lifetime(run_dir: Path) -> Path:
    base = SimulationConfig.from_json(PROJECT_ROOT / 'configs' / 'default.json')
    config = replace(
        base,
        num_sensors=4,
        num_sinks=1,
        packet_size_bytes=128,
        payload_size_bytes=128,
        packet_interval_s=10.0,
    )
    network = build_real_traffic_lifetime_network(config)
    simulation = Simulation(
        network, routing_algorithm='MHR', quiet=True, seed=42
    )
    simulation.run_for(41.0)
    simulation.export_results(run_dir)
    metrics = simulation.get_metrics()
    assert metrics['fnd_s'] == pytest.approx(10.004096)
    assert metrics['hnd_s'] == pytest.approx(20.004096)
    assert metrics['lnd_s'] == pytest.approx(40.004096)
    assert metrics['generated_packets'] == metrics['delivered_packets'] == 10
    assert validate_run(run_dir)['passed'] is True
    return run_dir


def _export_emhr_changed_reroute(run_dir: Path) -> Path:
    base = SimulationConfig.from_json(PROJECT_ROOT / 'configs' / 'default.json')
    config = replace(base, num_sensors=3, num_sinks=1)
    network = Network(config, communication_range_m=1100.0)
    source = Sensor('S1', 0.0, 0.0, 5.0)
    alternate = Sensor('R2', 0.0, 50.0, 5.0)
    sink = Sink('sink_00', 1000.0, 0.0)
    relay_distance = 950.0
    relay_energy = RadioModel().compute_tx_energy(
        config.packet_size_bytes * 8, relay_distance
    )
    assert relay_energy > config.initial_energy_j * 0.20
    first_relay = Sensor('R1', 50.0, 0.0, relay_energy)
    network.sensors = {'S1': source, 'R1': first_relay, 'R2': alternate}
    network.sinks = {'sink_00': sink}
    network.graph = nx.Graph()
    for node in (source, first_relay, alternate, sink):
        network.graph.add_node(
            node.node_id,
            node_type='sink' if isinstance(node, Sink) else 'sensor',
            x=node.x,
            y=node.y,
        )
    for left, right in (
        ('S1', 'R1'), ('R1', 'sink_00'),
        ('S1', 'R2'), ('R2', 'sink_00'),
    ):
        left_node = network.sensors.get(left) or network.sinks[left]
        right_node = network.sensors.get(right) or network.sinks[right]
        distance = left_node.distance_to(right_node)
        network.graph.add_edge(left, right, distance_m=distance, weight=distance)
    network.communication_range_m = 1100.0

    simulation = Simulation(network, routing_algorithm='EMHR', quiet=True, seed=42)
    assert simulation.traffic_gen is not None
    packet = Packet(
        'emhr_reroute_packet', 'S1', created_at=0.0,
        size_bytes=128, payload_size_bytes=128, sequence_number=1,
        created_event_seq=simulation.next_event_seq(),
    )
    route = simulation.router.get_route('S1', is_source=True)
    assert route == ['S1', 'R1', 'sink_00']
    simulation.router.record_route_event(
        time_s=0.0, source_id='S1', packet_id=packet.packet_id,
        current_node_id='S1', old_route='', new_route=route,
        reason='initial_route', outcome='initial_route',
    )
    packet.assign_route(route)
    simulation.traffic_gen.generated_packets.append(packet)
    simulation.traffic_gen.queues['S1'].append(packet)
    source.generated_packets += 1
    death = simulation.radio.attempt_transmission(
        first_relay, sink, 128, relay_distance, sim_time_s=0.0,
        packet_id='setup_emhr_relay_death',
    )
    assert death['success'] is True
    assert first_relay.is_alive is False
    simulation.run_for(1.0)
    simulation.export_results(run_dir)
    changed = [
        event for event in simulation.router.route_events
        if event['outcome'] == 'changed'
    ]
    assert changed and changed[0]['new_route'] == 'S1->R2->sink_00'
    assert validate_run(run_dir)['passed'] is True
    return run_dir


@pytest.fixture
def valid_run(tmp_path: Path) -> Path:
    return _export_valid_run(tmp_path / 'valid_run')


@pytest.fixture
def death_run(tmp_path: Path) -> Path:
    return _export_simultaneous_deaths(tmp_path / 'death_run')


@pytest.fixture
def changed_route_run(tmp_path: Path) -> Path:
    return _export_changed_reroute(tmp_path / 'changed_route_run')


@pytest.fixture
def real_lifetime_run(tmp_path: Path) -> Path:
    return _export_real_traffic_lifetime(tmp_path / 'real_lifetime_run')


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


@pytest.mark.parametrize(
    'updates',
    [
        {
            'routing_eligible_sensors': '0',
            'routing_eligible_ratio': '0.0',
            'energy_feasible_sensors': '0',
            'energy_feasible_ratio': '0.0',
        },
        {
            'routing_eligible_sensors': '0',
            'routing_eligible_ratio': '0.0',
        },
        {
            'energy_feasible_sensors': '999',
            'energy_feasible_ratio': '2.0',
        },
        {'energy_feasible_ratio': ''},
    ],
)
def test_snapshot_feasibility_corruption_is_rejected(
    valid_run: Path, updates: dict[str, str]
):
    _mutate_csv(
        valid_run / 'timeseries.csv',
        lambda rows: rows[0].update(updates),
    )
    assert 'timeseries_integrity' in _failed_checks(valid_run)


def test_all_dead_snapshot_keeps_undefined_feasibility_ratio(death_run: Path):
    rows = list(csv.DictReader((death_run / 'timeseries.csv').open(encoding='utf-8')))
    final = rows[-1]
    assert final['alive_sensors'] == '0'
    assert final['energy_feasible_sensors'] == '0'
    assert final['energy_feasible_ratio'] == ''
    assert validate_run(death_run)['passed'] is True


@pytest.mark.parametrize(
    ('corruption', 'value'),
    [
        ('changed_same', ''),
        ('source_mismatch', 'R2'),
        ('unknown_node', 'S1->unknown->sink_00'),
        ('missing_edge', 'S1->R2->R1->sink_00'),
        ('repeated_node', 'S1->R2->S1->R1->sink_00'),
        ('not_sink_terminated', 'S1->R2'),
        ('unchanged_different', ''),
        ('failed_with_route', ''),
    ],
)
def test_route_event_semantic_corruption_is_rejected(
    changed_route_run: Path, corruption: str, value: str
):
    def mutate(rows: list[dict[str, str]]) -> None:
        event = next(row for row in rows if row['outcome'] == 'changed')
        if corruption == 'changed_same':
            event['new_route'] = event['old_route']
        elif corruption == 'source_mismatch':
            event['source_id'] = value
        elif corruption in {
            'unknown_node', 'missing_edge', 'repeated_node', 'not_sink_terminated'
        }:
            event['new_route'] = value
        elif corruption == 'unchanged_different':
            event['outcome'] = 'unchanged'
        elif corruption == 'failed_with_route':
            event['outcome'] = 'failed'

    _mutate_csv(changed_route_run / 'route_events.csv', mutate)
    failed = _failed_checks(changed_route_run)
    assert failed & {
        'route_event_field_and_domain_validity', 'route_event_semantics'
    }


def test_emhr_new_route_relay_below_eth_is_rejected(tmp_path: Path):
    run_dir = _export_emhr_changed_reroute(tmp_path / 'emhr_changed_route')

    def lower_alternate_relay_energy(rows: list[dict[str, str]]) -> None:
        relay = next(row for row in rows if row['node_id'] == 'R2')
        relay['initial_energy_j'] = '0.5'
        relay['energy_j'] = '0.5'

    _mutate_csv(run_dir / 'nodes.csv', lower_alternate_relay_energy)
    report = validate_run(run_dir)
    semantic = next(
        check for check in report['checks']
        if check['metric'] == 'route_event_semantics'
    )
    assert semantic['passed'] is False
    assert "EMHR relay 'R2' is below Eth" in semantic['detail']


@pytest.mark.parametrize(
    ('old_route', 'new_route', 'outcome'),
    [
        (['S1', 'sink_00'], ['S1', 'sink_00'], 'changed'),
        (['S1', 'sink_00'], ['S1', 'R1', 'sink_00'], 'unchanged'),
        ('', ['S1', 'sink_00'], 'failed'),
        (['S1', 'sink_00'], ['S1', 'R1', 'sink_00'], 'initial_route'),
    ],
)
def test_record_route_event_rejects_self_contradictory_outcomes(
    old_route, new_route, outcome
):
    simulation = Simulation(
        _star_network(), routing_algorithm='MHR', quiet=True, seed=42
    )
    with pytest.raises(ValueError):
        simulation.router.record_route_event(
            time_s=0.0, source_id='S1', packet_id='p1',
            current_node_id='S1', old_route=old_route, new_route=new_route,
            reason='route_invalid', outcome=outcome,
        )


def test_cumulative_delivery_points_use_actual_delivery_events():
    packets = [
        {
            'packet_id': 'p3', 'status': 'DELIVERED', 'delivered_at': '2.0',
            'delivered_event_seq': '7', 'size_bytes': '20',
        },
        {
            'packet_id': 'p1', 'status': 'DELIVERED', 'delivered_at': '1.0',
            'delivered_event_seq': '3', 'size_bytes': '10',
        },
        {
            'packet_id': 'p2', 'status': 'DELIVERED', 'delivered_at': '1.0',
            'delivered_event_seq': '4', 'size_bytes': '15',
        },
        {
            'packet_id': 'pending', 'status': 'CREATED', 'delivered_at': '',
            'delivered_event_seq': '', 'size_bytes': '99',
        },
    ]
    points = _cumulative_delivery_points(packets, 3.0)
    assert [(p['time_s'], p['delivered_bits']) for p in points] == [
        (0.0, 0), (1.0, 200), (2.0, 360), (3.0, 360),
    ]
    assert points[1]['delivery_events'] == 2
    assert [p['point_kind'] for p in points] == [
        'initial', 'delivery', 'delivery', 'observation_end',
    ]


def test_cumulative_delivery_points_handle_no_delivery_and_reject_duplicates():
    pending = [{
        'packet_id': 'p1', 'status': 'CREATED', 'delivered_at': '',
        'delivered_event_seq': '', 'size_bytes': '128',
    }]
    assert [p['delivered_bits'] for p in _cumulative_delivery_points(pending, 5.0)] == [0, 0]
    with pytest.raises(ValueError, match='duplicate packet_id'):
        _cumulative_delivery_points([pending[0], dict(pending[0])], 5.0)


def test_windowed_rates_use_actual_final_window_and_duration_weighting():
    packets = [
        {
            'packet_id': 'boundary', 'status': 'DELIVERED',
            'created_at': '10.0', 'delivered_at': '10.0',
            'size_bytes': '100', 'payload_size_bytes': '80',
        },
        {
            'packet_id': 'final', 'status': 'DELIVERED',
            'created_at': '100.0', 'delivered_at': '100.5',
            'size_bytes': '100', 'payload_size_bytes': '80',
        },
    ]
    windows = _windowed_rates(packets, 101.0, 10.0)
    assert windows[1]['delivered_bytes'] == 100
    assert windows[-1]['window_start_s'] == 100.0
    assert windows[-1]['duration_s'] == 1.0
    assert windows[-1]['throughput_bps'] == 800.0
    weighted = sum(
        row['throughput_bps'] * row['duration_s'] for row in windows
    ) / 101.0
    assert weighted == pytest.approx(8.0 * 200 / 101.0)


def test_multiple_drop_categories_conserve_stacked_total():
    packets = [
        {'status': 'DROPPED', 'drop_category': 'routing_policy',
         'drop_detail': 'relay_below_threshold'},
        {'status': 'NO_ROUTE', 'drop_category': 'unreachable',
         'drop_detail': 'unreachable'},
        {'status': 'DROPPED', 'drop_category': 'queue_drop',
         'drop_detail': 'queue_drop'},
        {'status': 'DELIVERED', 'drop_category': '', 'drop_detail': ''},
    ]
    categories, details, total = _drop_category_breakdown(packets)
    assert total == 3
    assert sum(categories.values()) == total
    assert sum(details.values()) == total
    assert categories == {
        'routing_policy': 1, 'unreachable': 1, 'queue_drop': 1,
    }


def test_reference_mhr_r300_delivery_curve_known_answers():
    run_dir = (
        PROJECT_ROOT / 'results' / 'metrics_pilot_seed42_101s_schema'
        / 'MHR_R300m_seed42'
    )
    packets = list(csv.DictReader((run_dir / 'packets.csv').open(encoding='utf-8')))
    points = _cumulative_delivery_points(packets, 101.0)

    def value_at(time_s: float) -> int:
        return max(
            point['delivered_bits']
            for point in points
            if point['time_s'] <= time_s
        )

    assert value_at(15.0) == 460800
    assert value_at(25.0) == 921600
    assert value_at(95.0) == 4147200
    assert points[-1]['delivered_bits'] == 4608000
    assert all(
        left['delivered_bits'] <= right['delivered_bits']
        for left, right in zip(points, points[1:])
    )


def _summary_row(run_dir: Path, scenario: str) -> dict[str, object]:
    metrics = json.loads((run_dir / 'metrics.json').read_text(encoding='utf-8'))
    manifest = json.loads((run_dir / 'run_manifest.json').read_text(encoding='utf-8'))
    return {
        'scenario': scenario,
        'algorithm': manifest['routing_algorithm'],
        'range_m': manifest['communication_range_m'],
        'seed': manifest['topology_seed'],
        'requested_duration_s': manifest['requested_duration_s'],
        'actual_duration_s': metrics['measurement_duration_s'],
        'generated_packets': metrics['generated_packets'],
        'delivered_packets': metrics['delivered_packets'],
        'dropped_packets': metrics['dropped_packets'],
        'pending_packets': metrics['pending_packets'],
        'pdr_percent': metrics['pdr_percent'],
        'throughput_bps': metrics['throughput_bps'],
        'goodput_bps': metrics['goodput_bps'],
        'offered_rate_bps': metrics['offered_rate_bps'],
        'configured_rate_bps': metrics['configured_rate_bps'],
        'energy_per_delivered_bit_j': metrics['energy_per_delivered_bit_j'],
        'average_hops': metrics['average_hops'],
        'average_end_to_end_delay_s': metrics['average_end_to_end_delay_s'],
        'fnd_s': metrics['fnd_s'],
        'fnd_status': metrics['fnd_status'],
        'hnd_s': metrics['hnd_s'],
        'hnd_status': metrics['hnd_status'],
        'lnd_s': metrics['lnd_s'],
        'lnd_status': metrics['lnd_status'],
        'functional_network_death_s': metrics['functional_network_death_s'],
        'functional_network_death_status': metrics['functional_network_death_status'],
        'network_lifetime_s': metrics['network_lifetime_s'],
        'network_lifetime_status': metrics['network_lifetime_status'],
        'network_lifetime_definition': metrics['network_lifetime_definition'],
        'energy_service_lifetime_sampled_s': metrics['energy_service_lifetime_sampled_s'],
        'energy_service_lifetime_status': metrics['energy_service_lifetime_status'],
        'energy_service_lifetime_definition': metrics['energy_service_lifetime_definition'],
        'serviceability_sample_interval_s': metrics['serviceability_sample_interval_s'],
        'measurement_interval': metrics['measurement_interval'],
        'delivered_bits_at_fnd': metrics['delivered_bits_at_fnd'],
        'delivered_bits_at_hnd': metrics['delivered_bits_at_hnd'],
        'delivered_bits_at_lnd': metrics['delivered_bits_at_lnd'],
        'relay_jain_fairness': metrics['relay_jain_fairness'],
        'route_recompute_count': metrics['route_recompute_count'],
        'route_change_count': metrics['route_change_count'],
        'route_failure_count': metrics['route_failure_count'],
        'validation_passed': True,
        'output_dir': scenario,
    }


def _make_pilot(root: Path) -> Path:
    root.mkdir(parents=True)
    scenario = 'MHR_R250m_seed42'
    run_dir = _export_valid_run(root / scenario)
    summary = _summary_row(run_dir, scenario)
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


def test_plotter_rejects_tampered_lifetime_status(tmp_path: Path):
    pilot = _make_pilot(tmp_path / 'pilot')
    _mutate_summary(pilot, 'fnd_status', 'observed')
    completed = _run_plotter(pilot, output=tmp_path / 'figures')
    assert completed.returncode != 0
    assert 'fnd_status' in completed.stderr


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
    assert len(list((pilot / 'figures').glob('*.png'))) == 13
    with (pilot / 'figures' / '02_pdr_by_range.csv').open(
        newline='', encoding='utf-8'
    ) as file_handle:
        reader = csv.DictReader(file_handle)
        pdr_fields = list(reader.fieldnames or [])
        pdr_rows = list(reader)
    assert pdr_rows
    assert 'dropped_packets' in pdr_fields
    assert 'pending_packets' in pdr_fields
    assert 'lost_packets' not in pdr_fields
    milestone_bits = list(csv.DictReader(
        (pilot / 'figures' / '14_delivered_bits_at_lifetime_milestones.csv').open(
            encoding='utf-8'
        )
    ))
    assert {row['status'] for row in milestone_bits} == {'not_observed'}
    assert {row['delivered_bits'] for row in milestone_bits} == {''}


def test_plotter_handles_all_dead_undefined_feasibility_ratio(
    tmp_path: Path, real_lifetime_run: Path
):
    pilot = tmp_path / 'all_dead_pilot'
    pilot.mkdir()
    scenario = 'MHR_R250m_seed42'
    run_dir = pilot / scenario
    shutil.copytree(real_lifetime_run, run_dir)
    summary = _summary_row(run_dir, scenario)
    _write_csv(pilot / 'pilot_summary.csv', [summary], list(summary))
    (pilot / 'pilot_manifest.json').write_text(
        json.dumps({'requested_scenarios': 1, 'completed_scenarios': 1}) + '\n',
        encoding='utf-8',
    )

    completed = _run_plotter(pilot)
    assert completed.returncode == 0, completed.stderr
    output = pilot / 'figures'
    assert (output / '09_energy_feasible_ratio_over_time.png').exists()
    rows = list(csv.DictReader(
        (output / '09_energy_feasible_ratio_over_time.csv').open(encoding='utf-8')
    ))
    assert rows[-1]['alive_sensors'] == '0'
    assert rows[-1]['energy_feasible_sensors'] == '0'
    assert rows[-1]['energy_feasible_ratio'] == ''
    assert rows[-1]['status'] == 'undefined_no_alive_sensors'
    plot_manifest = json.loads((output / 'plot_manifest.json').read_text())
    assert '09_energy_feasible_ratio_over_time.png' in plot_manifest['figures']


def test_plotter_rejects_legacy_run_without_exported_topology(tmp_path: Path):
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
    assert completed.returncode != 0
    assert 'schema v4' in completed.stderr


def test_plotter_lifetime_status_delay_units_and_managed_outputs(tmp_path: Path):
    pilot = _make_pilot(tmp_path / 'pilot')
    output = pilot / 'figures'
    output.mkdir()
    (output / '07_controlled_lifetime_fixture.png').write_bytes(b'stale')
    (output / '07_controlled_lifetime_fixture.csv').write_text('stale\n')
    (output / 'user_notes.csv').write_text('keep\n')

    completed = _run_plotter(pilot)
    assert completed.returncode == 0, completed.stderr
    lifetime = list(csv.DictReader(
        (output / '06_pilot_lifetime_milestones.csv').open(encoding='utf-8')
    ))
    assert lifetime
    assert {row['status'] for row in lifetime} == {'not_observed'}
    assert {row['time_s'] for row in lifetime} == {''}
    assert {row['observation_interval'] for row in lifetime} == {'[0,11 s)'}

    delay = list(csv.DictReader(
        (output / '05_average_delay_by_range.csv').open(encoding='utf-8')
    ))
    metrics = json.loads(
        (pilot / 'MHR_R250m_seed42' / 'metrics.json').read_text(encoding='utf-8')
    )
    assert float(delay[0]['average_end_to_end_delay_ms']) == pytest.approx(
        metrics['average_end_to_end_delay_s'] * 1000.0
    )
    assert not (output / '07_controlled_lifetime_fixture.png').exists()
    assert not (output / '07_controlled_lifetime_fixture.csv').exists()
    assert (output / 'user_notes.csv').read_text() == 'keep\n'
    plot_manifest = json.loads((output / 'plot_manifest.json').read_text())
    assert '07_controlled_lifetime_fixture.png' not in plot_manifest['figures']
    assert 'user_notes.csv' not in plot_manifest['source_tables']


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
    plotted = _run_plotter(output)
    assert plotted.returncode == 0, plotted.stderr
    controlled_source = list(csv.DictReader(
        (output / 'figures' / '07_controlled_lifetime_fixture.csv').open(encoding='utf-8')
    ))
    assert controlled_source[0]['label'] == 'initial'
    assert controlled_source[0]['time_s'] == '0.0'
    assert controlled_source[0]['cumulative_dead_sensors'] == '0'
    assert any(row['label'] == 'observation_end' for row in controlled_source)
