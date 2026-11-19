from argparse import ArgumentParser
from dataclasses import asdict, replace
import json
from math import isclose
from pathlib import Path
from wsn_sim.config import DEFAULT_CONFIG_PATH, DetectorConfig, SimulationConfig
from wsn_sim.detection import ForwardingDetector
from wsn_sim.metrics import packet_event_metrics, security_metrics
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, create_run_manifest, save_detector_outputs, save_json, save_simulation

def _network(plan, positions, edges, sinks, **changes):
    config = replace(plan, config_profile='TEST_ONLY', num_sensors=len(positions), num_sinks=len(sinks), attacker_ids=(), attacker_ratio=0, p_drop=0, channel_loss_probability=0, **changes)
    network = Network(config, sensors={node: Sensor(node, *xy, config.initial_energy_j) for node, xy in positions.items()}, sinks={node: Sink(node, *xy) for node, xy in sinks.items()})
    network.graph.remove_edges_from(list(network.graph.edges))
    for left, right in edges:
        network.graph.add_edge(left, right, distance_m=network.distance(left, right))
    return network

def _save_case(simulation, directory, root, checks, context=None):
    summary = simulation.summary()
    checks['packet_conservation'] = summary['performance']['conservation_ok']
    checks['energy_conservation'] = summary['performance']['energy_conservation_ok']
    checks['control_overhead_not_modeled'] = summary['performance']['control_packets'] is None
    result = {'checks': checks, 'checks_passed': all(checks.values()), 'context': context or {}, 'summary': summary}
    save_simulation(simulation, directory, root, {'case_check.json': result, 'raw_packet_events.json': {'events': simulation.traffic_gen.events}, 'raw_energy_events.json': {'events': simulation.energy_events}})
    raw = json.loads((directory / 'raw_packet_events.json').read_text(encoding='utf-8'))['events']
    replayed = packet_event_metrics(raw, summary['time_s'] - simulation.started_at)
    if any((replayed[key] != summary['performance'][key] for key in replayed if key != 'na_reasons')) or any((summary['performance']['na_reasons'].get(key) != reason for key, reason in replayed['na_reasons'].items())):
        raise RuntimeError('saved raw packet events do not reproduce aggregate metrics')
    result['saved_raw_event_replay_passed'] = True
    save_json(result, directory / 'case_check.json')
    return result

