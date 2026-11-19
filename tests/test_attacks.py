from dataclasses import replace
import json
from math import comb
import os
from pathlib import Path
import random
import subprocess
import sys
import pytest
from wsn_sim.attack_verification import binomial_count_interval, trace_attack_case
from wsn_sim.attacks import SelectiveForwarding
from wsn_sim.config import SimulationConfig
from wsn_sim.models import PacketStatus
from wsn_sim.randomness import event_occurs, randomness_metadata
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_manifest

def test_near_sink_uses_nearest_of_all_sinks_and_id_ties(network_factory):
    network = network_factory({'a': (10, 0), 'b': (20, 0), 'c': (90, 0), 'd': (50, 0), 'e': (99, 0)}, sinks={'left': (0, 0), 'right': (100, 0)}, attacker_ratio=0.4, attacker_selection='near_sink')
    attack = SelectiveForwarding(network.config, network.sensors, network=network)
    assert attack.attacker_ids == {'a', 'e'}
    assert attack.nearest_sink_distances_m == {'a': 10, 'e': 1}
    assert attack.to_dict()['selection_rule'] == 'minimum_euclidean_distance_to_any_sink_then_sensor_id'

@pytest.mark.parametrize(('ratio', 'expected'), [(0, 0), (0.02, 9), (0.05, 23), (0.1, 45)])
@pytest.mark.parametrize('mode', ['random', 'near_sink'])
def test_selection_modes_have_identical_half_up_counts(config, network, ratio, expected, mode):
    attack = SelectiveForwarding(replace(config, attacker_ratio=ratio, attacker_selection=mode), network.sensors, network=network)
    report = attack.to_dict()
    assert len(attack.attacker_ids) == expected
    assert not attack.attacker_ids.intersection(network.sinks)
    assert report['attacker_ids'] == sorted(attack.attacker_ids)
    assert report['attacker_count'] == report['requested_count_from_ratio'] == expected
    assert report['requested_ratio'] == ratio
    assert report['actual_ratio'] == expected / 450
    assert report['selection'] == mode
    assert report['rounding'] == 'half_up'

@pytest.mark.parametrize('mode', ['random', 'near_sink'])
def test_selection_is_independent_of_routing_graph_energy_and_insertion(network_factory, mode):
    network = network_factory({'a': (5, 0), 'b': (10, 0), 'c': (15, 0), 'd': (20, 0)}, attacker_ratio=0.5, attacker_selection=mode)
    first = SelectiveForwarding(network.config, network.sensors, network=network)
    network.graph.remove_edges_from(list(network.graph.edges))
    network.sensors['d'].consume_energy(5, 0)
    cfg = replace(network.config, routing_algorithm='MHR', p_drop=0.75, channel_loss_probability=0.05)
    second = SelectiveForwarding(cfg, reversed(network.sensors), network=network)
    assert first.attacker_ids == second.attacker_ids

def test_explicit_ids_override_ratio_and_near_sink_without_geometry(config):
    cfg = replace(config, attacker_ratio=1, attacker_selection='near_sink', attacker_ids=('a',))
    attack = SelectiveForwarding(cfg, ['a', 'b', 'c'])
    assert attack.attacker_ids == {'a'}
    assert attack.to_dict()['selection'] == 'explicit'
    assert attack.to_dict()['requested_count_from_ratio'] == 3
    assert attack.actual_ratio == 1 / 3

@pytest.mark.parametrize('mode', ['random', 'near_sink'])
def test_explicit_empty_set_disables_attack(config, mode):
    attack = SelectiveForwarding(replace(config, attacker_ratio=1, attacker_selection=mode, attacker_ids=(), p_drop=1), ['a', 'b'])
    assert not attack.attacker_ids
    assert not attack.drops('a', 'packet', 'b')
    assert attack.actual_ratio == 0

