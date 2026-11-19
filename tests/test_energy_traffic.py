from dataclasses import replace
from math import sqrt
import pytest
from wsn_sim.attacks import SelectiveForwarding
from wsn_sim.energy import RadioModel
from wsn_sim.models import PacketStatus, Sensor, Sink
from wsn_sim.simulation import Simulation

@pytest.mark.parametrize('distance', [10, 100])
def test_radio_uses_bits_and_computed_crossover(distance):
    radio = RadioModel()
    expected_amplifier = 1e-11 * distance ** 2 if distance == 10 else 1.3e-15 * distance ** 4
    assert radio.d0 == pytest.approx(sqrt(1e-11 / 1.3e-15))
    assert radio.compute_tx_energy(1024, distance) == pytest.approx(1024 * (5e-08 + expected_amplifier))
    assert radio.compute_rx_energy(1024) == pytest.approx(1024 * 5e-08)

def test_insufficient_tx_drains_only_sender_and_records_exact_death():
    radio = RadioModel()
    sender = Sensor('s', 0, 0, 5, energy_j=1e-08)
    receiver = Sensor('a', 10, 0, 5)
    assert not radio.process_transmission(sender, receiver, 128, 10, time_s=3)
    assert sender.energy_j == 0
    assert sender.died_at == 3
    assert receiver.energy_j == 5
    sender.consume_energy(1, time_s=4)
    assert sender.died_at == 3

def test_insufficient_rx_is_not_a_successful_hop():
    radio = RadioModel()
    sender = Sensor('s', 0, 0, 5)
    receiver = Sensor('a', 10, 0, 5, energy_j=1e-08)
    assert not radio.process_transmission(sender, receiver, 128, 10, time_s=4)
    assert sender.energy_j == pytest.approx(5 - radio.compute_tx_energy(1024, 10))
    assert receiver.energy_j == 0
    assert receiver.died_at == 4

def test_exact_tx_budget_can_transmit_to_unlimited_sink():
    radio = RadioModel()
    required = radio.compute_tx_energy(1024, 10)
    sender = Sensor('s', 0, 0, 5, energy_j=required)
    sink = Sink('k', 10, 0)
    assert radio.process_transmission(sender, sink, 128, 10, time_s=2)
    assert sender.died_at == 2
    assert not hasattr(sink, 'energy_j')

def test_isolated_sensor_still_generates_and_packet_partition_is_complete(network_factory):
    net = network_factory({'s': (0, 0), 'z': (1000, 0)}, [('s', 'k')])
    simulation = Simulation(net.config, network=net)
    simulation.run_for(20.1)
    traffic = simulation.traffic_gen
    isolated = [packet for packet in traffic.generated_packets if packet.source_id == 'z']
    assert len(isolated) == 2
    assert all((packet.status is PacketStatus.NO_ROUTE and packet.drop_reason == 'unreachable' for packet in isolated))
    metrics = simulation.summary()['performance']
    assert (metrics['generated'], metrics['delivered'], metrics['dropped'], metrics['pending_in_flight']) == (4, 2, 2, 0)
    assert metrics['pdr'] == 0.5
    assert metrics['conservation_ok']

def test_dead_sensor_stops_generating_and_death_is_not_rounded_to_next_round(network_factory):
    net = network_factory({'s': (0, 0), 'z': (1000, 0)}, [('s', 'k')])
    net.sensors['s'].consume_energy(5 - 1e-08, 0)
    simulation = Simulation(net.config, network=net)
    simulation.run_for(25)
    assert net.sensors['s'].generated_packets == 1
    assert net.sensors['z'].generated_packets == 2
    assert net.sensors['s'].died_at == 10
    assert simulation.summary()['lifetime']['FND']['time_s'] == 10

