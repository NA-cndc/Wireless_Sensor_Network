from dataclasses import asdict, replace
import json
from pathlib import Path
from wsn_sim.config import DetectorConfig, SimulationConfig
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, save_simulation

def _in_flight_example(official: SimulationConfig, detector: DetectorConfig, root: Path, directory: Path) -> dict:
    config = replace(official, config_profile='TEST_ONLY', num_sensors=6, num_sinks=1, routing_algorithm='S_EMHR', bandwidth_bps=1024, attacker_ids=('attacker',), p_drop=1, detector=replace(detector, window_size_s=1.5, forwarding_timeout_s=0.1))
    positions = {'source': (0, 20), 'bridge': (10, 20), 'holder': (20, 20), 'attacker': (30, 20), 'backup': (30, 30), 'probe': (30, 10)}
    network = Network(config, sensors={node: Sensor(node, *xy, config.initial_energy_j) for node, xy in positions.items()}, sinks={'sink': Sink('sink', 40, 20)})
    network.graph.remove_edges_from(list(network.graph.edges))
    for left, right in (('source', 'bridge'), ('bridge', 'holder'), ('holder', 'attacker'), ('attacker', 'sink'), ('holder', 'backup'), ('backup', 'sink'), ('probe', 'attacker')):
        network.graph.add_edge(left, right, distance_m=network.distance(left, right))
    simulation = Simulation(config, network=network)
    simulation.traffic_gen.generate_packet('probe')
    packet = simulation.traffic_gen.generate_packet('source')
    before = list(packet.planned_route)
    simulation.run_for(4.1)
    result = {'scope': 'TEST_ONLY explicit packet injection on a known graph', 'packet_id': packet.packet_id, 'created_at': packet.created_at, 'delivered_at': packet.delivered_at, 'status': packet.status.value, 'route_before': before, 'actual_path': packet.actual_path, 'reroutes': simulation.traffic_gen.reroutes, 'summary': simulation.summary()}
    save_simulation(simulation, directory, root, {'in_flight_example.json': result})
    return result

def run_verification(project_root: str | Path, output_root: str | Path | None=None) -> dict:
    root = Path(project_root).resolve()
    official = SimulationConfig.from_json(root / 'configs/plan.json')
    detector = DetectorConfig(**json.loads((root / 'configs/detector_test_only.json').read_text(encoding='utf-8')))
    config = replace(official, config_profile='TEST_ONLY', num_sensors=4, num_sinks=2, communication_range_m=90, routing_algorithm='S_EMHR', attacker_ids=('sensor_attacker',), p_drop=1, detector=detector)
    positions = {'sensor_source': (0, 0), 'sensor_attacker': (60, 0), 'sensor_relay': (60, 60), 'sensor_isolated': (1000, 1000)}
    network = Network(config, sensors={node: Sensor(node, *xy, config.initial_energy_j) for node, xy in positions.items()}, sinks={'sink_00': Sink('sink_00', 120, 0), 'sink_01': Sink('sink_01', 120, 60)})
    simulation = Simulation(config, network=network)
    routes = {'MHR': simulation.router.get_mhr_route('sensor_source'), 'EMHR': simulation.router.get_emhr_route('sensor_source'), 'S_EMHR_before': simulation.router.get_semhr_route('sensor_source')}
    simulation.run_for(15)
    routes['S_EMHR_after'] = simulation.router.get_semhr_route('sensor_source', time_s=simulation.env.now)
    simulation.run_for(10)
    traffic = simulation.traffic_gen
    delivered = next((packet for packet in traffic.delivered_packets if packet.source_id == 'sensor_source'))
    attacked = next((packet for packet in traffic.dropped_packets if packet.drop_reason == 'selective_forwarding'))
    directory = create_run_directory(root / 'results/runs' if output_root is None else output_root, 'verification')
    result = {'scope': 'TEST_ONLY demonstration; no official multi-seed experiment', 'official_configuration': official.to_dict(), 'battery': {'initial_energy_j': official.initial_energy_j, 'energy_threshold_j': official.energy_threshold_j}, 'routes': routes, 'unreachable_packets': [{'packet_id': packet.packet_id, 'status': packet.status.value, 'reason': packet.drop_reason} for packet in traffic.dropped_packets if packet.source_id == 'sensor_isolated'], 'delivered_example': {'packet_id': delivered.packet_id, 'status': delivered.status.value, 'created_at': delivered.created_at, 'delivered_at': delivered.delivered_at, 'actual_path': delivered.actual_path, 'latency_s': delivered.latency_s}, 'attack_example': {'packet_id': attacked.packet_id, 'status': attacked.status.value, 'reason': attacked.drop_reason, 'actual_path': attacked.actual_path, 'events': [row for row in traffic.events if row['packet_id'] == attacked.packet_id]}, 'relay_windows': simulation.detector.windows, 'relay_states': {node: asdict(state) for node, state in simulation.detector.states.items()}, 'in_flight_reroute': _in_flight_example(official, detector, root, directory / 'in_flight'), 'summary': simulation.summary(), 'output_directory': str(directory)}
    save_simulation(simulation, directory, root, {'verification.json': result})
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return result
