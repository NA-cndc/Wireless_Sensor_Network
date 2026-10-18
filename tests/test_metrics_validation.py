'''Known-answer, lifetime, event-boundary and validator regression tests.'''

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pytest

from scripts.validate_metrics import validate_run
from wsn_sim.config import SimulationConfig
from wsn_sim.energy import RadioModel
from wsn_sim.metrics import (
    calculate_lifetime_milestones,
    calculate_simulation_metrics,
)
from wsn_sim.models import Packet, Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation


def _known_answer_components():
    sensors = {
        f'sensor_{index}': Sensor(f'sensor_{index}', float(index), 0.0, 5.0)
        for index in range(4)
    }
    sink = Sink('sink_00', 10.0, 0.0)
    config = SimpleNamespace(initial_energy_j=5.0)
    network = SimpleNamespace(
        sensors=sensors,
        sinks={sink.node_id: sink},
        config=config,
    )

    first = Packet(
        'p1',
        'sensor_0',
        0.0,
        128,
        payload_size_bytes=100,
    )
    first.assign_route(['sensor_0', 'sink_00'])
    first.mark_delivered(0.1, 'sink_00')

    second = Packet(
        'p2',
        'sensor_1',
        0.0,
        128,
        payload_size_bytes=100,
    )
    second.assign_route(['sensor_1', 'sink_00'])
    second.path = ['sensor_1', 'relay_a', 'relay_b', 'sink_00']
    second.mark_delivered(0.3, 'sink_00')

    dropped = Packet('p3', 'sensor_2', 0.0, 128, payload_size_bytes=100)
    dropped.mark_dropped('unreachable', no_route=True, sim_time_s=0.2)
    pending = Packet('p4', 'sensor_3', 0.0, 128, payload_size_bytes=100)

    traffic = SimpleNamespace(
        generated_packets=[first, second, dropped, pending],
        delivered_packets=[first, second],
        dropped_packets=[dropped],
    )
    radio = RadioModel()
    router = SimpleNamespace(route_change_count=0)
    history = [
        {
            'time_s': 0.0,
            'alive_sensors': 4,
            'reachable_sensors': 4,
            'reachability_ratio': 1.0,
            'state': 'operational',
        }
    ]
    return network, traffic, radio, router, history


def test_known_answer_packet_metrics():
    network, traffic, radio, router, history = _known_answer_components()
    metrics = calculate_simulation_metrics(
        network,
        traffic,
        radio,
        10.0,
        router,
        history,
    )
    assert metrics['generated_packets'] == 4
    assert metrics['delivered_packets'] == 2
    assert metrics['dropped_packets'] == 1
    assert metrics['pending_packets'] == 1
    assert metrics['pdr_percent'] == pytest.approx(50.0)
    assert metrics['throughput_bps'] == pytest.approx(204.8)
    assert metrics['goodput_bps'] == pytest.approx(160.0)
    assert metrics['average_hops'] == pytest.approx(2.0)
    assert metrics['average_end_to_end_delay_s'] == pytest.approx(0.2)
    assert metrics['total_hops_delivered'] == 4
    assert metrics['total_end_to_end_delay_s'] == pytest.approx(0.4)


def test_metric_zero_denominators_and_no_delivery():
    network, traffic, radio, router, history = _known_answer_components()
    traffic.generated_packets.clear()
    traffic.delivered_packets.clear()
    traffic.dropped_packets.clear()
    metrics = calculate_simulation_metrics(
        network,
        traffic,
        radio,
        0.0,
        router,
        history,
    )
    assert metrics['pdr_percent'] is None
    assert metrics['average_hops'] is None
    assert metrics['average_end_to_end_delay_s'] is None
    assert metrics['throughput_bps'] is None
    assert metrics['goodput_bps'] is None

    metrics_ten = calculate_simulation_metrics(
        network,
        traffic,
        radio,
        10.0,
        router,
        history,
    )
    assert metrics_ten['throughput_bps'] == 0.0
    assert metrics_ten['goodput_bps'] == 0.0


