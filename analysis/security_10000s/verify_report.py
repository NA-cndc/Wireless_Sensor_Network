from argparse import ArgumentParser
from collections import Counter
import csv
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from html.parser import HTMLParser
import io
import json
from math import isclose, sqrt
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from scipy import stats

from study import DEFAULT_PROJECT, JOB_SCOPE, SEEDS, load_project, read_json, verify_short_plan
from charts_vi import METRICS, PACKET_CATEGORIES, PLOT_TIMES_S, number_label



def read_numeric_csv(path):
    return pd.read_csv(path, float_precision="round_trip")


def same(a, b, message="numeric mismatch", abs_tol=1e-8):
    missing_a = a is None or isinstance(a, (float, np.floating)) and np.isnan(a)
    missing_b = b is None or isinstance(b, (float, np.floating)) and np.isnan(b)
    if missing_a or missing_b:
        if missing_a != missing_b:
            raise ValueError(message + ": NA mismatch")
    elif not isclose(float(a), float(b), rel_tol=1e-10, abs_tol=abs_tol):
        raise ValueError(f"{message}: {a} != {b}")


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
    def handle_starttag(self, tag, attributes):
        for key, value in attributes:
            if key in ("href", "src"):
                self.links.append(value)


def compare_old_prefix(records, output, long_report=None):
    """Independent validation only; no long-run metric is fed into the new report."""
    if long_report is None:
        return {"status": "not_requested", "long_metrics_reused": False}
    old = read_numeric_csv(long_report / "runs.csv")
    index = {(row.case_id, int(row.seed)): row for row in old.itertuples()}
    comparisons = []
    for record in records:
        job = record["job"]
        old_row = index[(job["case"]["case_id"], job["seed"])]
        if old_row.topology_hash != record["manifest"]["topology_hash"]:
            raise ValueError("prefix comparison requires the same physical topology")
        path = Path(old_row.directory) / "timeseries.csv"
        with path.open(encoding="utf-8-sig", newline="") as handle:
            previous = next((row for row in csv.DictReader(handle) if float(row["time_s"]) == 10000), None)
        if previous is None:
            raise ValueError("old checkpoint missing exact 10000-second sample")
        frame = read_numeric_csv(record["directory"] / "timeseries.csv")
        endpoint = frame.iloc[-1]
        if endpoint.time_s != 10000:
            raise ValueError("new run has no 10000-second sample")
        keys = [key for key in frame.columns if key != "time_s" and key in previous]
        for key in keys:
            if previous[key] == "":
                if not pd.isna(endpoint[key]):
                    raise ValueError("old/new prefix NA mismatch")
            else:
                same(endpoint[key], float(previous[key]), "prefix " + job["run_id"] + "/" + key)
        comparisons.append({"run_id": job["run_id"], "case_id": job["case"]["case_id"], "seed": job["seed"], "checked_fields": len(keys), "all_match": True, "old_timeseries": str(path), "old_metrics_used_to_compute_new_report": False})
    pd.DataFrame(comparisons).to_csv(output / "prefix_crosscheck_10000s.csv", index=False, encoding="utf-8-sig")
    return {"status": "PASS", "runs_checked": len(comparisons), "comparison_time_s": 10000, "only_prefix_samples_compared": True, "long_metrics_reused": False}


