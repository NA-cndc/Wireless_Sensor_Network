from argparse import ArgumentParser
from dataclasses import replace
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
import zipfile


DEFAULT_PROJECT = Path(__file__).resolve().parents[2]
HORIZON_S = 10000.0
PROFILE = "WSN_SECURITY_FIXED_HORIZON_10000S_V1"
JOB_SCOPE = "EVALUATION_FIXED_HORIZON_10000S"
SEEDS = list(range(51001, 51031))


def load_project(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root / "src"))
    module = importlib.import_module("wsn_sim.config")
    if module.DEFAULT_CONFIG_PATH.resolve().parents[1] != root:
        raise ValueError("simulation modules belong to another project")
    return root


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cases():
    from wsn_sim.experiment_plan import definitions
    result = definitions(core_only=True)
    for rho, probability, placement in ((0.02, 0.5, "random"), (0.1, 0.5, "random"), (0.05, 0.25, "random"), (0.05, 0.75, "random"), (0.05, 0.5, "near_sink")):
        for scenario in ("EMHR_SF", "SF3"):
            result.append({"scenario": scenario, "rho": rho, "p_drop": probability, "placement": placement, "case_id": f"{scenario}_r{rho:g}_d{probability:g}_{placement}"})
    return result


def profile_config(root):
    from wsn_sim.config import SimulationConfig
    return SimulationConfig.from_json(root / "configs/default.json")


def verify_short_plan(plan, root):
    from wsn_sim.calibration import json_digest
    from wsn_sim.config import SimulationConfig
    from wsn_sim.experiment_plan import PAIR_FIELDS, SCENARIOS, verify_plan
    verify_plan(plan, root)
    if plan.get("evaluation_profile") != PROFILE or plan["scope"] != "EVALUATION":
        raise ValueError("expected the official 10000-second evaluation profile")
    if plan["seeds"] != SEEDS or plan["cases"] != cases() or plan["expected_runs"] != 480 or len(plan["jobs"]) != 480:
        raise ValueError("profile requires 16 cases and 30 distinct seeds per case")
    if plan["base_configuration"] != profile_config(root).to_dict():
        raise ValueError("base configuration differs from the declared short profile")
    protocol = plan["analysis_protocol"]
    if protocol["horizon_s"] != HORIZON_S or protocol["security_cutoff_s"] != HORIZON_S or protocol["max_rounds"] != 1000 or protocol["sample_interval_s"] != 100 or protocol["last_generation_s"] != HORIZON_S:
        raise ValueError("numeric protocol fields disagree with the 10000-second evaluation")
    basis = read_json(Path(plan["detector_path"]).with_suffix(".lock.json"))
    for key in PAIR_FIELDS:
        if key not in {"seed", "channel_loss_probability", "max_rounds"} and plan["base_configuration"][key] != basis["simulation_configuration"][key]:
            raise ValueError(f"calibration basis mismatch: {key}")
    if plan["base_configuration"]["channel_loss_probability"] not in basis["protocol"]["channel_loss_probabilities"]:
        raise ValueError("channel loss not covered by calibration")
    keys = set()
    for job in plan["jobs"]:
        config = SimulationConfig.from_dict(job["configuration"])
        case = job["case"]
        if job["scope"] != JOB_SCOPE or "pilot_duration_s" in job or job.get("observation_horizon_s") != HORIZON_S:
            raise ValueError("short evaluation must not use pilot/test duration overrides")
        if config.max_rounds != 1000 or config.packet_interval_s != 10 or config.max_duration_s != HORIZON_S or job["sample_interval_s"] != 100:
            raise ValueError("each run must keep 1000 rounds, 100-second sampling and a 10000-second cutoff")
        algorithm, attacked, detecting = SCENARIOS[case["scenario"]]
        expected = replace(SimulationConfig.from_dict(plan["base_configuration"]), seed=job["seed"], routing_algorithm=algorithm, detector=config.detector if detecting else None, attacker_ratio=case["rho"] if attacked else 0, p_drop=case["p_drop"] if attacked else 0, attacker_ids=None if attacked else (), attacker_selection=case["placement"])
        if config != expected:
            raise ValueError("unexpected treatment parameters")
        if detecting:
            from dataclasses import asdict
            if asdict(config.detector) != read_json(plan["detector_path"]):
                raise ValueError("detector differs from the frozen parameters")
        if job["pairing_hash"] != json_digest({key: job["configuration"][key] for key in PAIR_FIELDS}):
            raise ValueError("exogenous pairing hash mismatch")
        key = (case["case_id"], job["seed"])
        if key in keys or case not in plan["cases"] or job["seed"] not in SEEDS:
            raise ValueError("duplicate or unknown evaluation case/seed")
        keys.add(key)
    return True