def test_payload_defaults_validates_and_can_be_smaller_than_packet():
    base = SimulationConfig.from_json('configs/default.json')
    legacy_data = base.to_dict()
    legacy_data.pop('payload_size_bytes')
    legacy = SimulationConfig.from_dict(legacy_data)
    assert legacy.payload_size_bytes == legacy.packet_size_bytes

    smaller = replace(base, payload_size_bytes=100)
    simulation = Simulation(smaller, current_range_m=300.0, quiet=True)
    simulation.run_for(11.0)
    assert simulation.traffic_gen.generated_packets
    assert {
        packet.payload_size_bytes
        for packet in simulation.traffic_gen.generated_packets
    } == {100}
    metrics = simulation.get_metrics()
    assert metrics['goodput_bps'] < metrics['throughput_bps']

    with pytest.raises(ValueError):
        replace(base, payload_size_bytes=129)
    with pytest.raises(ValueError):
        replace(base, payload_size_bytes=-1)


def test_lifetime_known_answers_partial_and_ceil():
    deaths = [
        {'node_id': f's{index}', 'death_time_s': time}
        for index, time in enumerate([2.0, 4.0, 6.0, 8.0])
    ]
    full = calculate_lifetime_milestones(4, deaths)
    assert full['fnd_s'] == 2.0
    assert full['hnd_s'] == 4.0
    assert full['lnd_s'] == 8.0

    partial = calculate_lifetime_milestones(4, deaths[:2])
    assert partial['fnd_s'] == 2.0
    assert partial['hnd_s'] == 4.0
    assert partial['lnd_s'] is None
    assert partial['lnd_status'] == 'not_observed'

    odd = calculate_lifetime_milestones(5, deaths[:3])
    assert odd['hnd_dead_sensor_count'] == 3
    assert odd['hnd_s'] == 6.0


def test_lifetime_accepts_zero_and_simultaneous_deaths():
    result = calculate_lifetime_milestones(
        4,
        [
            {'node_id': 'a', 'death_time_s': 0.0},
            {'node_id': 'b', 'death_time_s': 0.0},
        ],
    )
    assert result['fnd_s'] == 0.0
    assert result['hnd_s'] == 0.0
    assert result['lnd_s'] is None


def test_positive_energy_is_not_physical_death_or_emhr_threshold_death():
    sensor = Sensor('s', 0.0, 0.0, 5.0, energy_j=0.5)
    assert sensor.has_enough_energy(1.0) is False
    assert sensor.can_forward(1.0) is False
    assert sensor.is_alive is True
    assert sensor.death_time_s is None
    sensor.consume_energy(0.1)
    assert sensor.death_time_s is None


def test_failed_rx_transaction_can_kill_sender_at_event_time():
    radio = RadioModel()
    tx_cost = radio.compute_tx_energy(128 * 8, 50.0)
    rx_cost = radio.compute_rx_energy(128 * 8)
    sender = Sensor('sender', 0.0, 0.0, 5.0, energy_j=tx_cost)
    receiver = Sensor('receiver', 50.0, 0.0, 5.0, energy_j=rx_cost / 2)
    result = radio.attempt_transmission(
        sender,
        receiver,
        128,
        50.0,
        sim_time_s=7.0,
        packet_id='failed-rx',
    )
    assert result['success'] is False
    assert result['tx_energy_j'] == pytest.approx(tx_cost)
    assert sender.is_alive is False
    assert sender.death_time_s == 7.0
    assert radio.death_events == [
        {
            'node_id': 'sender',
            'death_time_s': 7.0,
            'energy_before_j': tx_cost,
            'energy_after_j': 0.0,
            'cause': 'tx',
            'event_seq': 0,
        }
    ]


