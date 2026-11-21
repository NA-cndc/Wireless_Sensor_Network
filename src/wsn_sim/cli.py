from argparse import ArgumentParser
from dataclasses import replace
import json
from pathlib import Path
from wsn_sim.calibration import verify_freeze
from wsn_sim.config import DEFAULT_CONFIG_PATH, DetectorConfig, SimulationConfig
from wsn_sim.experiment_plan import validate_calibration_basis
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, save_simulation

def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = ArgumentParser()
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument('--range', type=float, dest='range_m')
    parser.add_argument('--algorithm', choices=('MHR', 'EMHR', 'S_EMHR'))
    parser.add_argument('--duration', type=float)
    parser.add_argument('--rounds', type=int)
    parser.add_argument('--detector-config', type=Path)
    parser.add_argument('--attacker-selection', choices=('random', 'near_sink'))
    parser.add_argument('--attacker-ratio', type=float)
    parser.add_argument('--attacker-ids', nargs='*')
    parser.add_argument('--p-drop', type=float)
    parser.add_argument('--channel-loss', type=float)
    parser.add_argument('--output', type=Path, default=root / 'results/runs')
    args = parser.parse_args()
    config = SimulationConfig.from_json(args.config)
    changes = {name: value for name, value in {'communication_range_m': args.range_m, 'routing_algorithm': args.algorithm, 'max_rounds': args.rounds, 'attacker_selection': args.attacker_selection, 'attacker_ratio': args.attacker_ratio, 'attacker_ids': None if args.attacker_ids is None else tuple(args.attacker_ids), 'p_drop': args.p_drop, 'channel_loss_probability': args.channel_loss}.items() if value is not None}
    calibration_verification = None
    if args.detector_config is not None:
        changes['detector'] = DetectorConfig(**json.loads(args.detector_config.read_text(encoding='utf-8')))
        if changes['detector'].calibration_status == 'CALIBRATED':
            calibration_verification = verify_freeze(args.detector_config.resolve(), root)
    config = replace(config, **changes)
    if calibration_verification is not None and config.topology_model == 'na':
        lock_path = Path(calibration_verification['lock'])
        validate_calibration_basis(config.to_dict(), json.loads(lock_path.read_text(encoding='utf-8')))
    simulation = Simulation(config)
    if args.duration is None:
        summary = simulation.run()
    else:
        simulation.run_for(args.duration)
        summary = simulation.summary()
    extra = {'calibration_verification.json': calibration_verification} if calibration_verification is not None else None
    directory = save_simulation(simulation, create_run_directory(args.output), root, extra)
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    print(f'output_directory={directory}')
if __name__ == '__main__':
    main()
