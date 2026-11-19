"""Verify and regenerate the published security study from its portable archive."""

from argparse import ArgumentParser
from collections import Counter
import csv
from hashlib import sha256
from io import StringIO
import json
from math import isclose
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from report_vi import build_tables_and_figures
from study import DEFAULT_PROJECT, HORIZON_S, JOB_SCOPE, load_project, read_json


PUBLISHED_SHA256 = "55be594df949a03501e1063acbcbd21d9d1ba7757be441aef01c711e335a476b"


def load_records(directory):
    from wsn_sim.calibration import json_digest, source_fingerprint, verify_freeze
    from wsn_sim.experiment_execution import valid_completion
    from wsn_sim.experiment_plan import PAIR_FIELDS

    plan = read_json(directory / "batch/plan.json")
    checkpoint = read_json(directory / "batch/checkpoint.json")
    body = dict(plan)
    if json_digest({k: v for k, v in body.items() if k != "plan_hash"}) != plan["plan_hash"]:
        raise ValueError("published plan hash mismatch")
    if checkpoint["plan_hash"] != plan["plan_hash"] or checkpoint["status"] != "COMPLETE":
        raise ValueError("published checkpoint mismatch")
    snapshot = directory / "source"
    with ZipFile(directory / "batch/source_snapshot.zip") as source_archive:
        source_archive.extractall(snapshot)
    if source_fingerprint(snapshot) != plan["source_fingerprint"]:
        raise ValueError("archived source fingerprint mismatch")
    freeze = verify_freeze(snapshot / "configs/detector_stage78.json", snapshot)
    if freeze["config_file_sha256"] != plan["freeze"]["config_file_sha256"]:
        raise ValueError("archived detector hash mismatch")
    rows = read_json(directory / "report/portable_run_index.json")
    index = {row["run_id"]: row for row in rows}
    if len(index) != len(rows) or len(index) != 480 or len(plan["jobs"]) != 480:
        raise ValueError("expected 480 unique archived runs")
    records, groups, pairs = [], set(), {}
    for job in plan["jobs"]:
        run_id = job["run_id"]
        row, config = index[run_id], job["configuration"]
        case = job["case"]
        directory_name = f"raw/{run_id}"
        raw = directory / directory_name
        if row["archive_directory"] != directory_name or row["seed"] != job["seed"] or row["case_id"] != case["case_id"]:
            raise ValueError(f"portable index mismatch for {run_id}")
        if json_digest({k: v for k, v in job.items() if k != "run_id"})[:24] != run_id or not valid_completion(raw, job):
            raise ValueError(f"run hash mismatch for {run_id}")
        summary, manifest = (read_json(raw / name) for name in ("summary.json", "run_manifest.json"))
        pairing_hash = json_digest({key: config[key] for key in PAIR_FIELDS})
        if (job["scope"] != JOB_SCOPE or config["max_rounds"] != 1000 or config["packet_interval_s"] != 10
                or manifest["requested_horizon_s"] != HORIZON_S or summary["time_s"] != manifest["actual_duration_s"]
                or not 0 < summary["time_s"] <= HORIZON_S
                or (summary["time_s"] < HORIZON_S and summary["stop_reason"] != "LND")
                or manifest["source_sha256"] != plan["source_fingerprint"]["sha256"]
                or job["pairing_hash"] != pairing_hash or manifest["pairing_hash"] != pairing_hash):
            raise ValueError(f"profile or provenance mismatch for {run_id}")
        group = (case["case_id"], job["seed"])
        if group in groups:
            raise ValueError(f"duplicate treatment/seed {group}")
        groups.add(group)
        pair = (job["seed"], case["rho"], case["p_drop"], case["placement"])
        actual = (pairing_hash, manifest["topology_hash"], sorted(manifest["attack"]["attacker_ids"]))
        if pairs.setdefault(pair, actual) != actual:
            raise ValueError(f"paired input mismatch for {run_id}")
        records.append({"job": job, "summary": summary, "manifest": manifest, "directory": raw})
    counts = Counter(case_id for case_id, _ in groups)
    if len(counts) != 16 or set(counts.values()) != {30}:
        raise ValueError("expected 30 distinct seeds per treatment")
    return plan, checkpoint, records


def compare_published_tables(output, directory):
    maximum = 0.0
    for path in sorted(output.rglob("*.csv")):
        name = path.relative_to(output)
        reference = directory / "report" / name
        if not reference.is_file():
            continue
        before, after = (list(csv.DictReader(StringIO(file.read_text(encoding="utf-8-sig")))) for file in (reference, path))
        if len(before) != len(after):
            raise ValueError(f"row count mismatch: {name}")
        for i, (a, b) in enumerate(zip(before, after), start=2):
            if a.keys() != b.keys():
                raise ValueError(f"column mismatch: {name}")
            for key in a:
                if a[key] == b[key] or key == "directory":
                    continue
                try:
                    x, y = float(a[key]), float(b[key])
                except ValueError:
                    raise ValueError(f"value mismatch: {name}:{i} {key}") from None
                atol = 1e-8 if key == "difference_shapiro_p" else 1e-9
                if not isclose(x, y, rel_tol=1e-12, abs_tol=atol):
                    raise ValueError(f"numeric mismatch: {name}:{i} {key}")
                maximum = max(maximum, abs(x - y))
        if after and "directory" in after[0] and "run_id" in after[0]:
            for row in after:
                row["directory"] = f"data/security_10000s.zip!/raw/{row['run_id']}"
            with path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=after[0].keys())
                writer.writeheader()
                writer.writerows(after)
    return maximum


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = load_project(DEFAULT_PROJECT)
    package = root / "data/security_10000s.zip"
    if sha256(package.read_bytes()).hexdigest() != PUBLISHED_SHA256:
        raise ValueError("published archive SHA-256 mismatch")
    with TemporaryDirectory(prefix="wsn-security-", dir=root / "results") as staging:
        directory = Path(staging)
        with ZipFile(package) as archive:
            inventory = json.loads(archive.read("package_inventory.json"))
            for entry in inventory:
                raw = archive.read(entry["path"])
                if len(raw) != entry["size"] or sha256(raw).hexdigest() != entry["sha256"]:
                    raise ValueError(f"invalid archived member {entry['path']}")
            archive.extractall(directory)
        plan, checkpoint, records = load_records(directory)
        args.output.mkdir(parents=True, exist_ok=False)
        *_, figures = build_tables_and_figures(plan, checkpoint, records, args.output)
        maximum = compare_published_tables(args.output, directory)
        print(json.dumps({"verified_runs": len(records), "cases": 16, "seeds_per_case": 30, "figures": len(figures), "max_absolute_difference": maximum}))


if __name__ == "__main__":
    main()