def _controlled_network() -> Network:
    config = SimulationConfig.from_json('configs/default.json')
    network = Network(config, communication_range_m=250.0)
    network.sensors.clear()
    network.sinks.clear()
    network.graph = nx.Graph()
    relay = Sensor('relay', 1.0, 0.0, 5.0)
    left = Sensor('left', 2.0, 1.0, 5.0)
    right = Sensor('right', 2.0, -1.0, 5.0)
    sink = Sink('sink_00', 0.0, 0.0)
    network.sensors = {'relay': relay, 'left': left, 'right': right}
    network.sinks = {'sink_00': sink}
    for sensor in network.sensors.values():
        network.graph.add_node(
            sensor.node_id,
            node_type='sensor',
            x=sensor.x,
            y=sensor.y,
        )
    network.graph.add_node('sink_00', node_type='sink', x=0.0, y=0.0)
    network.graph.add_edges_from(
        [('sink_00', 'relay'), ('relay', 'left'), ('relay', 'right')]
    )
    return network


def test_functional_death_is_event_timed_after_relay_death():
    network = _controlled_network()
    simulation = Simulation(network, enable_traffic=False)

    def kill_relay():
        yield simulation.env.timeout(2.0)
        relay = network.sensors['relay']
        simulation.radio._debit_sensor(
            relay,
            relay.energy_j,
            float(simulation.env.now),
            'controlled_test',
        )

    simulation.env.process(kill_relay())
    simulation.run_for(3.0)
    below = [
        row
        for row in simulation.reachability_history
        if row['state'] == 'below_threshold'
    ]
    assert below[0]['time_s'] == 2.0
    assert below[0]['reachable_sensors'] == 0
    assert below[0]['alive_sensors'] == 2


def test_functional_death_at_zero_and_all_dead_ratio_is_none():
    network = _controlled_network()
    network.graph.remove_edges_from(list(network.graph.edges()))
    simulation = Simulation(network, enable_traffic=False)
    assert simulation.reachability_history[0]['time_s'] == 0.0
    assert simulation.reachability_history[0]['state'] == 'below_threshold'

    for sensor in network.sensors.values():
        simulation.radio._debit_sensor(
            sensor,
            sensor.energy_j,
            float(simulation.env.now),
            'controlled_test',
        )
    assert simulation.reachability_history[-1]['state'] == 'all_dead'
    assert simulation.reachability_history[-1]['reachability_ratio'] is None


def _metrics_without_packets(simulation: Simulation, duration_s: float):
    traffic = SimpleNamespace(generated_packets=[])
    return calculate_simulation_metrics(
        simulation.network,
        traffic,
        simulation.radio,
        duration_s,
        simulation.router,
        simulation.reachability_history,
    )


def test_one_sensor_death_sets_all_lifetime_milestones_and_network_lifetime():
    config = replace(
        SimulationConfig.from_json('configs/default.json'),
        num_sensors=1,
        num_sinks=1,
    )
    network = Network(config, communication_range_m=250.0)
    sensor = Sensor('sensor_0', 100.0, 0.0, 5.0)
    sink = Sink('sink_00', 0.0, 0.0)
    network.sensors = {'sensor_0': sensor}
    network.sinks = {'sink_00': sink}
    network.graph = nx.Graph()
    network.graph.add_node('sensor_0', node_type='sensor', x=100.0, y=0.0)
    network.graph.add_node('sink_00', node_type='sink', x=0.0, y=0.0)
    network.graph.add_edge('sensor_0', 'sink_00', distance_m=100.0, weight=100.0)
    simulation = Simulation(network, enable_traffic=False, routing_algorithm='MHR')

    def die_at_two():
        yield simulation.env.timeout(2.0)
        simulation.radio._debit_sensor(sensor, sensor.energy_j, 2.0, 'tx')

    simulation.env.process(die_at_two())
    simulation.run_for(3.0)
    metrics = _metrics_without_packets(simulation, 3.0)
    assert metrics['fnd_s'] == 2.0
    assert metrics['hnd_s'] == 2.0
    assert metrics['lnd_s'] == 2.0
    assert metrics['network_lifetime_s'] == 2.0
    assert metrics['network_lifetime_status'] == 'observed'
    assert metrics['current_reachability_ratio'] is None