def test_near_sink_requires_positions_and_rejects_sink_candidates(config, network):
    with pytest.raises(ValueError, match='positions'):
        SelectiveForwarding(replace(config, attacker_selection='near_sink'), ['a', 'b'])
    with pytest.raises(ValueError, match='network sensor IDs'):
        SelectiveForwarding(config, [*network.sensors, *network.sinks], network=network)
    with pytest.raises(ValueError, match='sensor IDs'):
        SelectiveForwarding(replace(config, attacker_ids=(next(iter(network.sinks)),)), network.sensors, network=network)

@pytest.mark.parametrize(('value', 'error'), [('explicit', ValueError), ('near-sink', ValueError), (True, TypeError), ([], TypeError)])
def test_selection_validation_round_trip(config, value, error):
    with pytest.raises(error):
        replace(config, attacker_selection=value)
    cfg = replace(config, attacker_selection='near_sink')
    assert SimulationConfig.from_dict(cfg.to_dict()) == cfg

@pytest.mark.parametrize(('ids', 'error'), [('sensor', TypeError), (['a', 'a'], ValueError), ([''], TypeError), ([1], TypeError)])
def test_candidate_pool_rejects_invalid_ids(config, ids, error):
    with pytest.raises(error):
        SelectiveForwarding(config, ids)

def test_random_selection_does_not_use_global_random_state(config):
    before = random.getstate()
    SelectiveForwarding(replace(config, attacker_ratio=0.5), [f's{index}' for index in range(100)])
    assert random.getstate() == before

@pytest.mark.parametrize('probability', [0, 1])
def test_pdrop_boundaries_only_apply_to_transit(config, probability):
    attack = SelectiveForwarding(replace(config, attacker_ids=('a',), p_drop=probability), ['a', 'b'])
    for index in range(100):
        assert attack.drops('a', f'p{index}', 'b') is bool(probability)
        assert not attack.drops('a', f'own{index}', 'a')
        assert not attack.drops('b', f'honest{index}', 'a')

def test_attack_variates_ignore_draw_order_but_include_attempt_index(config):
    attack = SelectiveForwarding(replace(config, attacker_ids=('a',)), ['a', 'b'])
    ids = [f'packet_{index}' for index in range(100)]
    first = {packet: attack.drops('a', packet, 'b') for packet in ids}
    for index in range(1000):
        event_occurs(config.stream_seeds['channel_loss'], 0.5, f'unrelated_{index}', 'x', 'y', 0)
    second = {packet: attack.drops('a', packet, 'b') for packet in reversed(ids)}
    next_attempt = {packet: attack.drops('a', packet, 'b', attempt_index=1) for packet in ids}
    assert first == second
    assert first != next_attempt
    assert all((first[packet] == event_occurs(attack.decision_seed, 0.5, packet, 'a', 0) for packet in ids))

@pytest.mark.parametrize(('attempt', 'error'), [(-1, ValueError), (True, TypeError), (0.5, TypeError)])
def test_attack_attempt_index_validation(config, attempt, error):
    attack = SelectiveForwarding(replace(config, attacker_ids=('a',)), ['a', 'b'])
    with pytest.raises(error):
        attack.drops('a', 'p', 'b', attempt_index=attempt)

def test_transit_attack_trace_stops_after_rx_and_own_packet_is_delivered(config):
    simulation = trace_attack_case(config, 1, 0)
    traffic = simulation.traffic_gen
    packet = next((packet for packet in traffic.generated_packets if packet.source_id == 'source'))
    own = next((packet for packet in traffic.generated_packets if packet.source_id == 'attacker'))
    events = [row for row in traffic.events if row['packet_id'] == packet.packet_id]
    assert [row['event'] for row in events] == ['created', 'tx', 'rx', 'dropped']
    assert events[-2]['node_id'] == events[-1]['node_id'] == 'attacker'
    assert events[-2]['energy_j'] == pytest.approx(1024 * 5e-08)
    assert events[-1]['energy_j'] == 0
    assert events[-1]['sender_id'] == 'source'
    assert events[-1]['receiver_id'] == 'attacker'
    assert events[-1]['attempt_index'] == 0
    assert packet.drop_reason == 'selective_forwarding'
    assert packet.actual_path == ['source', 'attacker']
    assert own.status is PacketStatus.DELIVERED
    energy = [sensor.energy_j for sensor in simulation.network.sensors.values()]
    count = len(traffic.events)
    traffic._drop(packet, 'natural_link_loss')
    simulation.env.process(traffic._transmit_packet(packet))
    simulation.run_for(0.1)
    assert len(traffic.events) == count
    assert [sensor.energy_j for sensor in simulation.network.sensors.values()] == energy
    assert len(traffic.dropped_packets) == 1
    assert packet.drop_reason == 'selective_forwarding'

