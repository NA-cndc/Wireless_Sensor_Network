from collections import defaultdict
import json
from math import isclose
from pathlib import Path
import pandas as pd
from study import read_json


EXTRA_METRICS = [
    "received_payload_bits", "generated_payload_bits", "offered_payload_bps",
    "jain_forwarding_fairness", "consumed_energy_j", "remaining_energy_j",
    "functional_network_death_restricted_s", "functional_routing_network_death_restricted_s",
    "alive_sensors", "alive_fraction", "FND_observed_fraction",
    "generated", "delivered", "dropped", "pending_in_flight", "received_wire_bits",
    "TP", "FP", "TN", "FN",
    "physical_reachable_alive", "routing_reachable_alive",
    "detector_isolation_events", "security_reroute_decision_count",
    "unique_suspected_by_cutoff", "unique_isolated_by_cutoff",
]

REQUIRED_METRICS = [
    "pdr", "throughput_bps", "goodput_bps", "energy_per_payload_bit_j",
    "mean_latency_s", "mean_actual_hops", "FND_restricted_s", "HND_restricted_s", "LND_restricted_s",
]

def export_csv(rows, path):
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")

def enrich(rows, records, directory):
    from wsn_sim.experiment_execution import file_hash
    indexed = {record["job"]["run_id"]: record for record in records}
    lifetimes, delays, integrity, sources, relay_rows = [], [], [], [], []
    loss_types = ["unreachable", "natural_link_loss", "selective_forwarding", "energy_depletion"]
    for row in rows:
        record = indexed[row["run_id"]]
        performance = record["summary"]["performance"]
        summary, spec = record["summary"], record["job"]
        configuration = spec["configuration"]
        states = read_json(record["directory"] / "final_sensor_states.json")
        counts = {name: performance[name] for name in ("generated", "delivered", "dropped", "pending_in_flight")}
        row.update(counts)
        row["received_payload_bits"] = performance["received_payload_bits"]
        row["generated_payload_bits"] = performance["generated"] * configuration["packet_size_bytes"] * 8
        row["offered_payload_bps"] = row["generated_payload_bits"] / summary["time_s"]
        forwards = [value["forwarded"] for value in states.values()]
        denominator = len(forwards) * sum(value * value for value in forwards)
        row["jain_forwarding_fairness"] = sum(forwards) ** 2 / denominator if denominator else None
        row["consumed_energy_j"] = performance["consumed_since_start_j"]
        row["remaining_energy_j"] = performance["remaining_energy_j"]
        row["alive_sensors"] = sum(state["alive"] for state in states.values())
        row["alive_fraction"] = row["alive_sensors"] / configuration["num_sensors"]
        row["dead_sensors"] = configuration["num_sensors"] - row["alive_sensors"]
        row["received_wire_bits"] = performance["received_wire_bits"]
        row["FND_observed_fraction"] = int(not summary["lifetime"]["FND"]["censored"])
        row["evaluation_time_s"] = summary["security"]["evaluation_time_s"]
        row["physical_reachable_alive"] = summary["reachability"]["physical_reachable_alive"]
        row["routing_reachable_alive"] = summary["reachability"]["routing_reachable_alive"]
        row["rounds"] = summary["rounds"]
        row["scope"] = spec["scope"]
        row["config_sha256"] = __import__("wsn_sim.calibration", fromlist=["json_digest"]).json_digest(configuration)
        row["na_reasons"] = json.dumps({"performance": performance.get("na_reasons", {}), "security": summary["security"].get("na_reasons", {}), "unmodeled": "MAC_ACK_idle_monitoring_control_queue_not_simulated"}, ensure_ascii=False)
        detector = summary["detector"]
        row["detector_enabled"] = detector is not None
        row["routing_avoidance_enabled"] = configuration["routing_algorithm"] == "S_EMHR"
        row["detector_isolation_events"] = row["isolation_events"]
        row["security_reroute_decision_count"] = performance["reroute_decision_categories"].get("security", 0)
        relays = detector["relays"] if detector else {}
        row["unique_suspected_by_cutoff"] = sum(state["suspected_at"] is not None and state["suspected_at"] <= summary["time_s"] for state in relays.values())
        row["unique_isolated_by_cutoff"] = sum(state["isolated_at"] is not None and state["isolated_at"] <= summary["time_s"] for state in relays.values())
        attackers = set(record["manifest"]["attack"]["attacker_ids"])
        for node, state in relays.items():
            received = state["received_transit"]
            relay_rows.append({**{key: row[key] for key in ("case_id", "scenario", "rho", "p_drop", "placement", "seed", "run_id")}, "node_id": node, "evaluation_time_s": summary["time_s"], "ground_truth_attacker_for_evaluation_only": node in attackers, "received_transit_total": received, "forwarded_total": state["forwarded"], "failed_timeout_total": state["failed_timeout"], "pending_total": state["pending"], "forwarding_ratio_cumulative": state["forwarded"] / received if received else None, "cumulative_ratio_na_reason": "no_transit_observations" if not received else None, "ratio_scope": "cumulative_diagnostic_not_window_ratio_used_by_EWMA", "trust_at_cutoff": state["trust"], "valid_windows": state["valid_windows"], "suspected_current": state["suspected"], "ever_suspected_by_cutoff": state["suspected_at"] is not None, "first_suspected_s": state["suspected_at"], "first_isolated_s": state["isolated_at"], "isolated_until_s": state["isolated_until"], "routing_avoidance_enabled": row["routing_avoidance_enabled"]})
        row["delivered_fraction"] = counts["delivered"] / counts["generated"]
        row["in_flight_fraction"] = counts["pending_in_flight"] / counts["generated"]
        for kind in loss_types:
            row[kind + "_count"] = performance["drop_reasons"].get(kind, 0)
            row[kind + "_fraction"] = row[kind + "_count"] / counts["generated"]
        row["queue_drop_count"] = None
        row["monitoring_energy_j"] = performance["monitoring_energy_j"]
        row["monitoring_time_s"] = performance["monitoring_time_s"]
        row["control_packets"] = performance["control_packets"]
        for kind, milestone in summary["lifetime"].items():
            lifetime_row = {
                **{name: row[name] for name in ("case_id", "scenario", "rho", "p_drop", "placement", "seed", "run_id")},
                "milestone": kind, "time_s": milestone["time_s"], "observed": not milestone["censored"],
                "censored": milestone["censored"], "received_payload_bits": milestone["received_payload_bits"],
                "observation_end_s": summary["time_s"], "administrative_horizon_s": row["requested_horizon_s"],
                "censor_reason": "milestone_not_reached_by_10000s" if milestone["censored"] else None,
            }
            lifetimes.append(lifetime_row)
            if kind.startswith("functional_"):
                row[kind + "_s"] = milestone["time_s"]
                row[kind + "_censored"] = milestone["censored"]
                row[kind + "_restricted_s"] = milestone["time_s"] if milestone["time_s"] is not None else row["requested_horizon_s"] if summary["time_s"] == row["requested_horizon_s"] else None
        for node, values in summary["security"]["attacker_delays"].items():
            delays.append({**{name: row[name] for name in ("case_id", "scenario", "rho", "p_drop", "placement", "seed", "run_id")}, "attacker_id": node, **values})
        generated_check = counts["generated"] == sum(value["generated"] for value in states.values())
        remaining_check = isclose(row["remaining_energy_j"], sum(value["energy_j"] for value in states.values()), abs_tol=1e-8)
        packets_check = counts["generated"] == counts["delivered"] + counts["dropped"] + counts["pending_in_flight"]
        energy_check = performance["energy_conservation_ok"]
        population_check = sum(summary["security"][name] for name in ("TP", "FP", "TN", "FN")) == configuration["num_sensors"]
        labels_check = summary["security"]["TP"] + summary["security"]["FN"] == row["actual_attacker_count"]
        reasons_check = sum(performance["drop_reasons"].values()) == counts["dropped"]
        detector = summary["detector"]
        detector_check = detector is None or (detector["conservation_ok"] and detector["input_conservation_ok"])
        checks = [generated_check, remaining_check, packets_check, energy_check, population_check, labels_check, reasons_check, detector_check]
        if not all(checks):
            raise ValueError(f"integrity failure {row['run_id']}: {checks}")
        integrity.append({"run_id": row["run_id"], "case_id": row["case_id"], "seed": row["seed"], "packet_conservation": packets_check, "energy_conservation": energy_check, "sensor_counters_match": generated_check, "sensor_energy_match": remaining_check, "security_population_match": population_check and labels_check, "drop_reasons_match": reasons_check, "detector_conservation": detector_check})
        sources.append({"run_id": row["run_id"], "directory": str(record["directory"]), "files": {name: file_hash(record["directory"] / name) for name in ("summary.json", "run_manifest.json", "spec.json", "complete.json", "final_sensor_states.json", "lifetime.json", "timeseries.csv")}})
    export_csv(rows, directory / "runs.csv")
    export_csv(lifetimes, directory / "lifetime_per_seed.csv")
    export_csv(delays, directory / "attacker_delays.csv")
    export_csv(integrity, directory / "integrity_per_run.csv")
    export_csv(relay_rows, directory / "relay_security_per_seed.csv")
    (directory / "input_manifest.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return lifetimes, sources

def extend_aggregates(plan, rows, aggregates, lifetimes, directory):
    from wsn_sim.experiment_statistics import sample_summary
    expected = len(plan["seeds"])
    for case in plan["cases"]:
        group = [row for row in rows if row["case_id"] == case["case_id"]]
        for metric in EXTRA_METRICS:
            aggregates.append({**case, "metric": metric, "estimand": "mean_min_time_administrative_horizon" if metric.endswith("_restricted_s") else "mean_per_independent_seed", "n_not_completed": expected - len(group), "n_undefined_among_completed": sum(row[metric] is None for row in group), **sample_summary([row[metric] for row in group], expected)})
    lifetime_table = []
    for case in plan["cases"]:
        for name in ("FND", "HND", "LND", "functional_network_death", "functional_routing_network_death"):
            group = [row for row in lifetimes if row["case_id"] == case["case_id"] and row["milestone"] == name]
            observed = [row for row in group if row["observed"]]
            lifetime_table.append({**case, "milestone": name, "n_runs": len(group), "n_observed": len(observed), "censored": sum(row["censored"] for row in group), "horizon_s": plan["base_configuration"]["max_rounds"] * plan["base_configuration"]["packet_interval_s"], "conditional_time_mean_s": sample_summary([row["time_s"] for row in observed], len(group))["mean"], "conditional_payload_mean_bits": sample_summary([row["received_payload_bits"] for row in observed], len(group))["mean"], "conditional_estimand": "only_runs_with_observed_milestone_not_comparable_if_differential_censoring"})
    export_csv(aggregates, directory / "aggregate.csv")
    export_csv(lifetime_table, directory / "bang_lifetime.csv")
    return lifetime_table

def extend_comparisons(plan, rows, comparisons, directory):
    from wsn_sim.experiment_statistics import holm_adjust, paired_comparison, sample_summary
    by_case = defaultdict(dict)
    for row in rows:
        by_case[row["case_id"]][row["seed"]] = row
    pairs = [("EMHR", "MHR", 0, 0, "random"), ("SF3", "MHR_SF", 0.05, 0.5, "random")]
    families = sorted({(row["rho"], row["p_drop"], row["placement"]) for row in rows if row["scenario"] == "SF3"})
    pairs.extend(("SF3", "EMHR_SF", *family) for family in families)
    existing = {(row["first"], row["second"], row["rho"], row["p_drop"], row["placement"], row["metric"]) for row in comparisons}
    for first, second, rho, probability, placement in pairs:
        a = by_case[f"{first}_r{rho:g}_d{probability:g}_{placement}"]
        b = by_case[f"{second}_r{rho:g}_d{probability:g}_{placement}"]
        for seed in a.keys() & b.keys():
            if a[seed]["pairing_hash"] != b[seed]["pairing_hash"] or a[seed]["topology_hash"] != b[seed]["topology_hash"]:
                raise ValueError("paired topology or exogenous configuration differs")
        for metric in REQUIRED_METRICS + EXTRA_METRICS:
            key = (first, second, rho, probability, placement, metric)
            if key not in existing:
                comparisons.append({"first": first, "second": second, "rho": rho, "p_drop": probability, "placement": placement, "metric": metric, **paired_comparison({seed: row[metric] for seed, row in a.items()}, {seed: row[metric] for seed, row in b.items()}, len(plan["seeds"]))})
                existing.add(key)
    for comparison in comparisons:
        a = by_case[f"{comparison['first']}_r{comparison['rho']:g}_d{comparison['p_drop']:g}_{comparison['placement']}"]
        b = by_case[f"{comparison['second']}_r{comparison['rho']:g}_d{comparison['p_drop']:g}_{comparison['placement']}"]
        metric = comparison["metric"]
        matched = [seed for seed in a.keys() & b.keys() if a[seed][metric] is not None and b[seed][metric] is not None]
        values_a, values_b = [a[seed][metric] for seed in matched], [b[seed][metric] for seed in matched]
        base_mean = sum(values_b) / len(values_b) if values_b else None
        difference = comparison["mean_difference_first_minus_second"]
        comparison["percent_change_vs_second"] = difference / base_mean * 100 if difference is not None and base_mean else None
        difference_ci = sample_summary([a[seed][metric] - b[seed][metric] for seed in matched], len(plan["seeds"]))
        comparison["difference_ci95_low"] = difference_ci["ci95_low"]
        comparison["difference_ci95_high"] = difference_ci["ci95_high"]
        comparison["inferentially_complete_30_pairs"] = comparison["n_matched"] == len(plan["seeds"]) and comparison["n_matched"] >= 30
    for test in ("paired_t_p", "wilcoxon_p"):
        for comparison, adjusted in zip(comparisons, holm_adjust([row[test] for row in comparisons])):
            comparison[test + "_holm"] = adjusted
            comparison["holm_family_size"] = len(comparisons)
    export_csv(comparisons, directory / "paired_comparisons.csv")
    return comparisons

def formatted(value, decimals=2):
    if value is None or pd.isna(value):
        return "NA"
    return f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")

def formatted_p(value):
    if value is None or pd.isna(value):
        return "NA"
    return "<0,00001" if value < 0.00001 else formatted(value, 5)

def metric_value(aggregates, case_id, metric):
    return next((row for row in aggregates if row["case_id"] == case_id and row["metric"] == metric), None)
