"""Repository entry point for the initial WSN demonstration."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wsn_sim.demo import run_demo


if __name__ == "__main__":
    run_demo(PROJECT_ROOT)
