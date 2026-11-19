from argparse import ArgumentParser
from dataclasses import replace
import json
from pathlib import Path
from wsn_sim.config import DEFAULT_CONFIG_PATH, DetectorConfig, SimulationConfig
from wsn_sim.detection import benign_calibration_profile
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, save_simulation

def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = ArgumentParser()
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument('--detector-config', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=120)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--channel-loss', type=float)
    for option in ('beta-trust', 'window-size-s', 'forwarding-timeout-s', 'trust-threshold', 'initial-trust', 'isolation-duration-s'):
        parser.add_argument(f'--{option}', type=float)
    for option in ('min-observations', 'consecutive-bad-windows'):
        parser.add_argument(f'--{option}', type=int)
    parser.add_argument('--output', type=Path, default=root / 'results/runs')
    args = parser.parse_args()
    detector = DetectorConfig(**json.loads(args.detector_config.read_text(encoding='utf-8')))
    detector_changes = {name: getattr(args, name) for name in ('beta_trust', 'window_size_s', 'forwarding_timeout_s', 'trust_threshold', 'initial_trust', 'isolation_duration_s', 'min_observations', 'consecutive_bad_windows') if getattr(args, name) is not None}
    if detector_changes:
        detector = replace(detector, **detector_changes, calibration_status='TEST_ONLY')
    scenario_changes = {name: value for name, value in {'seed': args.seed, 'channel_loss_probability': args.channel_loss}.items() if value is not None}
    config = replace(SimulationConfig.from_json(args.config), detector=detector, attacker_ratio=0, attacker_ids=(), p_drop=0, routing_algorithm='EMHR', **scenario_changes)
    simulation = Simulation(config)
    simulation.run_for(args.duration)
    profile = benign_calibration_profile(simulation.detector.windows)
    counters = simulation.detector.summary()
    profile['detector_parameters'] = counters['parameters']
    profile['observation_counters'] = counters
    directory = save_simulation(simulation, create_run_directory(args.output, 'benign_calibration'), root, {'calibration_profile.json': profile})
    print(json.dumps(profile, indent=2, allow_nan=False))
    print(f'output_directory={directory}')
if __name__ == '__main__':
    main()
