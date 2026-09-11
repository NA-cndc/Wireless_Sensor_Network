# AGENTS.md

> Standard conventions and context for AI coding agents operating on the `Wireless_Sensor_Network` repository.
> Inspired by and compliant with [agents.md](https://github.com/agentsmd/agents.md).

## Project Overview

`Wireless_Sensor_Network` is a Python-based, reproducible simulation platform for Wireless Sensor Networks (WSN).

- **Current baseline**: Models 450 sensor nodes and 7 static sinks across a 3000 m × 3000 m Cartesian area.
- **Topology**: Bidirectional connectivity graph generated with NetworkX across transmission radii $R \in \{250, 300, 350\}$ m.
- **Simulation**: SimPy event-driven simulation for packet generation, transmission, and metric tracking.
- **Data & Visualization**: NumPy for reproducible node coordinate generation, pandas for tabular metrics, Matplotlib (headless `Agg`) and Streamlit for visual dashboards.

## Directory Structure

```text
Wireless_Sensor_Network/
├── AGENTS.md                  # Instructions for AI coding assistants
├── .pre-commit-config.yaml    # Code quality git hooks (pre-commit, Ruff)
├── .specify/                  # Specification-driven development artifacts (GitHub Spec Kit)
├── configs/default.json       # Experiment parameters
├── docs/                      # Architectural, parameter, and verification engine docs
├── src/wsn_sim/               # Python package (src layout)
│   ├── models/                # Sensor, Sink, Packet dataclasses
│   ├── config.py              # Configuration loading & validation
│   ├── network.py             # Coordinate generation & NetworkX graphs
│   ├── simulation.py          # SimPy simulation engine
│   ├── metrics.py             # pandas metrics summary
│   ├── storage.py             # CSV, JSON manifest persistence
│   ├── visualization.py       # Matplotlib topology plotting
│   ├── exporters.py           # Exporters for ns-3, OMNeT++/INET, and Contiki-NG
│   └── app.py                 # Streamlit web dashboard
├── scripts/run_demo.py        # Demo runner script
├── tests/                     # pytest test suite
└── results/                   # Output artifacts (csv, figures, run_manifest.json)
```

## Supported Tooling & Repositories

- **AI Agent Support**: [AGENTS.md](https://github.com/agentsmd/agents.md), [GitHub Spec Kit](https://github.com/github/spec-kit).
- **Code Quality**: [pytest](https://github.com/pytest-dev/pytest), [Ruff](https://github.com/astral-sh/ruff), [pre-commit](https://github.com/pre-commit/pre-commit).
- **Core Implementation**: [NetworkX](https://github.com/networkx/networkx), [SimPy](https://gitlab.com/team-simpy/simpy), [SciPy](https://github.com/scipy/scipy), [Streamlit](https://github.com/streamlit/streamlit).
- **Verification Simulators (Optional)**: [ns-3](https://gitlab.com/nsnam/ns-3-dev), [OMNeT++](https://github.com/omnetpp/omnetpp), [INET](https://github.com/inet-framework/inet), [Contiki-NG](https://github.com/contiki-ng/contiki-ng).

## Development Commands

- **Run unit & integration tests**:
  ```bash
  python -m pytest -q
  ```
- **Lint and format with Ruff**:
  ```bash
  python -m ruff check .
  python -m ruff format .
  ```
- **Run baseline demonstration**:
  ```bash
  python scripts/run_demo.py
  ```
- **Run interactive Streamlit dashboard**:
  ```bash
  python -m streamlit run src/wsn_sim/app.py
  ```

## Agent Guidelines & Rules

1. **Determinism & Reproducibility**: Always preserve random seeds (`seed=42`) to guarantee identical topology generation across runs.
2. **Headless Execution**: Ensure Matplotlib uses `matplotlib.use("Agg")` to support running in headless CLI environments without display servers.
3. **No Domain Pollution**: Do not hardcode routing heuristics or energy models into `Network` or `Sensor` classes; keep routing algorithms modularized.
4. **Data Validation**: Any configuration changes must pass schema validation defined in `SimulationConfig`.