def test_network_lifetime_known_answers_for_relay_initial_failure_and_survival():
    relay_network = _controlled_network()
    relay_simulation = Simulation(relay_network, enable_traffic=False)
    relay = relay_network.sensors['relay']

    def relay_dies_at_two():
        yield relay_simulation.env.timeout(2.0)
        relay_simulation.radio._debit_sensor(relay, relay.energy_j, 2.0, 'tx')

    relay_simulation.env.process(relay_dies_at_two())
    relay_simulation.run_for(3.0)
    relay_metrics = _metrics_without_packets(relay_simulation, 3.0)
    assert relay_metrics['network_lifetime_s'] == 2.0

    initial_network = _controlled_network()
    initial_network.graph.remove_edges_from(list(initial_network.graph.edges()))
    initial_simulation = Simulation(initial_network, enable_traffic=False)
    initial_metrics = _metrics_without_packets(initial_simulation, 3.0)
    assert initial_metrics['network_lifetime_s'] == 0.0

    alive_simulation = Simulation(_controlled_network(), enable_traffic=False)
    alive_simulation.run_for(3.0)
    alive_metrics = _metrics_without_packets(alive_simulation, 3.0)
    assert alive_metrics['network_lifetime_s'] is None
    assert alive_metrics['network_lifetime_status'] == 'not_observed'


def test_positive_battery_can_be_physically_reachable_but_energy_infeasible():
    config = replace(
        SimulationConfig.from_json('configs/default.json'),
        num_sensors=1,
        num_sinks=1,
        initial_energy_j=1e-6,
    )
    network = Network(config, communication_range_m=250.0)
    sensor = Sensor('sensor_0', 100.0, 0.0, 1e-6)
    sink = Sink('sink_00', 0.0, 0.0)
    network.sensors = {'sensor_0': sensor}
    network.sinks = {'sink_00': sink}
    network.graph = nx.Graph()
    network.graph.add_node('sensor_0', node_type='sensor', x=100.0, y=0.0)
    network.graph.add_node('sink_00', node_type='sink', x=0.0, y=0.0)
    network.graph.add_edge('sensor_0', 'sink_00', distance_m=100.0, weight=100.0)
    simulation = Simulation(network, routing_algorithm='MHR', quiet=True)
    simulation.run_for(31.0)
    metrics = simulation.get_metrics()
    assert metrics['generated_packets'] == 3
    assert metrics['dropped_packets'] == 3
    assert metrics['drop_reasons'] == {'energy_depletion': 3}
    assert sensor.energy_j == 1e-6
    assert sensor.is_alive is True
    assert simulation.radio.death_events == []
    assert metrics['current_reachable_sensors'] == 1
    assert metrics['current_routing_eligible_sensors'] == 1
    assert metrics['current_energy_feasible_sensors'] == 0