def build_short_plan(root):
    from wsn_sim.calibration import json_digest, source_fingerprint, verify_freeze
    from wsn_sim.config import DetectorConfig
    from wsn_sim.experiment_plan import PAIR_FIELDS, SCENARIOS, validate_evaluation_seeds
    base = profile_config(root)
    detector_path = root / "configs/detector_stage78.json"
    frozen = verify_freeze(detector_path, root)
    detector = DetectorConfig(**read_json(detector_path))
    validate_evaluation_seeds(root, SEEDS)
    fingerprint = source_fingerprint(root)
    jobs = []
    for case in cases():
        algorithm, attacked, detecting = SCENARIOS[case["scenario"]]
        for seed in SEEDS:
            config = replace(base, seed=seed, routing_algorithm=algorithm, detector=detector if detecting else None, attacker_ratio=case["rho"] if attacked else 0, p_drop=case["p_drop"] if attacked else 0, attacker_ids=None if attacked else (), attacker_selection=case["placement"])
            values = config.to_dict()
            job = {"case": case, "configuration": values, "seed": seed, "source_sha256": fingerprint["sha256"], "freeze": frozen, "sample_interval_s": 100, "full_trace": False, "scope": JOB_SCOPE, "observation_horizon_s": HORIZON_S, "pairing_hash": json_digest({key: values[key] for key in PAIR_FIELDS})}
            job["run_id"] = json_digest(job)[:24]
            jobs.append(job)
    protocol = {
        "version": PROFILE, "registered_at_utc": datetime.now(timezone.utc).isoformat(),
        "horizon_s": HORIZON_S, "max_rounds": 1000, "sample_interval_s": 100,
        "cases": 16, "seeds_per_case": 30, "independent_unit": "seed",
        "design": "one_factor_at_a_time", "interactions_estimated": False,
        "boundary_rule": "include_all_events_at_t_le_10000_hold_later_arrivals_in_flight_no_drain",
        "first_generation_s": 10, "last_generation_s": 10000,
        "security_cutoff_s": HORIZON_S, "long_horizon_data_mixed": False,
        "request_resolution": {"effective_horizon_s": HORIZON_S, "effective_rounds": 1000, "authoritative_request_sections": [1, 5, 7, 8], "stale_1000_second_template_references_normalized": True, "previous_1000s_and_100000s_studies_preserved": True},
        "sampling_rule": "record_every_100_seconds_keep_10_second_packet_generation_and_exact_event_time_milestones",
        "horizon_selected_by_user_after_reviewing_previous_long_horizon_results": True,
        "detector_retuned_on_evaluation": False,
        "statistics": {"std_ddof": 1, "ci": "Student_t_95_percent", "paired_tests": ["paired_t", "Wilcoxon_Pratt"], "multiplicity": "Holm_all_declared_metrics_and_contrasts"},
    }
    plan = {"version": "wsn_experiments_v1", "scope": "EVALUATION", "evaluation_profile": PROFILE, "analysis_protocol": protocol, "base_configuration": base.to_dict(), "source_fingerprint": fingerprint, "range_pilot": read_json(root / "configs/experiment_selection.json"), "detector_path": str(detector_path), "freeze": frozen, "seeds": SEEDS, "cases": cases(), "jobs": jobs, "expected_runs": 480, "independent_seeds_per_configuration": 30, "extension_pending": {"factorial_interactions": "outside_requested_short_study", "long_horizon": "preserved_in_separate_original_reports"}}
    plan["plan_hash"] = json_digest(plan)
    verify_short_plan(plan, root)
    return plan


