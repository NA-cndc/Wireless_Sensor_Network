# SPEC-001: WSN Simulation Baseline & Architecture

> Status: Implemented  
> Aligned with [GitHub Spec Kit](https://github.com/github/spec-kit).

## 1. Problem Statement
Provide a deterministic, reproducible baseline for a Wireless Sensor Network (WSN) consisting of 450 sensors and 7 static sinks distributed across a 3 × 3 km Cartesian coordinate space.

## 2. Technical Specifications
- **Node Count**: 450 sensors (`s_0` to `s_449`), 7 sinks (`sink_0` to `sink_6`).
- **Coordinate Space**: $[0, 3000] \times [0, 3000]$ m.
- **Radii**: Multi-radius topology generation for $R \in [250, 300, 350]$ m.
- **Topology Model**: Undirected graph $G = (V, E)$ using NetworkX with Euclidean distance edge threshold $d(u, v) \le R$.
- **Event Simulation**: SimPy event queue handling discrete packet generation and time-stepped simulation.
- **Visualization**: Headless Matplotlib renderers and interactive Streamlit UI.
- **Quality Gates**: Pytest for test execution, Ruff for linting/formatting, pre-commit for VCS hygiene.

## 3. Simulator Interoperability
- Exportable node maps and mobility files to:
  - **ns-3**: Node positions / mobility trace
  - **OMNeT++ / INET**: NED network structure
  - **Contiki-NG**: Cooja XML (.csc) simulation layout