@pytest.mark.parametrize('algorithm', ['MHR', 'EMHR'])
@pytest.mark.parametrize(
    ('initial_energy_j', 'expected_energy_feasible'),
    [(0.0001, 0), (0.001, 1)],
)
def test_feasibility_uses_geometry_when_edge_distance_is_missing(
    tmp_path: Path,
    algorithm: str,
    initial_energy_j: float,
    expected_energy_feasible: int,
):
    config = replace(
        SimulationConfig.from_json('configs/default.json'),
        num_sensors=1,
        num_sinks=1,
        initial_energy_j=initial_energy_j,
    )
    network = Network(config, communication_range_m=250.0)
    sensor = Sensor('sensor_0', 100.0, 0.0, initial_energy_j)
    sink = Sink('sink_00', 0.0, 0.0)
    network.sensors = {'sensor_0': sensor}
    network.sinks = {'sink_00': sink}
    network.graph = nx.Graph()
    network.graph.add_node('sensor_0', node_type='sensor', x=100.0, y=0.0)
    network.graph.add_node('sink_00', node_type='sink', x=0.0, y=0.0)
    network.graph.add_edge('sensor_0', 'sink_00')
    network.communication_range_m = 250.0

    simulation = Simulation(
        network,
        routing_algorithm=algorithm,
        quiet=True,
        seed=42,
    )
    simulation.run_for(1.0)
    battery_before = sensor.energy_j
    edge_data_before = dict(network.graph['sensor_0']['sink_00'])

    expected_tx_cost = simulation.radio.compute_tx_energy(128 * 8, 100.0)
    assert expected_tx_cost == pytest.approx(0.00018432)
    metrics = simulation.get_metrics()
    assert metrics['current_reachable_sensors'] == 1
    assert metrics['current_routing_eligible_sensors'] == 1
    assert metrics['current_energy_feasible_sensors'] == expected_energy_feasible
    assert sensor.energy_j == battery_before
    assert dict(network.graph['sensor_0']['sink_00']) == edge_data_before == {}

    run_dir = tmp_path / f'{algorithm}_{initial_energy_j}'
    simulation.export_results(run_dir)
    assert sensor.energy_j == battery_before
    assert dict(network.graph['sensor_0']['sink_00']) == edge_data_before == {}
    assert validate_run(run_dir)['passed'] is True


def test_emhr_alive_relay_below_threshold_is_not_a_physical_death():
    network = _controlled_network()
    network.sensors['relay'].energy_j = 0.5
    simulation = Simulation(network, enable_traffic=False, routing_algorithm='EMHR')
    metrics = _metrics_without_packets(simulation, 1.0)
    assert metrics['alive_sensors'] == 3
    assert metrics['dead_sensors'] == 0
    assert metrics['current_reachable_sensors'] == 3
    assert metrics['current_routing_eligible_sensors'] == 1
    assert network.sensors['relay'].is_alive is True
    assert metrics['fnd_s'] is None


def test_simpy_stop_boundary_and_repeated_run_for():
    config = SimulationConfig.from_json('configs/default.json')
    simulation = Simulation(config, current_range_m=300.0, quiet=True)
    simulation.run_for(10.0)
    assert simulation.env.now == 10.0
    assert len(simulation.traffic_gen.generated_packets) == 0
    simulation.run_for(0.001)
    assert simulation.env.now == pytest.approx(10.001)
    assert len(simulation.traffic_gen.generated_packets) == 450


def test_export_and_get_metrics_are_idempotent(tmp_path: Path):
    network = _controlled_network()
    simulation = Simulation(network, routing_algorithm='MHR', quiet=True)
    simulation.run_for(11.0)
    before = (
        [sensor.energy_j for sensor in network.sensors.values()],
        [(packet.packet_id, packet.status) for packet in simulation.traffic_gen.generated_packets],
        list(simulation.radio.death_events),
        simulation.router.route_change_count,
    )
    first_metrics = simulation.get_metrics()
    second_metrics = simulation.get_metrics()
    simulation.export_results(tmp_path / 'first')
    simulation.export_results(tmp_path / 'second')
    after = (
        [sensor.energy_j for sensor in network.sensors.values()],
        [(packet.packet_id, packet.status) for packet in simulation.traffic_gen.generated_packets],
        list(simulation.radio.death_events),
        simulation.router.route_change_count,
    )
    assert first_metrics == second_metrics
    assert before == after


def test_simpy_traffic_radio_export_and_independent_validation(tmp_path: Path):
    config = SimulationConfig.from_json('configs/default.json')
    simulation = Simulation(
        config,
        current_range_m=300.0,
        routing_algorithm='EMHR',
        quiet=True,
        seed=42,
    )
    simulation.run_for(21.0)
    run_dir = tmp_path / 'integration'
    simulation.export_results(run_dir)
    report = validate_run(run_dir)
    assert report['passed'] is True