def prepare(root, output):
    from wsn_sim.storage import create_run_directory, save_json
    plan = build_short_plan(root)
    directory = create_run_directory(output.resolve(), "evaluation_10000s")
    save_json(plan, directory / "plan.json")
    save_json(plan["base_configuration"], directory / "experiment_10000s.json")
    save_json(plan["analysis_protocol"], directory / "protocol.json")
    save_effective_protocol(plan, directory)
    save_json({"plan_hash": plan["plan_hash"], "runs": {}, "attempts": [], "status": "PREPARED"}, directory / "checkpoint.json")
    save_json({"reused_runs": 0, "new_runs_planned": 480, "long_horizon_results_reused_as_short_metrics": False}, directory / "reuse_manifest.json")
    with zipfile.ZipFile(directory / "source_snapshot.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for relative in plan["source_fingerprint"]["files"]:
            archive.write(root / relative, relative)
        for path in (root / "configs").glob("*.json"):
            relative = path.relative_to(root).as_posix()
            if relative not in plan["source_fingerprint"]["files"]:
                archive.write(path, relative)
    return directory


def save_effective_protocol(plan, directory):
    """Keep original registration hashes; append explicit corrections of descriptive text."""
    from wsn_sim.storage import save_json
    effective = dict(plan["analysis_protocol"])
    if effective["horizon_s"] != HORIZON_S or effective["max_rounds"] != 1000 or any(job["configuration"]["max_rounds"] * job["configuration"]["packet_interval_s"] != HORIZON_S for job in plan["jobs"]):
        raise ValueError("cannot clarify a protocol with inconsistent execution horizons")
    correct = "include_all_events_at_t_le_10000_hold_later_arrivals_in_flight_no_drain"
    original = effective["boundary_rule"]
    if original not in {correct, "include_all_events_at_t_le_1000_hold_later_arrivals_in_flight_no_drain"}:
        raise ValueError("unrecognized boundary rule")
    effective["boundary_rule"] = correct
    effective["original_plan_hash"] = plan["plan_hash"]
    effective["description_correction"] = None if original == correct else {"field": "boundary_rule", "original": original, "corrected": correct, "reason": "stale_numeric_text_from_1000s_template_actual_configuration_and_measurements_are_10000s", "execution_changed": False, "original_plan_or_job_hashes_modified": False}
    save_json(effective, Path(directory) / "protocol_effective.json")
    return effective


def main():
    parser = ArgumentParser(description="Official fixed-horizon 10000-second security evaluation")
    parser.add_argument("mode", choices=("prepare", "run", "resume", "status", "dry-run", "sample"))
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--scenario", choices=("MHR", "EMHR", "SF3"))
    args = parser.parse_args()
    root = load_project(args.project)
    if args.mode == "sample":
        if args.scenario is None or args.output is None:
            parser.error("sample requires --scenario and a new --output directory")
        from wsn_sim.experiment_execution import execute_worker
        plan = build_short_plan(root)
        job = next(job for job in plan["jobs"] if job["case"]["scenario"] == args.scenario)
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=False)
        execute_worker(job, output, root)
        print(output)
        return
    if args.mode == "dry-run":
        plan = build_short_plan(root)
        print(json.dumps({"profile": PROFILE, "cases": 16, "runs": 480, "horizon_s": HORIZON_S, "max_rounds": 1000, "source_sha256": plan["source_fingerprint"]["sha256"], "freeze_verified": plan["freeze"]["verified"]}, indent=2))
        return
    if args.mode in {"prepare", "run"}:
        directory = prepare(root, args.output or root / "results/security_10000s")
    else:
        if args.batch is None:
            raise ValueError("--batch is required")
        directory = args.batch.resolve()
    print(f"batch_directory={directory}", flush=True)
    plan = read_json(directory / "plan.json")
    verify_short_plan(plan, root)
    if args.mode in {"run", "resume"}:
        from wsn_sim.experiments import run_batch
        state = run_batch(plan, directory, root, workers=args.workers, timeout_s=3600, retries=1)
        if state["status"] != "COMPLETE":
            raise RuntimeError("evaluation has failed or unfinished runs")
    elif args.mode == "status":
        from wsn_sim.experiments import progress
        print(json.dumps(progress(plan, read_json(directory / "checkpoint.json")), indent=2))


if __name__ == "__main__":
    main()