def recovery_checks(plan, root, directory):
    cases = {}
    for name in ('diamond', 'switch_sink', 'no_route', 'node_dead', 'relay_energy', 'link_unavailable'):
        detector = DetectorConfig(0.2, 0.5, 0.1, 1, 0.7, 1, 1, 2.5)
        positions = {'s': (0, 0), 'h': (10, 0), 'holder': (20, 0), 'a': (30, 0), 'b': (30, 20), 'probe': (30, -10)}
        edges = [('s', 'h'), ('h', 'holder'), ('holder', 'a'), ('a', 'k0'), ('probe', 'a')]
        if name != 'no_route':
            edges.extend([('holder', 'b'), ('b', 'k1' if name == 'switch_sink' else 'k0')])
        sinks = {f'k{index}': (40 + index * 20, 0) for index in range(7)}
        network = _network(plan, positions, edges, sinks, routing_algorithm='S_EMHR', detector=detector, bandwidth_bps=1024)
        attacked = name in {'diamond', 'switch_sink', 'no_route'}
        if attacked:
            config = replace(network.config, attacker_ids=('a',), p_drop=1)
            network.config = config
        simulation = Simulation(network.config, network=network)
        nodes_before = set(network.graph)
        packet = simulation.traffic_gen.generate_packet('s')
        if attacked:
            simulation.traffic_gen.generate_packet('probe')
        else:

            def change(case=name):
                yield simulation.env.timeout(0.5)
                if case == 'link_unavailable':
                    simulation.set_link_state('holder', 'a', available=False)
                else:
                    network.sensors['a'].consume_energy(5 if case == 'node_dead' else 4.5, simulation.env.now)
            simulation.env.process(change())
        simulation.run_for(4.1)
        expected_path = ['s', 'h', 'holder'] if name == 'no_route' else ['s', 'h', 'holder', 'b', 'k1' if name == 'switch_sink' else 'k0']
        decision = simulation.traffic_gen.reroute_decisions[0]
        expected_reason = 'isolation' if attacked else name
        checks = {'actual_path': packet.actual_path == expected_path, 'status': packet.status.value == ('NO_ROUTE' if name == 'no_route' else 'DELIVERED'), 'no_loop': len(packet.actual_path) == len(set(packet.actual_path)), 'physical_nodes_preserved': set(network.graph) == nodes_before and 'a' in network.graph, 'cause': decision['reason'] == expected_reason and decision['trigger_nodes'] == ([] if name == 'link_unavailable' else ['a']), 'no_fake_death': network.sensors['a'].is_alive == (name != 'node_dead')}
        cases[name] = _save_case(simulation, directory / name, root, checks, {'scope': 'TEST_ONLY known graph with real probe selective forwarding for isolation cases', 'source_packet_id': packet.packet_id, 'actual_path': packet.actual_path, 'seven_sink_fallback': name == 'switch_sink', 'reroute_decisions': simulation.traffic_gen.reroute_decisions})
    config = DetectorConfig(0.5, 5, 1, 1, 0.7, 1, 1, 6)
    detector = ForwardingDetector(config, ['relay'])
    detector.observe_received('relay', 'first', 'source', 0)
    detector.advance(5)
    detector.observe_received('relay', 'old', 'source', 10)
    detector.observe_forwarded('relay', 'old', 10.1)
    detector.advance(15)
    before_fresh = detector.summary()
    detector.observe_received('relay', 'fresh', 'source', 15.1)
    detector.observe_forwarded('relay', 'fresh', 15.2)
    detector.advance(20)
    save_detector_outputs(detector, directory / 'probation')
    cases['probation'] = {'checks_passed': before_fresh['relays']['relay']['probation'] and (not detector.states['relay'].probation) and (detector.states['relay'].trust == 0.875), 'before_fresh': before_fresh, 'after_fresh': detector.summary()}
    save_json(cases['probation'], directory / 'probation/case_check.json')
    return cases