def test_natural_loss_never_invokes_attack_or_charges_rx(network_factory, monkeypatch):
    network = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')], attacker_ids=('a',), p_drop=1, channel_loss_probability=1)
    simulation = Simulation(network.config, network=network)

    def unexpected_attack(*args, **kwargs):
        pytest.fail('attack decision happened before a successful RX')
    monkeypatch.setattr(simulation.traffic_gen.attack, 'drops', unexpected_attack)
    packet = simulation.traffic_gen.generate_packet('s')
    simulation.run_for(0.1)
    assert packet.drop_reason == 'natural_link_loss'
    assert packet.actual_hop_count == 0
    assert network.sensors['a'].energy_j == 5
    events = simulation.traffic_gen.events
    assert [row['event'] for row in events] == ['created', 'tx', 'dropped']
    assert events[-1]['sender_id'] == 's'
    assert events[-1]['receiver_id'] == 'a'
    assert events[-1]['energy_j'] == 0

def test_channel_loss_after_relay_tx_is_not_a_selective_drop(network_factory, config):

    def channel_loses(seed, sender, receiver):
        return event_occurs(replace(config, seed=seed).stream_seeds['channel_loss'], 0.5, 's_p1', sender, receiver, 0)
    chosen_seed = next((seed for seed in range(1000) if not channel_loses(seed, 's', 'a') and channel_loses(seed, 'a', 'b')))
    network = network_factory({'s': (0, 0), 'a': (10, 0), 'b': (20, 0)}, [('s', 'a'), ('a', 'b'), ('b', 'k')], sinks={'k': (30, 0)}, seed=chosen_seed, attacker_ids=('a',), p_drop=0, channel_loss_probability=0.5)
    simulation = Simulation(network.config, network=network)
    packet = simulation.traffic_gen.generate_packet('s')
    simulation.run_for(0.1)
    assert packet.drop_reason == 'natural_link_loss'
    assert packet.actual_path == ['s', 'a']
    assert network.sensors['a'].received_packets == 1
    assert network.sensors['a'].forwarded_packets == 1
    assert network.sensors['b'].energy_j == 5
    assert [row['event'] for row in simulation.traffic_gen.events] == ['created', 'tx', 'rx', 'tx', 'dropped']
    assert network.sensors['a'].energy_j == pytest.approx(5 - 1024 * 5e-08 - 1024 * (5e-08 + 1e-11 * 10 ** 2))

@pytest.mark.parametrize('stage', ['TX', 'RX'])
def test_energy_failure_is_neither_natural_nor_attack_and_trace_charges_only_available_energy(network_factory, monkeypatch, stage):
    network = network_factory({'s': (0, 0), 'a': (10, 0)}, [('s', 'a'), ('a', 'k')], attacker_ids=('a',), p_drop=1, routing_algorithm='MHR')
    failing = network.sensors['s' if stage == 'TX' else 'a']
    failing.consume_energy(5 - 1e-08, 0)
    budget = failing.energy_j
    simulation = Simulation(network.config, network=network)

    def unexpected_attack(*args, **kwargs):
        pytest.fail('attack decision happened on failed TX/RX')
    monkeypatch.setattr(simulation.traffic_gen.attack, 'drops', unexpected_attack)
    packet = simulation.traffic_gen.generate_packet('s')
    simulation.run_for(0.1)
    dropped = simulation.traffic_gen.events[-1]
    assert packet.drop_reason == 'energy_depletion'
    assert dropped['energy_stage'] == stage
    assert dropped['energy_j'] == budget
    assert failing.energy_j == 0
    assert packet.actual_hop_count == 0