def test_validator_detects_intentional_corruption(tmp_path: Path):
    config = SimulationConfig.from_json('configs/default.json')
    simulation = Simulation(
        config,
        current_range_m=300.0,
        routing_algorithm='MHR',
        quiet=True,
    )
    simulation.run_for(11.0)
    original = tmp_path / 'original'
    corrupted = tmp_path / 'corrupted'
    simulation.export_results(original)
    shutil.copytree(original, corrupted)

    metrics_path = corrupted / 'metrics.json'
    metrics = json.loads(metrics_path.read_text(encoding='utf-8'))
    metrics['delivered_packets'] += 1
    metrics_path.write_text(
        json.dumps(metrics, indent=2, allow_nan=False) + '\n',
        encoding='utf-8',
    )
    report = validate_run(corrupted)
    assert report['passed'] is False
    failed_names = {
        check['metric'] for check in report['checks'] if not check['passed']
    }
    assert 'delivered_packets' in failed_names
    completed = subprocess.run(
        [
            sys.executable,
            'scripts/validate_metrics.py',
            str(corrupted),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert 'Result: FAIL' in completed.stdout


def _mutate_csv(path: Path, mutation) -> None:
    with path.open('r', newline='', encoding='utf-8') as file_handle:
        reader = csv.DictReader(file_handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    mutation(rows)
    with path.open('w', newline='', encoding='utf-8') as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_timeseries_and_route_tampering_fail(tmp_path: Path):
    config = replace(
        SimulationConfig.from_json('configs/default.json'),
        num_sensors=4,
        num_sinks=1,
    )
    network = Network(config, communication_range_m=250.0)
    simulation = Simulation(network, routing_algorithm='MHR', quiet=True, seed=42)
    simulation.run_for(21.0)
    original = tmp_path / 'orig_run'
    simulation.export_results(original)

    # 0. Original passes
    assert validate_run(original)['passed'] is True

    # 1. Alter snapshot energy to 999999 J -> FAIL
    corrupt_energy = tmp_path / 'corrupt_energy'
    shutil.copytree(original, corrupt_energy)
    _mutate_csv(
        corrupt_energy / 'timeseries.csv',
        lambda rows: rows[1].__setitem__('total_energy_j', '999999.0'),
    )
    rep = validate_run(corrupt_energy)
    assert rep['passed'] is False
    failed_checks = {c['metric'] for c in rep['checks'] if not c['passed']}
    assert 'timeseries_integrity' in failed_checks

    # 2. Alter generated and dropped packet counters in snapshot (conserved but contradicts log) -> FAIL
    corrupt_packets = tmp_path / 'corrupt_packets'
    shutil.copytree(original, corrupt_packets)
    _mutate_csv(
        corrupt_packets / 'timeseries.csv',
        lambda rows: (
            rows[1].__setitem__('generated_packets', str(int(rows[1]['generated_packets']) + 1)),
            rows[1].__setitem__('dropped_packets', str(int(rows[1]['dropped_packets']) + 1)),
        ),
    )
    rep = validate_run(corrupt_packets)
    assert rep['passed'] is False
    failed_checks = {c['metric'] for c in rep['checks'] if not c['passed']}
    assert 'timeseries_integrity' in failed_checks

    # 3. Alter delivered_bytes at snapshot -> FAIL
    corrupt_bytes = tmp_path / 'corrupt_bytes'
    shutil.copytree(original, corrupt_bytes)
    _mutate_csv(
        corrupt_bytes / 'timeseries.csv',
        lambda rows: rows[1].__setitem__('delivered_bytes', '999999'),
    )
    rep = validate_run(corrupt_bytes)
    assert rep['passed'] is False
    failed_checks = {c['metric'] for c in rep['checks'] if not c['passed']}
    assert 'timeseries_integrity' in failed_checks

    # 4. Alter route_change_count to 999999 in metrics.json -> FAIL
    corrupt_route = tmp_path / 'corrupt_route'
    shutil.copytree(original, corrupt_route)
    m_path = corrupt_route / 'metrics.json'
    m_data = json.loads(m_path.read_text(encoding='utf-8'))
    m_data['route_change_count'] = 999999
    m_path.write_text(json.dumps(m_data, indent=2) + '\n', encoding='utf-8')
    rep = validate_run(corrupt_route)
    assert rep['passed'] is False
    failed_checks = {c['metric'] for c in rep['checks'] if not c['passed']}
    assert 'route_change_count' in failed_checks


def test_lifetime_real_traffic_milestones(tmp_path: Path):
    base = SimulationConfig.from_json('configs/default.json')
    config = replace(
        base,
        num_sensors=4,
        num_sinks=1,
        packet_size_bytes=128,
        payload_size_bytes=128,
        packet_interval_s=10.0,
    )
    network = Network(config, communication_range_m=100.0)
    tx_cost = 0.0000768
    sink = Sink('sink_00', 0.0, 0.0)
    network.sensors = {
        'S1': Sensor('S1', 50.0, 0.0, 1 * tx_cost),
        'S2': Sensor('S2', 0.0, 50.0, 2 * tx_cost),
        'S3': Sensor('S3', -50.0, 0.0, 3 * tx_cost),
        'S4': Sensor('S4', 0.0, -50.0, 4 * tx_cost),
    }
    network.sinks = {'sink_00': sink}
    network.graph = nx.Graph()
    network.graph.add_node('sink_00', node_type='sink', x=0.0, y=0.0)
    for s in network.sensors.values():
        network.graph.add_node(s.node_id, node_type='sensor', x=s.x, y=s.y)
        network.graph.add_edge(s.node_id, 'sink_00', distance_m=50.0, weight=50.0)

    simulation = Simulation(network, routing_algorithm='MHR', quiet=True, seed=42)
    simulation.run_for(41.0)
    run_dir = tmp_path / 'lifetime_real'
    simulation.export_results(run_dir)

    metrics = simulation.get_metrics()
    assert metrics['fnd_s'] == pytest.approx(10.004096, rel=1e-4)
    assert metrics['hnd_s'] == pytest.approx(20.004096, rel=1e-4)
    assert metrics['lnd_s'] == pytest.approx(40.004096, rel=1e-4)
    assert metrics['generated_packets'] == 10
    assert metrics['delivered_packets'] == 10
    assert metrics['dropped_packets'] == 0
    assert metrics['pending_packets'] == 0
    assert metrics['delivered_bits_at_fnd'] == 4096
    assert metrics['delivered_bits_at_hnd'] == 7168
    assert metrics['delivered_bits_at_lnd'] == 10240

    validation = validate_run(run_dir)
    assert validation['passed'] is True


def _export_failed_recompute_run(run_dir: Path) -> tuple[Simulation, Path]:
    base = SimulationConfig.from_json('configs/default.json')
    config = replace(
        base,
        num_sensors=2,
        num_sinks=1,
        packet_size_bytes=128,
        payload_size_bytes=128,
        packet_interval_s=10.0,
    )
    tx_cost = 0.0000768
    network = Network(config, communication_range_m=60.0)
    source = Sensor('S1', 0.0, 0.0, 5.0)
    relay = Sensor('S2', 50.0, 0.0, tx_cost)
    sink = Sink('sink_00', 100.0, 0.0)
    network.sensors = {'S1': source, 'S2': relay}
    network.sinks = {'sink_00': sink}
    network.graph = nx.Graph()
    for sensor in network.sensors.values():
        network.graph.add_node(
            sensor.node_id,
            node_type='sensor',
            x=sensor.x,
            y=sensor.y,
        )
    network.graph.add_node('sink_00', node_type='sink', x=100.0, y=0.0)
    network.graph.add_edge('S1', 'S2', distance_m=50.0, weight=50.0)
    network.graph.add_edge('S2', 'sink_00', distance_m=50.0, weight=50.0)

    simulation = Simulation(network, routing_algorithm='MHR', quiet=True, seed=42)
    assert simulation.traffic_gen is not None
    packet = Packet(
        'S1_manual_1',
        'S1',
        created_at=0.0,
        size_bytes=128,
        payload_size_bytes=128,
        sequence_number=1,
        created_event_seq=simulation.next_event_seq(),
    )
    route = simulation.router.get_route('S1', is_source=True)
    assert route == ['S1', 'S2', 'sink_00']
    simulation.router.record_route_event(
        time_s=0.0,
        source_id='S1',
        packet_id=packet.packet_id,
        current_node_id='S1',
        old_route='',
        new_route=route,
        reason='initial_route',
        outcome='initial_route',
    )
    packet.assign_route(route)
    simulation.traffic_gen.generated_packets.append(packet)
    simulation.traffic_gen.queues['S1'].append(packet)
    source.generated_packets += 1

    death_tx = simulation.radio.attempt_transmission(
        relay,
        sink,
        packet_size_bytes=128,
        distance_m=50.0,
        sim_time_s=0.0,
        packet_id='setup_relay_death',
    )
    assert death_tx['success'] is True
    assert relay.is_alive is False

    simulation.run_for(1.0)
    simulation.export_results(run_dir)
    return simulation, run_dir


def test_failed_recompute_is_logged_counted_and_validated(tmp_path: Path):
    simulation, run_dir = _export_failed_recompute_run(tmp_path / 'failed_recompute')

    assert simulation.router.route_recompute_count == 1
    assert simulation.router.route_change_count == 0
    assert simulation.router.route_failure_count == 1
    failed_events = [
        event
        for event in simulation.router.route_events
        if event['outcome'] == 'failed'
    ]
    assert len(failed_events) == 1
    assert failed_events[0]['reason'] == 'route_invalid'
    assert validate_run(run_dir)['passed'] is True


def test_packet_event_sequence_controls_same_timestamp_replay(tmp_path: Path):
    _, original = _export_failed_recompute_run(tmp_path / 'event_order_original')
    corrupted = tmp_path / 'event_order_corrupted'
    shutil.copytree(original, corrupted)

    with (corrupted / 'packets.csv').open(
        'r', newline='', encoding='utf-8'
    ) as file_handle:
        packet_reader = csv.DictReader(file_handle)
        packet_fields = list(packet_reader.fieldnames or [])
        packet_rows = list(packet_reader)
    with (corrupted / 'timeseries.csv').open(
        'r', newline='', encoding='utf-8'
    ) as file_handle:
        snapshot_reader = csv.DictReader(file_handle)
        snapshot_fields = list(snapshot_reader.fieldnames or [])
        snapshot_rows = list(snapshot_reader)

    packet_seq = packet_rows[0]['created_event_seq']
    snapshot_seq = snapshot_rows[0]['event_seq']
    packet_rows[0]['created_event_seq'] = snapshot_seq
    snapshot_rows[0]['event_seq'] = packet_seq

    with (corrupted / 'packets.csv').open(
        'w', newline='', encoding='utf-8'
    ) as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=packet_fields)
        writer.writeheader()
        writer.writerows(packet_rows)
    with (corrupted / 'timeseries.csv').open(
        'w', newline='', encoding='utf-8'
    ) as file_handle:
        writer = csv.DictWriter(file_handle, fieldnames=snapshot_fields)
        writer.writeheader()
        writer.writerows(snapshot_rows)

    report = validate_run(corrupted)
    assert report['passed'] is False
    failed_checks = {c['metric'] for c in report['checks'] if not c['passed']}
    assert 'timeseries_integrity' in failed_checks