@pytest.mark.parametrize('probability', [0, 1])
def test_attacker_receives_before_drop_and_sends_own_packets(network_factory, probability):
    net = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')], sinks={'k': (20, 0)}, attacker_ids=('a',), p_drop=probability)
    simulation = Simulation(net.config, network=net)
    simulation.run_for(10.1)
    traffic = simulation.traffic_gen
    source_packet = next((packet for packet in traffic.generated_packets if packet.source_id == 's'))
    own_packet = next((packet for packet in traffic.generated_packets if packet.source_id == 'a'))
    assert own_packet.status is PacketStatus.DELIVERED
    radio = simulation.radio
    tx = radio.compute_tx_energy(1024, 10)
    rx = radio.compute_rx_energy(1024)
    assert net.sensors['a'].energy_j == pytest.approx(5 - rx - tx * (2 - probability))
    events = [row['event'] for row in traffic.events if row['packet_id'] == source_packet.packet_id]
    if probability:
        assert source_packet.drop_reason == 'selective_forwarding'
        assert source_packet.actual_path == ['s', 'a']
        assert events == ['created', 'tx', 'rx', 'dropped']
        assert source_packet.delivered_at is None
    else:
        assert source_packet.status is PacketStatus.DELIVERED
        assert source_packet.actual_path == ['s', 'a', 'k']
        assert source_packet.latency_s == pytest.approx(2 * 1024 / 250000)

def test_natural_loss_consumes_tx_without_receiver_energy_or_attack_decision(network_factory):
    net = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')], sinks={'k': (20, 0)}, attacker_ids=('a',), p_drop=1, channel_loss_probability=1)
    simulation = Simulation(net.config, network=net)
    simulation.run_for(10.1)
    assert all((packet.drop_reason == 'natural_link_loss' for packet in simulation.traffic_gen.dropped_packets))
    assert net.sensors['a'].received_packets == 0
    assert net.sensors['a'].energy_j == pytest.approx(5 - simulation.radio.compute_tx_energy(1024, 10))
    assert all((packet.actual_hop_count == 0 for packet in simulation.traffic_gen.generated_packets))

@pytest.mark.parametrize(('ratio', 'expected'), [(0, 0), (0.02, 9), (0.05, 23), (0.1, 45)])
def test_seeded_attacker_selection_uses_half_up_and_only_sensors(config, ratio, expected):
    ids = [f'sensor_{index:03d}' for index in range(450)]
    cfg = replace(config, attacker_ratio=ratio)
    first = SelectiveForwarding(cfg, ids)
    second = SelectiveForwarding(cfg, reversed(ids))
    assert len(first.attacker_ids) == expected
    assert first.attacker_ids == second.attacker_ids
    assert first.actual_ratio == expected / 450

def test_reject_explicit_sink_attacker(config):
    with pytest.raises(ValueError, match='sensor IDs'):
        SelectiveForwarding(replace(config, attacker_ids=('sink_00',)), ['s'])

def test_round_limit_preserves_in_flight_packets(network_factory):
    net = network_factory({'s': (0, 0)}, [('s', 'k')], max_rounds=2)
    simulation = Simulation(net.config, network=net)
    assert simulation.run_for(100) == 20
    summary = simulation.summary()
    assert summary['rounds'] == 2
    assert summary['stop_reason'] == 'max_rounds'
    assert summary['performance']['generated'] == 2
    assert summary['performance']['delivered'] == 1
    assert summary['performance']['pending_in_flight'] == 1
    assert summary['performance']['conservation_ok']
    assert simulation.run_for(10) == 20

def test_last_node_death_stops_before_round_limit(network_factory):
    net = network_factory({'s': (0, 0)}, [('s', 'k')])
    net.sensors['s'].consume_energy(5 - 1e-08, 0)
    simulation = Simulation(net.config, network=net)
    assert simulation.run_for(100) == 10
    summary = simulation.summary()
    assert summary['stop_reason'] == 'LND'
    assert all((summary['lifetime'][name]['time_s'] == 10 for name in ('FND', 'HND', 'LND')))
    assert summary['performance']['dropped'] == 1