def test_empirical_integrated_drop_count_and_rx_tx_match_binomial(network_factory):
    samples = 2000
    network = network_factory({'s': (0, 0), 'a': (10, 0), 'b': (20, 0)}, [('s', 'a'), ('a', 'b'), ('b', 'k')], sinks={'k': (30, 0)}, attacker_ids=('a',), p_drop=0.5)
    simulation = Simulation(network.config, network=network)
    for _ in range(samples):
        simulation.traffic_gen.generate_packet('s')
    simulation.run_for(0.1)
    dropped = len(simulation.traffic_gen.dropped_packets)
    delivered = len(simulation.traffic_gen.delivered_packets)
    lower, upper = binomial_count_interval(samples, 0.5)
    assert lower <= dropped <= upper
    assert dropped + delivered == samples
    assert network.sensors['a'].received_packets == samples
    assert network.sensors['a'].forwarded_packets == delivered
    assert all((packet.drop_reason == 'selective_forwarding' for packet in simulation.traffic_gen.dropped_packets))
    tx, rx = (1024 * (5e-08 + 1e-11 * 10 ** 2), 1024 * 5e-08)
    assert network.sensors['a'].energy_j == pytest.approx(5 - samples * rx - delivered * tx)
    assert network.sensors['b'].energy_j == pytest.approx(5 - delivered * (rx + tx))
    assert simulation.summary()['performance']['conservation_ok']

def test_corresponding_attack_and_channel_events_match_when_algorithms_use_different_hops(network_factory):
    runs = []
    for algorithm in ('MHR', 'EMHR'):
        network = network_factory({'s': (0, 0), 'a': (10, 0), 'b': (10, 10), 'c': (20, 10), 'r': (30, 0)}, [('s', 'a'), ('a', 'r'), ('s', 'b'), ('b', 'c'), ('c', 'r'), ('r', 'k')], sinks={'k': (40, 0)}, routing_algorithm=algorithm, attacker_ids=('r',), p_drop=0.5, channel_loss_probability=0.05)
        network.sensors['a'].consume_energy(4.5, 0)
        simulation = Simulation(network.config, network=network)
        for _ in range(100):
            simulation.traffic_gen.generate_packet('s')
        simulation.run_for(0.1)
        received = {row['packet_id'] for row in simulation.traffic_gen.events if row['event'] == 'rx' and row['node_id'] == 'r'}
        packets = {packet.packet_id: packet for packet in simulation.traffic_gen.generated_packets}
        runs.append((received, packets))
    common = runs[0][0] & runs[1][0]
    assert common
    for packet_id in common:
        first, second = (runs[0][1][packet_id], runs[1][1][packet_id])
        assert first.planned_hop_count == 3
        assert second.planned_hop_count == 4
        assert first.status == second.status
        assert first.drop_reason == second.drop_reason

@pytest.mark.parametrize(('samples', 'probability', 'alpha'), [(10, 0.5, 0.05), (20, 0.25, 0.1), (40, 0.75, 0.001)])
def test_binomial_interval_matches_direct_small_distribution(samples, probability, alpha):
    cumulative = []
    total = 0.0
    for count in range(samples + 1):
        total += comb(samples, count) * probability ** count * (1 - probability) ** (samples - count)
        cumulative.append(total)
    expected = tuple((next((count for count, value in enumerate(cumulative) if value >= target)) for target in (alpha / 2, 1 - alpha / 2)))
    assert binomial_count_interval(samples, probability, alpha) == expected

@pytest.mark.parametrize(('probability', 'expected'), [(0, (0, 0)), (1, (20000, 20000))])
def test_binomial_boundary_is_deterministic(probability, expected):
    assert binomial_count_interval(20000, probability) == expected

