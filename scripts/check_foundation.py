from argparse import ArgumentParser
from dataclasses import replace
import json
from math import isclose
from pathlib import Path
import pandas as pd
from wsn_sim.config import SimulationConfig
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, create_run_manifest, save_csv, save_json

def check_known_graph(plan: SimulationConfig) -> dict:
    config = replace(plan, config_profile='TEST_ONLY', num_sensors=3, num_sinks=1, communication_range_m=15, routing_algorithm='EMHR', detector=None, attacker_ratio=0, attacker_ids=(), channel_loss_probability=0)
    network = Network(config, sensors={node: Sensor(node, x, y, config.initial_energy_j) for node, x, y in (('source', 0, 0), ('relay', 10, 0), ('isolated', 1000, 1000))}, sinks={'sink': Sink('sink', 20, 0)})
    simulation = Simulation(config, network=network)
    routes = {'MHR': simulation.router.get_mhr_route('source'), 'EMHR': simulation.router.get_emhr_route('source')}
    simulation.run_for(10.1)
    tx_j = 128 * 8 * (5e-08 + 1e-11 * 10 ** 2)
    rx_j = 128 * 8 * 5e-08
    expected_energy_j = {'source': tx_j, 'relay': 2 * tx_j + rx_j, 'isolated': 0.0}
    observed_energy_j = {node: sensor.initial_energy_j - sensor.energy_j for node, sensor in network.sensors.items()}
    metrics = simulation.summary()['performance']
    return {'configuration': config.to_dict(), 'routes': routes, 'expected_energy_j': expected_energy_j, 'observed_energy_j': observed_energy_j, 'sink_received_unique': network.sinks['sink'].received_packet_count, 'packets': [{'packet_id': packet.packet_id, 'source_id': packet.source_id, 'status': packet.status.value, 'reason': packet.drop_reason, 'created_at': packet.created_at, 'delivered_at': packet.delivered_at, 'planned_route': packet.planned_route, 'actual_path': packet.actual_path, 'planned_hops': packet.planned_hop_count, 'actual_hops': packet.actual_hop_count, 'payload_size_bytes': packet.size_bytes, 'wire_size_bytes': packet.wire_size_bytes} for packet in simulation.traffic_gen.generated_packets], 'summary': simulation.summary(), 'events': simulation.traffic_gen.events, 'matches_expected': (metrics['generated'], metrics['delivered'], metrics['dropped'], metrics['pending_in_flight']) == (3, 2, 1, 0) and metrics['conservation_ok'] and all((isclose(observed_energy_j[node], value, abs_tol=1e-12) for node, value in expected_energy_j.items())) and (network.sinks['sink'].received_packet_count == 2)}

def check_reachability(config: SimulationConfig, seeds: list[int]) -> dict:
    rows = []
    coordinates_stable = True
    for seed in seeds:
        network = Network(replace(config, seed=seed))
        coordinates = network.coordinates()
        for radius in config.communication_ranges_m:
            network.build_graph(radius)
            summary = network.topology_summary()
            reachable = summary['routable_sensors']
            coordinates_stable = coordinates_stable and network.coordinates() == coordinates
            rows.append({**summary, 'reachable_ratio': reachable / summary['sensors'], 'fully_reachable': reachable == summary['sensors']})
    by_radius = []
    for radius in config.communication_ranges_m:
        samples = [row for row in rows if row['communication_range_m'] == radius]
        failed = sum((not row['fully_reachable'] for row in samples))
        by_radius.append({'communication_range_m': radius, 'topology_count': len(samples), 'not_fully_reachable_count': failed, 'not_fully_reachable_rate': failed / len(samples), 'mean_reachable_ratio': sum((row['reachable_ratio'] for row in samples)) / len(samples), 'minimum_reachable_ratio': min((row['reachable_ratio'] for row in samples))})
    return {'scope': 'stage_1_foundation_topology_audit', 'seeds': seeds, 'criterion': 'every_sensor_has_a_physical_path_to_a_sink', 'criterion_is_research_acceptance': False, 'coordinates_stable': coordinates_stable, 'rows': rows, 'by_radius': by_radius, 'configured_initial_range_m': config.communication_range_m, 'selected_main_range_m': None, 'main_range_status': 'NEEDS_PILOT_DECISION'}

def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = ArgumentParser()
    parser.add_argument('--seeds', type=int, nargs='+', default=[42])
    parser.add_argument('--output', type=Path, default=root / 'results/runs')
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds) or any((seed < 0 for seed in args.seeds)):
        parser.error('seeds must be unique non-negative integers')
    plan = SimulationConfig.from_json(root / 'configs/plan.json')
    default = SimulationConfig.from_json(root / 'configs/default.json')
    legacy = SimulationConfig.from_json(root / 'configs/legacy/energy_3j.json')
    contract = {'config_profile': 'PLAN', 'initial_energy_j': 5, 'energy_threshold_ratio': 0.2, 'num_sensors': 450, 'num_sinks': 7, 'area_width_m': 3000, 'area_height_m': 3000, 'packet_size_bytes': 128, 'packet_interval_s': 10, 'max_rounds': 10000, 'communication_ranges_m': (250, 300, 350)}
    mismatches = {name: getattr(plan, name) for name, value in contract.items() if getattr(plan, name) != value}
    known_graph = check_known_graph(plan)
    reachability = check_reachability(plan, args.seeds)
    directory = create_run_directory(args.output, 'stage1_foundation')
    report = {'stage': 1, 'plan_configuration': plan.to_dict(), 'plan_energy_configuration': plan.energy_configuration, 'plan_contract_mismatches': mismatches, 'default_alias_matches_plan': default == plan, 'legacy': {'config_profile': legacy.config_profile, 'energy_configuration': legacy.energy_configuration, 'performance_run': False, 'performance_compared_with_plan': False}, 'known_graph': known_graph, 'reachability': reachability, 'checks_passed': not mismatches and default == plan and known_graph['matches_expected'] and reachability['coordinates_stable'], 'output_directory': str(directory)}
    report_path = save_json(report, directory / 'foundation_check.json')
    csv_path = save_csv(pd.DataFrame(reachability['rows']), directory / 'reachability.csv')
    manifest_path = directory / 'run_manifest.json'
    manifest = create_run_manifest(plan, [report_path, csv_path, manifest_path], root)
    manifest['stage'] = 1
    manifest['topology_audit_seeds'] = args.seeds
    save_json(manifest, manifest_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    if not report['checks_passed']:
        raise SystemExit(1)
if __name__ == '__main__':
    main()