def metric_checks(plan, root, directory):
    cases = {}
    positions = {'source': (0, 0), 'relay': (10, 0)}
    edges = [('source', 'relay'), ('relay', 'sink')]
    for name, duration in (('known_delivery', 3), ('in_flight', 0.5)):
        network = _network(plan, positions, edges, {'sink': (20, 0)}, routing_algorithm='MHR', wire_size_bytes=160, bandwidth_bps=1280)
        simulation = Simulation(network.config, network=network)
        simulation.traffic_gen.generate_packet('source')
        simulation.run_for(duration)
        metrics = simulation.summary()['performance']
        if name == 'known_delivery':
            energy = 1280 * (2 * (5e-08 + 1e-11 * 10 ** 2) + 5e-08)
            checks = {'generated_delivered': metrics['generated'] == metrics['delivered'] == 1, 'wire_payload_rates': isclose(metrics['throughput_bps'], 1280 / 3) and isclose(metrics['goodput_bps'], 1024 / 3), 'actual_hops_latency': metrics['mean_actual_hops'] == 2 and metrics['mean_latency_s'] == 2, 'energy_by_hand': isclose(metrics['energy_from_events_j'], energy, abs_tol=1e-12), 'energy_per_bit': isclose(metrics['energy_per_payload_bit_j'], energy / 1024, abs_tol=1e-12)}
        else:
            checks = {'packet_not_lost': metrics['generated'] == metrics['pending_in_flight'] == 1 and metrics['dropped'] == 0, 'no_false_latency_or_energy_ratio': metrics['mean_latency_s'] is None and metrics['energy_per_payload_bit_j'] is None}
        cases[name] = _save_case(simulation, directory / name, root, checks, {'expected_energy_j': energy} if name == 'known_delivery' else {})
    network = _network(plan, {'a': (0, 0), 'b': (0, 10)}, [('a', 'sink'), ('b', 'sink')], {'sink': (10, 0)}, routing_algorithm='MHR')
    simulation = Simulation(network.config, network=network)
    simulation.traffic_gen.generate_packet('a')

    def deaths():
        yield simulation.env.timeout(2)
        network.sensors['a'].consume_energy(5, simulation.env.now)
        yield simulation.env.timeout(2)
        network.sensors['b'].consume_energy(5, simulation.env.now)
    simulation.env.process(deaths())
    simulation.run_for(6)
    summary = simulation.summary()
    cases['lifetime'] = _save_case(simulation, directory / 'lifetime', root, {'actual_death_times': [summary['lifetime'][name]['time_s'] for name in ('FND', 'HND', 'LND')] == [2, 2, 4], 'payload_at_death': summary['lifetime']['FND']['received_payload_bits'] == 1024, 'LND_stop': summary['stop_reason'] == 'LND' and summary['time_s'] == 4, 'no_alive_separate': summary['reachability']['status'] == 'no_alive_sensors' and summary['lifetime']['functional_network_death']['time_s'] is None})
    network = _network(plan, {'s': (0, 0), 'r': (10, 0), 't': (0, 10)}, [('s', 'r'), ('t', 'r'), ('r', 'sink')], {'sink': (20, 0)})
    simulation = Simulation(network.config, network=network)

    def disconnect():
        yield simulation.env.timeout(0.5)
        simulation.set_link_state('r', 'sink', available=False)
        yield simulation.env.timeout(0.5)
        simulation.set_link_state('r', 'sink', available=True)
    simulation.env.process(disconnect())
    simulation.run_for(1.1)
    summary = simulation.summary()
    cases['functional_link'] = _save_case(simulation, directory / 'functional_link', root, {'functional_time': summary['lifetime']['functional_network_death']['time_s'] == 0.5, 'no_battery_death': summary['lifetime']['FND']['time_s'] is None, 'restoration_preserves_first_crossing': summary['reachability']['physical_reachable_alive'] == 3})
    config = DetectorConfig(0.5, 5, 1, 1, 0.8, 1, 1, 10)
    detector = ForwardingDetector(config, list('abcdefgh'))
    for node in 'abef':
        detector.observe_received(node, node, 'source', 0)
    detector.observe_forwarded('f', 'f', 0.1)
    result = security_metrics(list('abcdefgh'), list('abcd'), detector, 5)
    checks = {'hand_matrix': [result[key] for key in ('TP', 'FP', 'TN', 'FN')] == [2, 1, 3, 2], 'ratios': result['tpr'] == 0.5 and result['fpr'] == 0.25 and isclose(result['precision'], 2 / 3) and isclose(result['f1'], 4 / 7), 'unobserved_attackers_retained': result['FN'] == 2 and result['coverage'] == 0.5}
    cases['security_hand'] = {'checks': checks, 'checks_passed': all(checks.values()), 'evaluation': result}
    save_detector_outputs(detector, directory / 'security_hand')
    save_json({'input_rx': list('abef'), 'input_tx': ['f'], 'ground_truth_evaluator_only': list('abcd'), 'parameters': asdict(config), **cases['security_hand']}, directory / 'security_hand/case_check.json')
    return cases

def run_checks(root: Path, output_root: Path, stage: int) -> dict:
    directory = create_run_directory(output_root, f'stage{stage}_checks')
    plan = SimulationConfig.from_json(root / 'configs/plan.json')
    cases = recovery_checks(plan, root, directory) if stage == 5 else metric_checks(plan, root, directory)
    report = {'stage': stage, 'scope': 'TEST_ONLY deterministic acceptance checks, not evaluation seeds', 'cases': cases, 'checks_passed': all((case['checks_passed'] for case in cases.values())), 'output_directory': str(directory), 'evaluation_runs': 0}
    save_json(report, directory / 'checks.json')
    manifest_path = directory / 'run_manifest.json'
    manifest = create_run_manifest(plan, [*sorted(directory.rglob('*.*')), manifest_path], root)
    manifest.update({'stage': stage, 'evaluation_runs': 0})
    save_json(manifest, manifest_path)
    print(json.dumps({'stage': stage, 'checks_passed': report['checks_passed'], 'cases': {name: case['checks_passed'] for name, case in cases.items()}, 'output_directory': str(directory), 'evaluation_runs': 0}, indent=2))
    return report

def main(stage: int) -> None:
    root = DEFAULT_CONFIG_PATH.parents[1]
    parser = ArgumentParser()
    parser.add_argument('--output', type=Path, default=root / 'results/runs')
    args = parser.parse_args()
    if not run_checks(root, args.output.resolve(), stage)['checks_passed']:
        raise SystemExit(1)
