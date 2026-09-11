"""Repository entry point for the initial WSN demonstration."""

from pathlib import Path

from wsn_sim.demo import run_demo

if __name__ == "__main__":
    run_demo(Path(__file__).resolve().parents[1])
