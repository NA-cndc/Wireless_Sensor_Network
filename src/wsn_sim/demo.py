from __future__ import annotations
from pathlib import Path
from wsn_sim.config import SimulationConfig
from wsn_sim.metrics import topology_summary_frame
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_directory, create_run_manifest, save_json, save_topology_summary
from wsn_sim.visualization import save_topology_plot

def run_demo(project_root: str | Path, output_root: str | Path | None=None) -> dict[str, object]:
    root = Path(project_root).resolve()
    output = create_run_directory(root / 'results/runs' if output_root is None else output_root, 'topology')
    config = SimulationConfig.from_json(root / 'configs' / 'plan.json')
    network = Network(config)
    summaries: list[dict[str, int | float]] = []
    figure_paths: list[Path] = []
    initial_coordinates = network.coordinates()
    for radius in config.communication_ranges_m:
        network.build_graph(radius)
        if network.coordinates() != initial_coordinates:
            raise RuntimeError('node coordinates changed while rebuilding topology')
        summaries.append(network.topology_summary())
        figure_paths.append(save_topology_plot(network, output / 'figures' / f'topology_R{radius:g}.png'))
    frame = topology_summary_frame(summaries)
    csv_path = save_topology_summary(frame, output / 'topology_summary.csv')
    simulation = Simulation(config, network=network)
    simpy_time_s = simulation.run_for(config.packet_interval_s)
    manifest_path = output / 'run_manifest.json'
    generated_paths = [csv_path, *figure_paths, manifest_path]
    manifest = create_run_manifest(config, generated_paths, root)
    save_json(manifest, manifest_path)
    print(f'sensors={len(network.sensors)}')
    print(f'sinks={len(network.sinks)}')
    for summary in summaries:
        print(f"R={summary['communication_range_m']:g} nodes={summary['nodes']} edges={summary['edges']} routable_sensors={summary['routable_sensors']} isolated_sensors={summary['isolated_sensors']}")
    print(f'simpy_time_s={simpy_time_s:g}')
    print(f'csv={csv_path}')
    print(f'manifest={manifest_path}')
    print(f'output_directory={output}')
    return {'summaries': summaries, 'simpy_time_s': simpy_time_s, 'generated_files': generated_paths}

def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    run_demo(project_root)
if __name__ == '__main__':
    main()