def verify_report(root, batch, directory, check_package=True):
    from wsn_sim.calibration import source_fingerprint, verify_freeze
    from wsn_sim.evaluation import classification_metrics
    from wsn_sim.experiment_execution import file_hash
    from wsn_sim.experiment_tables import collect_batch
    from wsn_sim.experiment_statistics import holm_adjust
    plan, checkpoint, records = collect_batch(batch, root)
    verify_short_plan(plan, root)
    protocol = read_json(directory / "protocol_effective.json")
    assert protocol["horizon_s"] == 10000 and protocol["max_rounds"] == 1000 and protocol["sample_interval_s"] == 100
    assert protocol["boundary_rule"] == "include_all_events_at_t_le_10000_hold_later_arrivals_in_flight_no_drain"
    assert protocol["original_plan_hash"] == plan["plan_hash"]
    if protocol["description_correction"] is not None:
        correction = protocol["description_correction"]
        assert correction["original"] == plan["analysis_protocol"]["boundary_rule"]
        assert correction["corrected"] == protocol["boundary_rule"]
        assert not correction["execution_changed"] and not correction["original_plan_or_job_hashes_modified"]
    assert checkpoint["status"] == "COMPLETE" and len(records) == 480
    assert Counter(record["job"]["case"]["case_id"] for record in records) == {case["case_id"]: 30 for case in plan["cases"]}
    assert source_fingerprint(root)["sha256"] == plan["source_fingerprint"]["sha256"]
    freeze = verify_freeze(Path(plan["detector_path"]), root)
    runs = read_numeric_csv(directory / "runs.csv")
    aggregates = read_numeric_csv(directory / "aggregate.csv")
    lifetimes = read_numeric_csv(directory / "lifetime_per_seed.csv")
    lifetime_table = read_numeric_csv(directory / "bang_lifetime.csv")
    pairs = read_numeric_csv(directory / "paired_comparisons.csv")
    relay_frame = read_numeric_csv(directory / "relay_security_per_seed.csv")
    relay_snapshots = {(row.run_id, row.node_id): row for row in relay_frame.itertuples()}
    assert len(relay_frame) == len(relay_snapshots) == sum(
        len(record["summary"]["detector"]["relays"]) for record in records if record["summary"]["detector"]
    )
    assert len(runs) == 480 and runs["run_id"].nunique() == 480
    assert (runs.groupby("case_id")["topology_hash"].nunique() == 30).all()
    assert (runs["requested_horizon_s"] == 10000).all()
    indexed = {row.run_id: row for row in runs.itertuples()}
    record_index = {record["job"]["run_id"]: record for record in records}
    all_pair_groups = {}
    for record in records:
        spec, summary, manifest = record["job"], record["summary"], record["manifest"]
        row = indexed[spec["run_id"]]
        states = read_json(record["directory"] / "final_sensor_states.json")
        perf, security, detector = summary["performance"], summary["security"], summary["detector"]
        assert spec["scope"] == manifest["scope"] == JOB_SCOPE
        end = summary["time_s"]
        assert end == security["evaluation_time_s"] == manifest["actual_duration_s"] == row.actual_duration_s
        assert 0 <= end <= manifest["requested_horizon_s"] == 10000
        assert end == 10000 or summary["stop_reason"] == "LND"
        assert 0 <= summary["rounds"] == row.rounds <= spec["configuration"]["max_rounds"] == 1000
        sensor_count = len(states)
        assert sensor_count == manifest.get("actual_num_sensors", spec["configuration"]["num_sensors"])
        if spec["configuration"].get("topology_model") == "na":
            assert 400 <= sensor_count <= 500
            assert manifest["topology_seed"] == spec["seed"]
        count = int((Decimal(str(spec["case"]["rho"])) * sensor_count).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        assert manifest["attack"]["attacker_count"] == count
        same(manifest["attack"]["actual_ratio"], count / sensor_count)
        assert set(manifest["attack"]["attacker_ids"]).issubset(states)
        assert manifest["stream_seeds"] == summary["stream_seeds"]
        assert perf["conservation_ok"] and perf["energy_conservation_ok"]
        assert perf["generated"] == perf["delivered"] + perf["dropped"] + perf["pending_in_flight"]
        assert perf["delivered"] == perf["received_unique_at_sink"]
        assert perf["duplicate_delivery_events"] == perf["duplicate_created_events"] == 0
        assert sum(perf["drop_reasons"].values()) == perf["dropped"]
        same(sum(state["energy_j"] for state in states.values()), perf["remaining_energy_j"], "remaining energy")
        same(sensor_count * spec["configuration"]["initial_energy_j"] - perf["remaining_energy_j"],
             perf["consumed_since_start_j"], "energy depletion")
        same(perf["energy_from_events_j"], perf["consumed_since_start_j"], "radio event energy", abs_tol=1e-7)
        assert perf["generated"] == sum(state["generated"] for state in states.values())
        assert row.alive_sensors == sum(state["alive"] for state in states.values())
        assert row.physical_reachable_alive == summary["reachability"]["physical_reachable_alive"]
        assert row.routing_reachable_alive == summary["reachability"]["routing_reachable_alive"]
        same(row.pdr, perf["delivered"] / perf["generated"] if perf["generated"] else None)
        same(row.throughput_bps, perf["received_wire_bits"] / end if end else None)
        same(row.goodput_bps, perf["received_payload_bits"] / end if end else None)
        same(row.energy_per_payload_bit_j, perf["consumed_since_start_j"] / perf["received_payload_bits"] if perf["received_payload_bits"] else None)
        for key in ("generated", "delivered", "dropped", "pending_in_flight", "received_payload_bits", "received_wire_bits", "mean_latency_s", "mean_actual_hops", "reroute_decision_count", "route_edges_changed"):
            same(getattr(row, key), perf[key], "per-run " + key)
        assert all(perf[key] is None for key in ("monitoring_energy_j", "monitoring_time_s", "control_packets"))
        assert row.detector_enabled == (detector is not None)
        assert row.routing_avoidance_enabled == (spec["configuration"]["routing_algorithm"] == "S_EMHR")
        events = perf["security_overhead"]["logical_state_events"].get("isolated", 0)
        assert row.detector_isolation_events == row.isolation_events == events
        assert row.security_reroute_decision_count == perf["reroute_decision_categories"].get("security", 0)
        if not row.routing_avoidance_enabled:
            assert row.security_reroute_decision_count == 0
        if detector:
            assert detector["time_s"] == end and detector["conservation_ok"] and detector["input_conservation_ok"]
            relays = detector["relays"]
            assert set(relays) == set(states)
            for node, state in relays.items():
                for key in ("first_received_at", "suspected_at", "isolated_at", "probation_started_at_s"):
                    assert state[key] is None or 0 <= state[key] <= end
                exported = relay_snapshots[(row.run_id, node)]
                for field, original in (("received_transit_total", "received_transit"), ("forwarded_total", "forwarded"), ("failed_timeout_total", "failed_timeout"), ("pending_total", "pending"), ("trust_at_cutoff", "trust"), ("valid_windows", "valid_windows"), ("first_suspected_s", "suspected_at"), ("first_isolated_s", "isolated_at")):
                    same(getattr(exported, field), state[original], "relay snapshot " + field)
                same(exported.forwarding_ratio_cumulative, state["forwarded"] / state["received_transit"] if state["received_transit"] else None)
                assert exported.evaluation_time_s == end
                assert exported.ground_truth_attacker_for_evaluation_only == (node in manifest["attack"]["attacker_ids"])
                assert exported.suspected_current == state["suspected"]
                assert exported.received_transit_total == exported.forwarded_total + exported.failed_timeout_total + exported.pending_total
            predicted = {node for node, state in relays.items() if state["suspected_at"] is not None and state["suspected_at"] <= end}
            same(security["coverage"], sum(state["valid_windows"] > 0 for state in relays.values()) / sensor_count)
        else:
            predicted = set()
        assert row.unique_suspected_by_cutoff == len(predicted)
        assert row.unique_isolated_by_cutoff == (sum(state["isolated_at"] is not None for state in detector["relays"].values()) if detector else 0)
        expected = classification_metrics(set(states), set(manifest["attack"]["attacker_ids"]), predicted)
        for key in ("TP", "FP", "TN", "FN", "tpr", "fpr", "precision", "f1"):
            same(security[key], expected[key], "cutoff security " + key)
            same(getattr(row, key), security[key], "security CSV " + key)
        for node, delay in security["attacker_delays"].items():
            for kind in ("detection", "isolation"):
                value = delay[kind + "_delay_s"]
                assert delay[kind + "_censored"] == (value is None)
                assert value is None or 0 <= value <= end
                if value is None:
                    assert delay[kind + "_na_reason"]
        deaths = sorted(state["died_at"] for state in states.values() if state["died_at"] is not None)
        assert all(0 <= time <= end for time in deaths)
        assert len(deaths) == sensor_count - row.alive_sensors
        for name, rank in (("FND", 1), ("HND", (sensor_count + 1) // 2), ("LND", sensor_count)):
            milestone = summary["lifetime"][name]
            derived = deaths[rank - 1] if len(deaths) >= rank else None
            same(milestone["time_s"], derived, "milestone from sensor deaths")
            assert milestone["censored"] == (derived is None)
            if derived is None:
                assert milestone["received_payload_bits"] is None
            same(getattr(row, name + "_s"), derived)
            same(getattr(row, name + "_restricted_s"), 10000 if derived is None else derived)
        frame = read_numeric_csv(record["directory"] / "timeseries.csv")
        endpoint = frame.iloc[-1]
        log_end = manifest.get("log_end_s", end)
        assert endpoint.time_s == summary.get("log_end_s", end) == log_end <= end
        expected_grid = list(range(0, int(log_end) + 1, spec["sample_interval_s"]))
        if expected_grid[-1] != log_end:
            assert log_end == end and summary["stop_reason"] == "LND"
            expected_grid.append(log_end)
        assert list(frame["time_s"]) == expected_grid
        if "log_end_s" in manifest:
            terminals = frame.alive_sensors.eq(0) | frame.physical_reachable_alive.eq(0)
            assert not terminals.iloc[:-1].any()
            assert log_end == end or terminals.iloc[-1]
        assert (frame["generated"] == frame["delivered"] + frame["dropped"] + frame["in_flight"]).all()
        if log_end == end:
            for ts_key, performance_key in (("generated", "generated"), ("delivered", "delivered"), ("dropped", "dropped"), ("in_flight", "pending_in_flight"), ("received_payload_bits", "received_payload_bits"), ("remaining_energy_j", "remaining_energy_j")):
                same(endpoint[ts_key], perf[performance_key], "endpoint " + ts_key)
        family = (spec["case"]["rho"], spec["case"]["p_drop"], spec["case"]["placement"], spec["seed"])
        for previous in all_pair_groups.get(family, []):
            assert previous["manifest"]["topology_hash"] == manifest["topology_hash"]
            assert previous["manifest"]["attack"]["attacker_ids"] == manifest["attack"]["attacker_ids"]
            assert previous["job"]["pairing_hash"] == spec["pairing_hash"]
        all_pair_groups.setdefault(family, []).append(record)
    for seed in SEEDS:
        groups = [record for record in records if record["job"]["seed"] == seed]
        assert len({record["manifest"]["topology_hash"] for record in groups}) == 1
        treatments = [record for record in groups if record["job"]["case"]["rho"] == .05 and record["job"]["case"]["p_drop"] == .5]
        assert len({record["manifest"]["attack"]["attacker_count"] for record in treatments}) == 1
        passive = runs[(runs.scenario == "SF2") & (runs.seed == seed)].iloc[0]
        control = runs[(runs.scenario == "EMHR_SF") & (runs.seed == seed) & (runs.rho == .05) & (runs.p_drop == .5) & (runs.placement == "random")].iloc[0]
        for metric in ("pdr", "throughput_bps", "goodput_bps", "energy_per_payload_bit_j", "mean_latency_s", "mean_actual_hops", "consumed_energy_j", "remaining_energy_j", "delivered", "dropped", "pending_in_flight"):
            same(passive[metric], control[metric], "passive SF2 must preserve physical traffic/radio in current model")
    for aggregate in aggregates.itertuples():
        group = runs[runs["case_id"] == aggregate.case_id][aggregate.metric].dropna().to_numpy(dtype=float)
        assert aggregate.n_used == len(group) and aggregate.n_expected == 30 and aggregate.n_missing == 30 - len(group)
        same(aggregate.mean, np.mean(group) if len(group) else None, "aggregate mean")
        std = np.std(group, ddof=1) if len(group) > 1 else None
        same(aggregate.sample_std_ddof1, std, "sample std ddof1")
        half = stats.t.ppf(.975, len(group) - 1) * std / sqrt(len(group)) if std is not None else None
        same(aggregate.ci95_low, np.mean(group) - half if half is not None else None, "CI95 low")
        same(aggregate.ci95_high, np.mean(group) + half if half is not None else None, "CI95 high")
    for row in lifetime_table.itertuples():
        group = lifetimes[(lifetimes.case_id == row.case_id) & (lifetimes.milestone == row.milestone)]
        assert row.n_runs == len(group) == 30
        assert row.n_observed == group["observed"].sum()
        assert row.censored + row.n_observed == row.n_runs
        assert group.loc[group["censored"], "time_s"].isna().all()
        assert group.loc[group["censored"], "received_payload_bits"].isna().all()
    for pair in pairs.itertuples():
        a = runs[(runs.scenario == pair.first) & (runs.rho == pair.rho) & (runs.p_drop == pair.p_drop) & (runs.placement == pair.placement)].set_index("seed")[pair.metric]
        b = runs[(runs.scenario == pair.second) & (runs.rho == pair.rho) & (runs.p_drop == pair.p_drop) & (runs.placement == pair.placement)].set_index("seed")[pair.metric]
        matched = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
        difference = matched.a - matched.b
        assert pair.n_matched == len(matched)
        same(pair.mean_difference_first_minus_second, difference.mean() if len(difference) else None)
        half = stats.t.ppf(.975, len(difference) - 1) * difference.std(ddof=1) / sqrt(len(difference)) if len(difference) > 1 else None
        same(pair.difference_ci95_low, difference.mean() - half if half is not None else None)
        same(pair.difference_ci95_high, difference.mean() + half if half is not None else None)
        assert pair.holm_family_size == len(pairs)
        rounded = np.round(difference.to_numpy(), 12)
        expected_t = expected_w = None
        if len(rounded) > 1:
            if np.all(rounded == 0):
                expected_t = expected_w = 1.0
            else:
                if np.std(rounded, ddof=1) > 0:
                    expected_t = stats.ttest_rel(matched.a, matched.b).pvalue
                expected_w = stats.wilcoxon(rounded, zero_method="pratt", method="auto").pvalue
        same(pair.paired_t_p, expected_t, "paired t p-value")
        same(pair.wilcoxon_p, expected_w, "Wilcoxon-Pratt p-value")
    for test in ("paired_t_p", "wilcoxon_p"):
        values = [None if pd.isna(value) else value for value in pairs[test]]
        for actual, expected in zip(pairs[test + "_holm"], holm_adjust(values)):
            same(actual, expected)
    figures = read_json(directory / "bieu_do/figure_manifest.json")
    visibility_audit = read_numeric_csv(directory / "bar_visibility_audit.csv")
    labeled_bars = plan["base_configuration"].get("topology_model") == "na"
    assert len(figures) == 10
    total_bars = 0
    for figure in figures:
        for key, hash_key in (("figure", "png_sha256"), ("vector", "svg_sha256"), ("data_csv", "data_sha256")):
            assert file_hash(directory / "bieu_do" / figure[key]) == figure[hash_key]
        checks = figure["layout_checks"]
        assert checks["legend_outside_all_axes"] and checks["labels_above_bars"] and checks["numeric_labels_do_not_overlap"] and checks["all_text_inside_figure"]
        assert checks["configuration_subtitle_count"] == checks["footnote_count"] == checks["error_bar_count"] == 0
        svg = ET.parse(directory / "bieu_do" / figure["vector"])
        texts = [element.text or "" for element in svg.iter() if element.tag.endswith("}text")]
        joined = " ".join(texts)
        for forbidden in ("Số phía trên cột", "CI 95%", "seed/cấu hình", "Cấu hình tấn công:", "phá hòa", "Chưa quan sát mốc", "100.000"):
            assert forbidden not in joined, (figure["figure"], forbidden)
        data = read_numeric_csv(directory / "bieu_do" / figure["data_csv"])
        if labeled_bars:
            assert figure["bars"] and not figure["lines"] and not figure["point_labels"]
        if "metric" in data.columns and "case_id" in data.columns:
            for row in data.itertuples():
                source = aggregates[(aggregates.case_id == row.case_id) & (aggregates.metric == row.metric)].iloc[0]
                same(row.mean, source["mean"], "figure data CSV")
        for bar in figure["bars"]:
            assert bar["label"] == number_label(bar["value_in_axis_units"], bar["ylabel"])
            assert bar["label"] in texts
            value = bar["value_in_axis_units"]
            assert np.isfinite(value) and value >= 0
            assert bar["data_state"] == ("positive" if value > 0 else "zero")
            assert bar["zero_marker_shown"] == (value == 0)
            if value > 0:
                assert bar["rendered_height_pixels"] >= 2 or bar["tiny_positive_marker_shown"]
            if value == 0:
                assert any(element.get("id", "").startswith("true_zero_marker_") for element in svg.iter())
            for source in bar["sources"]:
                if "time_s" in source:
                    matching = data[(data.scenario == source["scenario"]) & (data.metric == source["metric"])
                                    & (data.time_s == source["time_s"])]
                    assert len(matching) == 1
                    origin = matching.iloc[0]
                    assert origin["plotted"]
                elif "value" in data.columns:
                    group = data[(data.scenario == source["scenario"]) & (data.metric == source["metric"])]
                    origin = {"n_used": group.value.count(), "mean": group.value.mean()}
                else:
                    origin = aggregates[(aggregates.case_id == source["case_id"]) & (aggregates.metric == source["metric"])].iloc[0]
                    if source["n_used"] != 30:
                        assert f"n={source['n_used']}" in texts
                assert source["n_used"] == origin["n_used"] and 0 < source["n_used"] <= 30
                same(source["mean"], origin["mean"])
                same(value, origin["mean"] * source["unit_factor"], "bar source provenance")
            total_bars += 1
        if "case_id" in data.columns:
            expected_values = sorted(float(row.mean) * METRICS[row.metric][2] for row in data.itertuples() if not pd.isna(row.mean))
            actual_values = sorted(bar["value_in_axis_units"] for bar in figure["bars"])
            if actual_values:
                assert len(expected_values) == len(actual_values)
                for actual, expected in zip(actual_values, expected_values):
                    same(actual, expected, "bar height from CSV")
        if "time_s" in data.columns:
            assert data.time_s.min() == 0 and data.time_s.max() <= 10000
            if labeled_bars:
                assert data.plotted.eq(data.time_s.isin(PLOT_TIMES_S)).all()
                assert int(data.plotted.sum()) == len(figure["bars"])
                plotted_keys = set(data[data.plotted][["scenario", "metric", "time_s"]].itertuples(index=False, name=None))
                source_keys = {
                    (source["scenario"], source["metric"], source["time_s"])
                    for bar in figure["bars"] for source in bar["sources"]
                }
                assert source_keys == plotted_keys
        for line in figure["lines"]:
            metric, scenario = line["series"].split("|")
            group = data[(data.metric == metric) & (data.scenario == scenario)]
            if "time_s" in data.columns:
                group = group.sort_values("time_s")
                assert line["x"] == group.time_s.tolist()
                factor = 1
            else:
                variable = "rho" if "04_" in figure["figure"] else "p_drop"
                group = group.sort_values(variable)
                assert line["x"] == list(range(3))
                factor = METRICS[metric][2]
            for actual, expected in zip(line["y"], group["mean"] * factor):
                same(actual, expected, "line point from CSV")
            assert len(line["y"]) == len(group)
        for point in figure["point_labels"]:
            assert point["label"] == number_label(point["y"], point["ylabel"])
            assert point["label"] in texts
            line = next(line for line in figure["lines"] if line["series"] == point["series"] and line["axis"] == point["axis"])
            same(point["y"], line["y"][line["x"].index(point["x"])], "point label from line data")
        if "value" in data.columns:
            for source in data.itertuples():
                original = runs[(runs.scenario == source.scenario) & (runs.seed == source.seed) & (runs.placement == "random") & (runs.rho.isin([0, .05])) & (runs.p_drop.isin([0, .5]))].iloc[0]
                same(source.value, original[source.metric], "packet component CSV")
            if labeled_bars:
                assert len(figure["bars"]) == len(PACKET_CATEGORIES) * data.scenario.nunique()
                assert np.allclose(data.groupby(["scenario", "seed"]).value.sum(), 1)
            else:
                assert len(figure["bars"]) == 6
                for bar in figure["bars"]:
                    same(bar["value_in_axis_units"], 100, "stacked packet total")
    assert len(visibility_audit) == total_bars
    assert visibility_audit.data_state.isin(["positive", "zero"]).all()
    zero_count = int((visibility_audit.data_state == "zero").sum())
    assert visibility_audit.loc[visibility_audit.data_state == "zero", "zero_marker_shown"].all()
    parser = Links()
    parser.feed((directory / "BAO_CAO.html").read_text(encoding="utf-8"))
    for link in parser.links:
        if link in ("verification.json", "du_lieu_10000s.zip") and not check_package:
            continue
        assert (directory / link.split("#")[0]).exists(), "broken link: " + link
    prefix = compare_old_prefix(records, directory)
    package_files = 0
    test_evidence = None
    if (directory / "test_results.xml").exists():
        suites = ET.parse(directory / "test_results.xml").getroot()
        test_evidence = {"tests": sum(int(suite.get("tests", 0)) for suite in suites.iter("testsuite")), "failures": sum(int(suite.get("failures", 0)) for suite in suites.iter("testsuite")), "errors": sum(int(suite.get("errors", 0)) for suite in suites.iter("testsuite"))}
        assert test_evidence["tests"] >= 8 and test_evidence["failures"] == test_evidence["errors"] == 0
    if check_package:
        inventory = read_json(directory / "package_inventory.json")
        with zipfile.ZipFile(directory / "du_lieu_10000s.zip") as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == len(inventory) + 1
            assert len(set(archive.namelist())) == len(archive.namelist())
            for item in inventory:
                content = archive.read(item["path"])
                assert len(content) == item["size"] and hashlib.sha256(content).hexdigest() == item["sha256"]
            for record in records:
                prefix_path = "raw/" + record["job"]["run_id"] + "/"
                complete = read_json(record["directory"] / "complete.json")
                for name, digest in complete["files"].items():
                    assert hashlib.sha256(archive.read(prefix_path + name)).hexdigest() == digest
            package_files = len(inventory)
    return {"status": "PASS", "verification_phase": "complete_package" if check_package else "before_zip_creation", "verified_at_utc": datetime.now(timezone.utc).isoformat(), "completed": 480, "failed": 0, "pending": 0, "cases": 16, "seeds_per_case": 30, "horizon_s": 10000, "rounds": 1000, "freeze_verified": freeze["verified"], "source_sha256": plan["source_fingerprint"]["sha256"], "run_hashes_verified": 480, "packet_energy_conservation": True, "event_cutoff_inclusive_no_drain": True, "security_recomputed_at_cutoff": True, "milestones_recomputed_from_sensor_deaths": True, "all_statistics_recomputed": True, "paired_topology_and_attacker_ids": True, "lifetime_NA_censoring_preserved": True, "figures": 10, "bar_labels_verified": total_bars, "positive_bars": total_bars - zero_count, "true_zero_values_marked": zero_count, "main_chart_missing_values": 0, "relay_snapshot_rows_checked": len(relay_frame), "effective_protocol_checked": True, "figure_layout_checks_passed": True, "HTML_links_valid": True, "old_prefix_crosscheck": prefix, "package_verified": check_package, "package_file_count": package_files, "test_evidence": test_evidence, "zip_sha256": file_hash(directory / "du_lieu_10000s.zip") if check_package else None}


def main():
    parser = ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    args = parser.parse_args()
    result = verify_report(load_project(args.project), args.batch.resolve(), args.report.resolve())
    (args.report / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
