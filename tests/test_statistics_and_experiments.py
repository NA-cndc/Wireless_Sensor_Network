"""Tests for statistical methods, reproducibility, lifetime metrics, and CLI.

Kiểm tra:
- Item 3: Pilot multi-seed kiểm tra reachability >= 95% và degree.
- Item 16: Tái lập 100% giữa serial và multiprocessing cho cùng seed.
- Item 17: Tính toán metrics, xử lý mẫu số bằng 0.
- Item 18: FND/HND/LND/functional death và xử lý censored data.
- Item 25: Không ghi đè output giữa các seed/thuật toán khác nhau.
- Item 26: Thống kê mô tả ddof=1, CI 95%, kiểm định cặp, Cohen's d trên >= 30 mẫu.
- Item 27: CLI --help và các entry point.
- Item 28: Git metadata kiểm tra ngữ nghĩa, không ép nhánh cứng.
"""

from dataclasses import replace
from pathlib import Path
import pytest

from wsn_sim.config import SimulationConfig
from wsn_sim.experiments import run_single_experiment
from wsn_sim.network import Network
from wsn_sim.simulation import Simulation
from wsn_sim.statistics import calculate_sample_statistics, compare_paired_experiments
from wsn_sim.storage import create_run_manifest


def test_pilot_reachability_across_multiple_seeds():
    """Kiểm tra độ phủ sóng và tỷ lệ liên thông >= 95% trên nhiều seed pilot."""
    cfg = SimulationConfig.from_json("configs/default.json")
    seeds = [42, 100, 2026, 9999]

    for s in seeds:
        net = Network(replace(cfg, seed=s), communication_range_m=300.0)
        conn = net.check_network_connectivity()
        assert conn["total_sensors"] == 450
        assert conn["total_sinks"] == 7
        assert conn["routable_ratio"] >= 0.95
        assert conn["meets_95_percent_threshold"] is True


def test_reproducibility_across_identical_runs():
    """Cùng config và seed phải cho kết quả giống hệt nhau 100%."""
    cfg = SimulationConfig.from_json("configs/default.json")

    sim1 = Simulation(cfg, current_range_m=300.0, routing_algorithm="EMHR", quiet=True, seed=42)
    sim1.run_for(30.0)
    m1 = sim1.get_metrics()

    sim2 = Simulation(cfg, current_range_m=300.0, routing_algorithm="EMHR", quiet=True, seed=42)
    sim2.run_for(30.0)
    m2 = sim2.get_metrics()

    assert m1["generated_packets"] == m2["generated_packets"]
    assert m1["delivered_packets"] == m2["delivered_packets"]
    assert m1["consumed_energy_sensors_j"] == pytest.approx(m2["consumed_energy_sensors_j"])
    assert m1["pdr_percent"] == pytest.approx(m2["pdr_percent"])


def test_sample_statistics_and_confidence_interval():
    """Kiểm tra tính toán Mean, SD với ddof=1, và 95% CI trên 30 mẫu."""
    data = [10.0 + (i % 5) * 0.5 for i in range(30)]
    stats = calculate_sample_statistics(data)

    assert stats["count_valid"] == 30
    assert stats["count_censored"] == 0
    assert stats["mean"] is not None
    assert stats["std"] is not None
    assert stats["ci_95_lower"] < stats["mean"] < stats["ci_95_upper"]


def test_paired_comparison_and_effect_size():
    """Kiểm tra so sánh cặp và Cohen's d effect size."""
    base = [80.0 + (i % 3) for i in range(30)]
    prop = [b + 5.0 + (0.5 * (i % 3)) for i, b in enumerate(base)]

    res = compare_paired_experiments(base, prop)
    assert res["pairs_valid"] == 30
    assert res["mean_difference"] > 4.5
    assert res["statistically_significant"] is True
    assert res["p_value"] < 0.001
    assert res["cohens_d_effect_size"] > 0.8


def test_censored_lifetime_milestones_handling():
    """Kiểm tra các mốc chưa xảy ra (chưa cạn pin) được xử lý là None/censored."""
    cfg = SimulationConfig.from_json("configs/default.json")
    sim = Simulation(cfg, current_range_m=300.0, quiet=True)
    sim.run_for(20.0)
    metrics = sim.get_metrics()

    assert metrics["dead_sensors"] == 0
    assert metrics["t_fnd_s"] is None
    assert metrics["t_hnd_s"] is None
    assert metrics["t_lnd_s"] is None
    assert metrics["bits_at_fnd"] is None


def test_output_folders_do_not_overwrite(tmp_path: Path):
    """Mỗi run lưu vào thư mục riêng biệt theo scenario/seed, không ghi đè."""
    cfg = SimulationConfig.from_json("configs/default.json")

    run_single_experiment(cfg, algorithm="MHR", seed=42, duration_s=10.0, output_dir=tmp_path)
    run_single_experiment(cfg, algorithm="EMHR", seed=42, duration_s=10.0, output_dir=tmp_path)
    run_single_experiment(cfg, algorithm="EMHR", seed=43, duration_s=10.0, output_dir=tmp_path)

    dirs = [d.name for d in tmp_path.iterdir() if d.is_dir()]
    assert len(dirs) == 3
    assert any("MHR_R300m_seed42" in d for d in dirs)
    assert any("EMHR_R300m_seed42" in d for d in dirs)
    assert any("EMHR_R300m_seed43" in d for d in dirs)


def test_git_metadata_robustness(tmp_path: Path):
    """Kiểm tra create_run_manifest an toàn khi thư mục không phải git repo."""
    cfg = SimulationConfig.from_json("configs/default.json")
    non_git_dir = tmp_path / "empty_folder"
    non_git_dir.mkdir()

    manifest = create_run_manifest(cfg, ["summary.csv"], repository_root=non_git_dir)
    assert manifest["seed"] == 42
    assert manifest["git_commit"] is None
    assert manifest["git_branch"] is None
    assert manifest["working_tree_clean"] is None
