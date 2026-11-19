from pathlib import Path
from wsn_sim.verification import run_verification
if __name__ == '__main__':
    run_verification(Path(__file__).resolve().parents[1])
