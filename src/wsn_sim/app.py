"""Streamlit web dashboard for interactive WSN topology exploration and simulation."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st

from wsn_sim.config import SimulationConfig
from wsn_sim.exporters import (
    export_to_cooja,
    export_to_ns3_mobility,
    export_to_omnetpp_ned,
)
from wsn_sim.network import Network
from wsn_sim.simulation import run_smoke_simulation


def main() -> None:
    st.set_page_config(
        page_title="WSN Simulation Dashboard",
        page_icon="📡",
        layout="wide",
    )

    st.title("📡 Wireless Sensor Network (WSN) Simulation Platform")
    st.markdown(
        "Interactive simulation dashboard for large-scale Wireless Sensor Networks. "
        "Built with **NetworkX**, **SimPy**, **NumPy**, **SciPy**, and **Streamlit**."
    )

    # Sidebar parameters
    st.sidebar.header("⚙️ Experiment Parameters")

    seed = st.sidebar.number_input("Random Seed", value=42, step=1)
    num_sensors = st.sidebar.number_input("Number of Sensors", value=450, step=10, min_value=10)
    num_sinks = st.sidebar.number_input("Number of Sinks", value=7, step=1, min_value=1)
    area_size = st.sidebar.number_input("Area Size (m x m)", value=3000.0, step=500.0)

    radius_options = [250.0, 300.0, 350.0]
    radius_mode = st.sidebar.radio("Communication Radius (R)", options=radius_options, index=1)
    custom_radius = st.sidebar.slider(
        "Fine-tune Radius (m)",
        min_value=100.0,
        max_value=600.0,
        value=float(radius_mode),
        step=25.0,
    )

    # Instantiate config and network
    config = SimulationConfig(
        area_width_m=float(area_size),
        area_height_m=float(area_size),
        num_sensors=int(num_sensors),
        num_sinks=int(num_sinks),
        communication_ranges_m=[float(custom_radius)],
        seed=int(seed),
    )

    network = Network(config, communication_range_m=float(custom_radius))
    summary = network.topology_summary()

    # Metric Row
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Nodes", f"{summary['nodes']}")
    col2.metric("Total Edges", f"{summary['edges']}")
    col3.metric("Routable Sensors", f"{summary['routable_sensors']} / {summary['sensors']}")
    col4.metric("Isolated Sensors", f"{summary['isolated_sensors']}")
    avg_degree = (2 * summary["edges"] / summary["nodes"]) if summary["nodes"] > 0 else 0
    col5.metric("Avg Degree", f"{avg_degree:.2f}")

    # Tabs
    tab_topology, tab_simpy, tab_exporters = st.tabs(
        ["🌐 Topology View", "⚡ SimPy Simulation", "📤 Simulator Exporters"]
    )

    with tab_topology:
        st.subheader(f"Network Topology (R = {custom_radius} m)")
        fig, ax = plt.subplots(figsize=(10, 10))
        ax.set_xlim(0, config.area_width_m)
        ax.set_ylim(0, config.area_height_m)
        ax.set_title(
            f"WSN Topology: {summary['sensors']} Sensors, {summary['sinks']} Sinks, R={custom_radius}m",
            fontsize=12,
        )
        ax.set_xlabel("X (meters)")
        ax.set_ylabel("Y (meters)")
        ax.grid(True, linestyle="--", alpha=0.4)

        # Plot edges
        coords = network.coordinates()
        for u, v in network.graph.edges():
            ux, uy = coords[u]
            vx, vy = coords[v]
            ax.plot([ux, vx], [uy, vy], color="#cbd5e1", linewidth=0.5, zorder=1)

        # Plot sensors
        sensor_x = [s.x for s in network.sensors.values()]
        sensor_y = [s.y for s in network.sensors.values()]
        ax.scatter(sensor_x, sensor_y, c="#3b82f6", s=18, label="Sensors", zorder=2)

        # Plot sinks
        sink_x = [s.x for s in network.sinks.values()]
        sink_y = [s.y for s in network.sinks.values()]
        ax.scatter(sink_x, sink_y, c="#ef4444", marker="^", s=120, label="Sinks", zorder=3)

        ax.legend(loc="upper right")
        st.pyplot(fig)
        plt.close(fig)

    with tab_simpy:
        st.subheader("⚡ SimPy Discrete-Event Simulation")
        sim_duration = st.slider(
            "Simulation Duration (seconds)", min_value=5, max_value=60, value=10
        )
        if st.button("Run SimPy Event Simulation", type="primary"):
            sim_res = run_smoke_simulation(network, duration_s=float(sim_duration))
            st.success(f"Simulation completed up to time {sim_res.simulated_time_s}s!")
            st.json(sim_res.to_dict())

    with tab_exporters:
        st.subheader("📤 Export Topology to External Verification Simulators")
        st.markdown(
            "Export current node coordinates and topology to formats used by optional verification engines: "
            "**ns-3**, **OMNeT++ / INET**, and **Contiki-NG Cooja**."
        )

        col_ns3, col_omnet, col_cooja = st.columns(3)

        with col_ns3:
            st.markdown("### ns-3")
            if st.button("Generate ns-3 Mobility"):
                tmp_path = Path("results/temp_ns3.tcl")
                export_to_ns3_mobility(network, tmp_path)
                content = tmp_path.read_text(encoding="utf-8")
                st.download_button(
                    "Download ns-3 Trace (.tcl)", data=content, file_name="ns3_wsn_mobility.tcl"
                )
                st.code(content[:500] + "\n... (truncated)", language="tcl")

        with col_omnet:
            st.markdown("### OMNeT++ / INET")
            if st.button("Generate OMNeT++ NED"):
                tmp_path = Path("results/temp_omnet.ned")
                export_to_omnetpp_ned(network, tmp_path)
                content = tmp_path.read_text(encoding="utf-8")
                st.download_button("Download NED (.ned)", data=content, file_name="wsn_network.ned")
                st.code(content[:500] + "\n... (truncated)", language="ned")

        with col_cooja:
            st.markdown("### Contiki-NG")
            if st.button("Generate Cooja XML"):
                tmp_path = Path("results/temp_cooja.csc")
                export_to_cooja(network, tmp_path)
                content = tmp_path.read_text(encoding="utf-8")
                st.download_button("Download Cooja (.csc)", data=content, file_name="cooja_sim.csc")
                st.code(content[:500] + "\n... (truncated)", language="xml")


if __name__ == "__main__":
    main()
