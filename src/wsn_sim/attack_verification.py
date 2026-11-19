from argparse import ArgumentParser
from dataclasses import replace
import json
from math import fsum, isclose, sqrt
from pathlib import Path
from wsn_sim.attacks import SelectiveForwarding
from wsn_sim.config import DEFAULT_CONFIG_PATH, SimulationConfig, require_integer, require_number, require_probability
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.randomness import event_occurs, randomness_metadata
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, create_run_manifest, save_json, save_simulation

def binomial_count_interval(samples: int, probability: float, alpha: float=1e-06) -> tuple[int, int]:
    require_integer('samples', samples)
    require_probability('probability', probability)
    require_number('alpha', alpha)
    if alpha >= 1:
        raise ValueError('alpha must be strictly less than one')
    if probability in (0, 1):
        count = 0 if probability == 0 else samples
        return (count, count)
    mode = min(samples, int((samples + 1) * probability))
    weights = [0.0] * (samples + 1)
    weights[mode] = 1.0
    for count in range(mode, 0, -1):
        weights[count - 1] = weights[count] * count / (samples - count + 1) * (1 - probability) / probability
    for count in range(mode, samples):
        weights[count + 1] = weights[count] * (samples - count) / (count + 1) * probability / (1 - probability)
    total = fsum(weights)
    lower_target, upper_target = (total * alpha / 2, total * (1 - alpha / 2))
    cumulative = 0.0
    lower = None
    for count, weight in enumerate(weights):
        cumulative += weight
        if lower is None and cumulative >= lower_target:
            lower = count
        if cumulative >= upper_target:
            return (lower, count)
    return (lower, samples)

def sample_drop_rates(config: SimulationConfig, samples: int) -> list[dict]:
    require_integer('samples', samples)
    rows = []

    def record(mechanism: str, probability: float, count: int) -> None:
        lower, upper = binomial_count_interval(samples, probability)
        rows.append({'mechanism': mechanism, 'probability': probability, 'samples': samples, 'observed_drops': count, 'observed_ratio': count / samples, 'expected_count': samples * probability, 'binomial_std': sqrt(samples * probability * (1 - probability)), 'alpha': 1e-06, 'lower_count': lower, 'upper_count': upper, 'within_binomial_interval': lower <= count <= upper})
    for probability in (0.0, 0.25, 0.5, 0.75, 1.0):
        attack = SelectiveForwarding(replace(config, config_profile='TEST_ONLY', attacker_ids=('relay',), p_drop=probability), ['relay', 'source'])
        count = sum((attack.drops('relay', f'sampler_{index}', 'source') for index in range(samples)))
        record('selective_forwarding', probability, count)
    for probability in (0.0, 0.01, 0.05, 1.0):
        count = sum((event_occurs(config.stream_seeds['channel_loss'], probability, f'sampler_{index}', 'source', 'relay', 0) for index in range(samples)))
        record('natural_link_loss', probability, count)
    return rows

def trace_attack_case(plan: SimulationConfig, p_drop: float, channel_loss: float) -> Simulation:
    config = replace(plan, config_profile='TEST_ONLY', num_sensors=3, num_sinks=1, communication_range_m=15, routing_algorithm='EMHR', detector=None, attacker_selection='random', attacker_ratio=0, attacker_ids=('attacker',), p_drop=p_drop, channel_loss_probability=channel_loss)
    network = Network(config, sensors={node: Sensor(node, x, 0, config.initial_energy_j) for node, x in (('source', 0), ('attacker', 10), ('downstream', 20))}, sinks={'sink': Sink('sink', 30, 0)})
    simulation = Simulation(config, network=network)
    simulation.traffic_gen.generate_packet('source')
    simulation.traffic_gen.generate_packet('attacker')
    simulation.run_for(0.1)
    return simulation

