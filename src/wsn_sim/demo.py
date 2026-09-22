"""End-to-end demonstration for the initial WSN architecture."""

from __future__ import annotations

from pathlib import Path

from wsn_sim.config import SimulationConfig
from wsn_sim.metrics import topology_summary_frame
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.storage import create_run_manifest, save_json, save_topology_summary
from wsn_sim.visualization import save_topology_plot


def run_demo(project_root: str | Path) -> dict[str, object]:
    """Generate three topologies, smoke-test SimPy, and save all outputs.

    Args:
        project_root: Repository root containing ``configs/default.json``.

    Returns:
        A mapping containing summaries, simulated time, and generated paths.
    """
    root = Path(project_root).resolve()
    config = SimulationConfig.from_json(root / "configs" / "default.json")
    network = Network(config)

    summaries: list[dict[str, int | float]] = []
    figure_paths: list[Path] = []
    initial_coordinates = network.coordinates()

    for radius in config.communication_ranges_m:
        network.build_graph(radius)
        if network.coordinates() != initial_coordinates:
            raise RuntimeError("node coordinates changed while rebuilding topology")
        summaries.append(network.topology_summary())
        figure_paths.append(
            save_topology_plot(
                network,
                root / "results" / "figures" / f"topology_R{radius:g}.png",
            )
        )

    frame = topology_summary_frame(summaries)
    csv_path = save_topology_summary(
        frame, root / "results" / "csv" / "topology_summary.csv"
    )

    simulation = Simulation(network)
    simpy_time_s = simulation.run_for(config.packet_interval_s)

    manifest_path = root / "results" / "run_manifest.json"
    generated_paths = [csv_path, *figure_paths, manifest_path]
    relative_paths = [path.relative_to(root) for path in generated_paths]
    manifest = create_run_manifest(config, relative_paths, root)
    save_json(manifest, manifest_path)

    print(f"sensors={len(network.sensors)}")
    print(f"sinks={len(network.sinks)}")
    for summary in summaries:
        print(
            f"R={summary['communication_range_m']:g} "
            f"nodes={summary['nodes']} edges={summary['edges']} "
            f"routable_sensors={summary['routable_sensors']} "
            f"isolated_sensors={summary['isolated_sensors']}"
        )
    print(f"simpy_time_s={simpy_time_s:g}")
    print(f"csv={csv_path.relative_to(root)}")
    print(f"manifest={manifest_path.relative_to(root)}")

    return {
        "summaries": summaries,
        "simpy_time_s": simpy_time_s,
        "generated_files": generated_paths,
    }


def main() -> None:
    """Run the demo from the repository containing this installed package."""
    project_root = Path(__file__).resolve().parents[2]
    run_demo(project_root)


if __name__ == "__main__":
    main()
