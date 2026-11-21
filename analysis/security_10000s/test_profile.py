import copy
from dataclasses import replace
from io import BytesIO
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from study import DEFAULT_PROJECT, JOB_SCOPE, build_short_plan, cases, load_project, profile_config, study_job, verify_short_plan

ROOT = load_project(DEFAULT_PROJECT)
from wsn_sim.calibration import json_digest, source_fingerprint
from wsn_sim.config import DetectorConfig
from wsn_sim.models import Sensor, Sink
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation


@pytest.fixture(scope="module")
def published_root(tmp_path_factory):
    snapshot = tmp_path_factory.mktemp("published_source")
    with ZipFile(ROOT / "data/security_10000s.zip") as package:
        with ZipFile(BytesIO(package.read("batch/source_snapshot.zip"))) as source:
            source.extractall(snapshot)
        (snapshot / "configs/default.json").write_bytes(package.read("batch/experiment_10000s.json"))
    return snapshot


@pytest.fixture(scope="module")
def plan(published_root):
    return build_short_plan(published_root)


def resign(plan):
    for job in plan["jobs"]:
        job.pop("run_id", None)
        job["run_id"] = json_digest(job)[:24]
    plan.pop("plan_hash", None)
    plan["plan_hash"] = json_digest(plan)
    return plan


def test_published_profile_has_16_cases_30_seeds_and_valid_freeze(plan, published_root):
    assert verify_short_plan(plan, published_root)
    assert len(plan["jobs"]) == 480
    assert all(job["scope"] == JOB_SCOPE for job in plan["jobs"])
    assert plan["freeze"]["verified"]
    assert plan["analysis_protocol"]["boundary_rule"] == "include_all_events_at_t_le_10000_hold_later_arrivals_in_flight_no_drain"
    assert plan["analysis_protocol"]["sample_interval_s"] == 100
    assert all(len({job["seed"] for job in plan["jobs"] if job["case"] == case}) == 30 for case in plan["cases"])


@pytest.mark.parametrize("mutation", ["long", "pilot", "duplicate", "energy", "test_scope", "wrong_security_cutoff"])
def test_rejects_wrong_horizon_and_undeclared_changes(plan, mutation, published_root):
    changed = copy.deepcopy(plan)
    if mutation == "long":
        changed["jobs"][0]["configuration"]["max_rounds"] = 10000
    elif mutation == "pilot":
        changed["jobs"][0]["pilot_duration_s"] = 10000
    elif mutation == "duplicate":
        changed["jobs"][1] = copy.deepcopy(changed["jobs"][0])
    elif mutation == "energy":
        changed["base_configuration"]["initial_energy_j"] = 1
    elif mutation == "wrong_security_cutoff":
        changed["analysis_protocol"]["security_cutoff_s"] = 1000
    else:
        changed["jobs"][0]["scope"] = "TEST_ONLY"
    with pytest.raises(ValueError):
        verify_short_plan(resign(changed), published_root)


def test_current_profile_refuses_the_published_freeze():
    with pytest.raises(ValueError, match="recalibration is required"):
        build_short_plan(ROOT)


def test_current_test_samples_pair_exogenous_inputs():
    config = profile_config(ROOT)
    detector = DetectorConfig(0.5, 5, 1, 1, 0.8, 2, 1, 10)
    selected = [case for case in cases() if case["scenario"] in {"MHR", "EMHR", "SF3"}][:3]
    jobs = [study_job(config, case, 51001, detector, source_fingerprint(ROOT), None) for case in selected]
    assert {job["case"]["scenario"] for job in jobs} == {"MHR", "EMHR", "SF3"}
    assert {job["scope"] for job in jobs} == {"TEST_ONLY"}
    assert len({job["pairing_hash"] for job in jobs}) == 1
    assert all(job["configuration"]["topology_model"] == "na" for job in jobs)
    assert all(job["configuration"]["max_rounds"] == 1000 for job in jobs)


@pytest.mark.parametrize("bandwidth", [250000, 102.4])
def test_10000_second_cutoff_keeps_last_packet_in_flight(bandwidth):
    config = replace(profile_config(ROOT), num_sensors=1, num_sinks=1, attacker_ids=(), attacker_ratio=0, p_drop=0, channel_loss_probability=0, routing_algorithm="EMHR", detector=None, bandwidth_bps=bandwidth)
    network = Network(config, sensors={"s": Sensor("s", 0, 0, 5)}, sinks={"k": Sink("k", 10, 0)})
    simulation = Simulation(config, network=network)
    simulation.run_for(10000)
    summary = simulation.summary()
    performance = summary["performance"]
    assert summary["time_s"] == 10000
    assert summary["rounds"] == 1000
    assert performance["generated"] == 1000
    assert performance["delivered"] == 999
    assert performance["pending_in_flight"] == 1
    assert performance["dropped"] == 0
    assert performance["received_payload_bits"] == 999 * 1024
    assert performance["mean_actual_hops"] == 1
    assert performance["mean_latency_s"] == pytest.approx(1024 / bandwidth)
    assert performance["conservation_ok"] and performance["energy_conservation_ok"]
    assert all(event["time_s"] <= 10000 for event in simulation.traffic_gen.events)
    assert simulation.run_for(10) == 10000
    assert simulation.summary()["performance"]["delivered"] == 999


def test_csv_reload_preserves_paired_lifetime_rounding(tmp_path):
    import numpy as np
    import pandas as pd
    from verify_report import read_numeric_csv

    first, second = 1680.0204799999995, 1670.0327679999991
    path = tmp_path / "paired.csv"
    pd.DataFrame({"first": [first], "second": [second]}).to_csv(path, index=False)
    row = read_numeric_csv(path).iloc[0]
    assert row["first"] == first and row["second"] == second
    assert np.round(row["first"] - row["second"], 12) == np.round(first - second, 12)
