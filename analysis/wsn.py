"""Run the official 10,000-second profile, with optional explicit smoke duration."""

from pathlib import Path
import sys

from wsn_sim.cli import main


if __name__ == "__main__":
    if not any(arg == "--config" or arg.startswith("--config=") for arg in sys.argv[1:]):
        default_config = Path(__file__).resolve().parents[1] / "configs" / "default.json"
        sys.argv[1:1] = ["--config", str(default_config)]
    main()