@pytest.mark.parametrize(('samples', 'probability', 'alpha'), [(0, 0.5, 1e-06), (100, -0.1, 1e-06), (100, 1.1, 1e-06), (100, 0.5, 0), (100, 0.5, 1)])
def test_binomial_validation_rejects_invalid_parameters(samples, probability, alpha):
    with pytest.raises(ValueError):
        binomial_count_interval(samples, probability, alpha)

def test_manifest_declares_six_streams_and_event_key_schema(config, project_root):
    manifest = create_run_manifest(config, [], project_root)
    assert len(set(manifest['stream_seeds'].values())) == 6
    assert manifest['randomness'] == randomness_metadata()
    assert manifest['randomness']['simulated_attempt_index'] == 0
    assert manifest['randomness']['retransmission_modeled'] is False
    assert manifest['randomness']['stream_usage']['traffic'] == 'deterministic_periodic_no_draws'

@pytest.mark.parametrize('mode', ['random', 'near_sink'])
def test_selection_and_results_reproduce_across_python_hash_seeds(project_root, mode):
    code = f"from dataclasses import replace; import json; from wsn_sim import Simulation,SimulationConfig; c=replace(SimulationConfig.from_json('configs/plan.json'),config_profile='TEST_ONLY',num_sensors=24,num_sinks=2,area_width_m=300,area_height_m=300,communication_range_m=80,attacker_ratio=0.25,attacker_selection={mode!r},p_drop=0.5,channel_loss_probability=0.05); s=Simulation(c);s.run_for(21);print(json.dumps({{'summary':s.summary(),'events':s.traffic_gen.events}},sort_keys=True))"
    outputs = []
    for seed in ('1', '8123'):
        result = subprocess.run([sys.executable, '-c', code], cwd=project_root, env=dict(os.environ, PYTHONHASHSEED=seed), check=True, capture_output=True, text=True)
        outputs.append(json.loads(result.stdout))
    assert outputs[0] == outputs[1]

def test_attack_check_script_emits_real_trace_and_binomial_results(project_root, tmp_path):
    result = subprocess.run([sys.executable, 'scripts/check_attacks.py', '--samples', '2000', '--output', str(tmp_path)], cwd=project_root, check=True, capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert report['stage'] == 2
    assert report['checks_passed']
    assert all((row['packet_counts_match'] and row['drop_reasons_match'] for row in report['trace_cases'].values()))
    assert report['selection_modes']['random']['attacker_count'] == report['selection_modes']['near_sink']['attacker_count'] == 23
    assert all((row['samples'] == 2000 and row['within_binomial_interval'] for row in report['drop_rate_checks']))
    assert report['trace_cases']['selective_drop']['summary']['performance']['drop_reasons'] == {'selective_forwarding': 1}
    assert report['trace_cases']['natural_loss']['summary']['performance']['drop_reasons'] == {'natural_link_loss': 2}
    manifest = json.loads((Path(report['output_directory']) / 'run_manifest.json').read_text(encoding='utf-8'))
    assert manifest['sampler_samples_per_probability'] == 2000
    assert all((Path(path).exists() for path in manifest['generated_files']))

@pytest.mark.parametrize('explicit', [False, True])
def test_cli_supports_near_sink_and_explicit_override(project_root, tmp_path, explicit):
    command = [sys.executable, 'main.py', '--duration', '0.1', '--attacker-selection', 'near_sink', '--attacker-ratio', '0.05', '--p-drop', '0.75', '--channel-loss', '0.01', '--output', str(tmp_path)]
    if explicit:
        command.extend(['--attacker-ids', 'sensor_000'])
    result = subprocess.run(command, cwd=project_root, check=True, capture_output=True, text=True)
    summary = json.loads(result.stdout.rsplit('output_directory=', 1)[0])
    assert summary['attack']['selection'] == ('explicit' if explicit else 'near_sink')
    assert summary['attack']['attacker_count'] == (1 if explicit else 23)
