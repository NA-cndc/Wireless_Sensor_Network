"""Compare deterministic data from two runs of the three acceptance scenarios."""

from argparse import ArgumentParser
import json
from math import isclose
from pathlib import Path


def compare(left, right, name):
    if isinstance(left, dict) and isinstance(right, dict) and left.keys() == right.keys():
        return max((compare(left[key], right[key], f"{name}.{key}") for key in left), default=0)
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return max((compare(a, b, f"{name}[{i}]") for i, (a, b) in enumerate(zip(left, right))), default=0)
    if type(left) is float and type(right) is float and isclose(left, right, rel_tol=1e-12, abs_tol=1e-9):
        return abs(left - right)
    if type(left) is not type(right) or left != right:
        raise ValueError(f"{name}: {left!r} differs from {right!r}")
    return 0


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    for scenario in ("MHR", "EMHR", "SF3"):
        left, right = (path / scenario for path in (args.reference, args.candidate))
        maximum = 0
        for name in ("summary.json", "lifetime.json", "topology.json", "final_sensor_states.json"):
            a, b = (json.loads((path / name).read_text(encoding="utf-8")) for path in (left, right))
            maximum = max(maximum, compare(a, b, name))
        if (left / "timeseries.csv").read_bytes() != (right / "timeseries.csv").read_bytes():
            raise ValueError(f"{scenario}: time series differs")
        print(f"{scenario}: max_absolute_difference={maximum:g}")


if __name__ == "__main__":
    main()