def run_attack_checks(project_root: str | Path, samples: int=20000, output_root: str | Path | None=None) -> dict:
    require_integer('samples', samples, 1000)
    root = Path(project_root).resolve()
    plan = SimulationConfig.from_json(root / 'configs/plan.json')
    directory = create_run_directory(root / 'results/runs' if output_root is None else output_root, 'stage2_attacks')
    network = Network(plan)
    selections = {mode: SelectiveForwarding(replace(plan, attacker_ratio=0.05, attacker_selection=mode), network.sensors, network=network).to_dict() for mode in ('random', 'near_sink')}
    trace_cases = {}
    tx_j = plan.transmission_size_bytes * 8 * (5e-08 + 1e-11 * 10 ** 2)
    rx_j = plan.transmission_size_bytes * 8 * 5e-08
    expected = {'benign': {'source': tx_j, 'attacker': 2 * tx_j + rx_j, 'downstream': 2 * tx_j + 2 * rx_j}, 'selective_drop': {'source': tx_j, 'attacker': tx_j + rx_j, 'downstream': tx_j + rx_j}, 'natural_loss': {'source': tx_j, 'attacker': tx_j, 'downstream': 0.0}}
    packet_counts = {'benign': (2, 2, 0, 0), 'selective_drop': (2, 1, 1, 0), 'natural_loss': (2, 0, 2, 0)}
    drop_reasons = {'benign': {}, 'selective_drop': {'selective_forwarding': 1}, 'natural_loss': {'natural_link_loss': 2}}
    for name, p_drop, channel_loss in (('benign', 0, 0), ('selective_drop', 1, 0), ('natural_loss', 1, 1)):
        simulation = trace_attack_case(plan, p_drop, channel_loss)
        observed = {node: sensor.initial_energy_j - sensor.energy_j for node, sensor in simulation.network.sensors.items()}
        trace_cases[name] = {'summary': simulation.summary(), 'events': simulation.traffic_gen.events, 'expected_energy_j': expected[name], 'observed_energy_j': observed, 'energy_matches': all((isclose(observed[node], value, abs_tol=1e-12) for node, value in expected[name].items()))}
        performance = trace_cases[name]['summary']['performance']
        trace_cases[name]['packet_counts_match'] = tuple((performance[key] for key in ('generated', 'delivered', 'dropped', 'pending_in_flight'))) == packet_counts[name]
        trace_cases[name]['drop_reasons_match'] = performance['drop_reasons'] == drop_reasons[name]
        save_simulation(simulation, directory / name, root)
    rates = sample_drop_rates(plan, samples)
    report = {'stage': 2, 'scope': 'TEST_ONLY trace and Bernoulli sampler validation, not evaluation seeds', 'plan_configuration': plan.to_dict(), 'stream_seeds': plan.stream_seeds, 'randomness': randomness_metadata(), 'selection_modes': selections, 'trace_cases': trace_cases, 'drop_rate_checks': rates, 'binomial_method': 'central_count_quantiles_by_mode_centered_pmf_recurrence_float64', 'checks_passed': selections['random']['attacker_count'] == selections['near_sink']['attacker_count'] == 23 and all((row['energy_matches'] and row['packet_counts_match'] and row['drop_reasons_match'] and row['summary']['performance']['conservation_ok'] for row in trace_cases.values())) and all((row['within_binomial_interval'] for row in rates)), 'output_directory': str(directory)}
    save_json(report, directory / 'attack_checks.json')
    manifest_path = directory / 'run_manifest.json'
    manifest = create_run_manifest(plan, [*sorted(directory.rglob('*.*')), manifest_path], root)
    manifest['stage'] = 2
    manifest['sampler_samples_per_probability'] = samples
    save_json(manifest, manifest_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return report

def main() -> None:
    parser = ArgumentParser()
    parser.add_argument('--samples', type=int, default=20000)
    parser.add_argument('--output', type=Path, default=DEFAULT_CONFIG_PATH.parents[1] / 'results/runs')
    args = parser.parse_args()
    if args.samples < 1000:
        parser.error('samples must be at least 1000 distinct event keys')
    report = run_attack_checks(DEFAULT_CONFIG_PATH.parents[1], args.samples, args.output)
    if not report['checks_passed']:
        raise SystemExit(1)
if __name__ == '__main__':
    main()
