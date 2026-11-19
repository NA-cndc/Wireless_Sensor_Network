import argparse
import json
import sys
import multiprocessing
from dataclasses import replace
from hashlib import sha256
from math import ceil, isfinite
from pathlib import Path

# Cấu hình UTF-8 cho console trên Windows tránh lỗi encode
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import matplotlib.pyplot as plt

from analysis.foundation.config import SimulationConfig
from analysis.foundation.network import Network
from analysis.foundation.storage import save_json, scenario_stem
from analysis.foundation.visualization import save_topology_plot
from analysis.foundation import runner as wsn_main


def generate_topologies(ranges, config_data, fig_dir):
    print("\n[1] ĐANG VẼ 3 BẢN ĐỒ TOPOLOGY (VECTOR PDF)...")
    cfg = SimulationConfig.from_dict(config_data)
    for r in ranges:
        network = Network(cfg, communication_range_m=r)
        out_path = fig_dir / f"topology_R{int(r)}m.pdf"
        save_topology_plot(network, out_path)
        print(f" -> Đã lưu: {out_path}")


def _validate_sources(csv_dir, config, scenarios):
    sources = []
    for radius, algo in scenarios:
        stem = scenario_stem(algo, radius)
        series = csv_dir / f"{stem}.csv"
        manifest = csv_dir / f"{stem}.json"
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        if (metadata["configuration"] != config.to_dict() or not series.is_file()
                or metadata["routing_algorithm"] != algo or metadata["communication_range_m"] != radius):
            raise ValueError(f"{stem} does not match the current profile. Run this script without --plots-only first.")
        metrics = metadata["metrics"]
        last_time = pd.read_csv(series, usecols=["Time_s"], float_precision="round_trip")["Time_s"].iloc[-1]
        if last_time != metrics["elapsed_s"]:
            raise ValueError(f"{stem} has an inconsistent final timestamp")
        sources.append({
            "radius_m": radius,
            "algorithm": algo,
            "timeseries": f"csv/{series.name}",
            "manifest": f"csv/{manifest.name}",
            "git_commit": metadata["git_commit"],
            "elapsed_s": metrics["elapsed_s"],
            "stop_reason": metrics["stop_reason"],
            "timeseries_sha256": sha256(series.read_bytes()).hexdigest(),
            "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
        })
    return sources


def _format(fig, ax, title, xlabel, ylabel, path, duration_s, legend_title="Thuật toán"):
    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel(f"{xlabel} · giới hạn {duration_s:g} s", fontsize=12)
    ax.set_xlim(0, duration_s)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.legend(title=legend_title, fontsize="10", loc="best")
    ax.grid(True, linestyle=":", alpha=0.6)
    fig.tight_layout()
    fig.savefig(path, format="pdf")
    plt.close(fig)


def plot_range_selection(ranges, csv_dir, fig_dir, algo="EMHR", initial_energy_j=5.0, *, duration_s):
    """
    GIAI ĐOẠN 1: Khảo sát độ nhạy bán kính truyền (R = 250m, 300m, 350m)
    trên cùng 1 thuật toán đại diện để chứng minh điểm cân bằng tối ưu.
    """
    print(f"\n[4A] VẼ BIỂU ĐỒ GIAI ĐOẠN 1: CHỌN BÁN KÍNH TỐI ƯU ({algo})...")
    plt.style.use("seaborn-v0_8-whitegrid")

    fig_life, ax_life = plt.subplots(figsize=(9, 6))
    fig_dead, ax_dead = plt.subplots(figsize=(9, 6))
    fig_energy, ax_energy = plt.subplots(figsize=(9, 6))
    fig_lat, ax_lat = plt.subplots(figsize=(9, 6))

    colors = {250.0: "tab:blue", 300.0: "tab:orange", 350.0: "tab:green"}
    actual_sensors = 450

    for r in ranges:
        csv_file = csv_dir / f"{scenario_stem(algo, r)}.csv"
        if not csv_file.exists():
            print(f" [Bỏ qua] Không tìm thấy file: {csv_file.name}")
            continue

        df_raw = pd.read_csv(csv_file)
        if df_raw.empty:
            continue

        actual_sensors = int(df_raw["Alive_Nodes"].max())
        df = df_raw

        c = colors.get(float(r), "black")
        label_name = f"R = {int(r)}m"

        r_t = 100 * df["Routable_Nodes"] / df["Alive_Nodes"].where(df["Alive_Nodes"] > 0)
        ax_life.plot(df["Time_s"], r_t, label=label_name, color=c, linestyle="-", linewidth=2.2)

        dead_nodes = actual_sensors - df["Alive_Nodes"]
        ax_dead.plot(df["Time_s"], dead_nodes, label=label_name, color=c, linestyle="-", linewidth=2.2)
        ax_energy.plot(df["Time_s"], df["Total_Energy_J"], label=label_name, color=c, linestyle="-", linewidth=2.2)
        latency = df["Avg_Latency_s"].where(df["Delivered_Packets"] > 0)
        ax_lat.plot(df["Time_s"], latency, label=label_name, color=c, linestyle="-", linewidth=2.2)

    # Đường ngưỡng và cố định trục tung từ mốc 0
    ax_life.axhline(y=50, color="red", linestyle=":", linewidth=1.5, label="Ngưỡng Lifetime (50%)")
    ax_dead.axhline(y=actual_sensors / 2, color="purple", linestyle=":", linewidth=1.5, label="Ngưỡng HND (50% chết)")

    ax_life.set_ylim(0, 105)
    ax_dead.set_ylim(0, actual_sensors + 10)
    ax_energy.set_ylim(0, (actual_sensors * initial_energy_j) + 100)
    ax_lat.set_ylim(bottom=0)

    _format(
        fig_life, ax_life,
        f"Ảnh hưởng của Bán kính truyền đến Tuổi thọ mạng ({algo})",
        "Thời gian (s)", "Tỷ lệ kết nối r(t) (%)",
        fig_dir / "stage1_range_1_lifetime.pdf",
        duration_s,
        legend_title="Bán kính truyền"
    )
    _format(
        fig_energy, ax_energy,
        f"Ảnh hưởng của Bán kính truyền đến Tiêu hao Năng lượng ({algo})",
        "Thời gian (s)", "Năng lượng còn lại (Joules)",
        fig_dir / "stage1_range_2_energy.pdf",
        duration_s,
        legend_title="Bán kính truyền"
    )
    _format(
        fig_lat, ax_lat,
        f"Ảnh hưởng của Bán kính truyền đến Độ trễ trung bình ({algo})",
        "Thời gian (s)", "Độ trễ (giây)",
        fig_dir / "stage1_range_3_latency.pdf",
        duration_s,
        legend_title="Bán kính truyền"
    )
    _format(
        fig_dead, ax_dead,
        f"Số lượng Sensor chết theo Bán kính truyền ({algo})",
        "Thời gian (s)", "Số Sensor đã chết",
        fig_dir / "stage1_range_4_dead_nodes.pdf",
        duration_s,
        legend_title="Bán kính truyền"
    )


def plot_algorithm_comparison(fixed_range, algos, csv_dir, fig_dir, initial_energy_j=5.0, *, duration_s):
    """
    GIAI ĐOẠN 2: Cố định bán kính tối ưu (VD: R=300m) để đối chứng MHR (nét đứt)
    với các thuật toán định tuyến tối ưu năng lượng (nét liền).
    """
    print(f"\n[4B] VẼ BIỂU ĐỒ GIAI ĐOẠN 2: SO SÁNH THUẬT TOÁN TẠI R={int(fixed_range)}m...")
    plt.style.use("seaborn-v0_8-whitegrid")

    fig_life, ax_life = plt.subplots(figsize=(9, 6))
    fig_dead, ax_dead = plt.subplots(figsize=(9, 6))
    fig_energy, ax_energy = plt.subplots(figsize=(9, 6))
    fig_lat, ax_lat = plt.subplots(figsize=(9, 6))

    # Bảng màu tách biệt cho nhóm thuật toán năng lượng
    energy_palette = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
    color_idx = 0
    actual_sensors = 450
    valid_dfs = []

    for algo in algos:
        csv_file = csv_dir / f"{scenario_stem(algo, fixed_range)}.csv"
        if not csv_file.exists():
            print(f" [Bỏ qua] Không tìm thấy file: {csv_file.name}")
            continue

        df_raw = pd.read_csv(csv_file)
        if df_raw.empty:
            continue

        actual_sensors = int(df_raw["Alive_Nodes"].max())
        df = df_raw
        valid_dfs.append((algo, df))

        # MHR dùng nét đứt làm mốc chuẩn đối chứng; các thuật toán năng lượng dùng nét liền
        if algo == "MHR":
            c = "dimgray"
            ls = "--"
            label_name = "MHR (Chuẩn đối chứng)"
        else:
            c = energy_palette[color_idx % len(energy_palette)]
            color_idx += 1
            ls = "-"
            label_name = algo

        r_t = 100 * df["Routable_Nodes"] / df["Alive_Nodes"].where(df["Alive_Nodes"] > 0)
        ax_life.plot(df["Time_s"], r_t, label=label_name, color=c, linestyle=ls, linewidth=2.2)

        dead_nodes = actual_sensors - df["Alive_Nodes"]
        ax_dead.plot(df["Time_s"], dead_nodes, label=label_name, color=c, linestyle=ls, linewidth=2.2)
        ax_energy.plot(df["Time_s"], df["Total_Energy_J"], label=label_name, color=c, linestyle=ls, linewidth=2.2)
        latency = df["Avg_Latency_s"].where(df["Delivered_Packets"] > 0)
        ax_lat.plot(df["Time_s"], latency, label=label_name, color=c, linestyle=ls, linewidth=2.2)

    # Đường ngưỡng và cố định trục tung từ mốc 0
    ax_life.axhline(y=50, color="red", linestyle=":", linewidth=1.5, label="Ngưỡng Lifetime (50%)")
    ax_dead.axhline(y=actual_sensors / 2, color="purple", linestyle=":", linewidth=1.5, label="Ngưỡng HND (50% chết)")

    ax_life.set_ylim(0, 105)
    ax_dead.set_ylim(0, actual_sensors + 10)
    ax_energy.set_ylim(0, (actual_sensors * initial_energy_j) + 100)
    ax_lat.set_ylim(bottom=0)

    r_label = f"R={int(fixed_range)}m"
    _format(
        fig_life, ax_life,
        f"So sánh Tỷ lệ kết nối vật lý r(t) ({r_label})",
        "Thời gian (s)", "Tỷ lệ r(t) (%)",
        fig_dir / "stage2_algo_1_lifetime.pdf",
        duration_s,
    )
    _format(
        fig_energy, ax_energy,
        f"So sánh Tiêu hao Năng lượng toàn mạng ({r_label})",
        "Thời gian (s)", "Năng lượng còn lại (Joules)",
        fig_dir / "stage2_algo_2_energy.pdf",
        duration_s,
    )
    _format(
        fig_lat, ax_lat,
        f"So sánh Độ trễ truyền tin trung bình ({r_label})",
        "Thời gian (s)", "Độ trễ (giây)",
        fig_dir / "stage2_algo_3_latency.pdf",
        duration_s,
    )
    _format(
        fig_dead, ax_dead,
        f"So sánh Số lượng Sensor chết - FND/HND ({r_label})",
        "Thời gian (s)", "Số Sensor đã chết",
        fig_dir / "stage2_algo_4_dead_nodes.pdf",
        duration_s,
    )

    # Vẽ biểu đồ phân rã gói tin tự động co giãn theo số lượng thuật toán
    if valid_dfs:
        n_algos = len(valid_dfs)
        ncols = n_algos if n_algos <= 3 else ceil(n_algos / 2)
        nrows = 1 if n_algos <= 3 else 2

        fig_pkt, axes = plt.subplots(
            nrows, ncols,
            figsize=(6.5 * ncols, 5.5 * nrows),
            sharey=True,
            squeeze=False
        )
        axes_flat = axes.flatten()

        for idx, (algo, df) in enumerate(valid_dfs):
            ax_target = axes_flat[idx]
            ax_target.plot(df["Time_s"], df["Delivered_Packets"], label="Đến đích thành công", color="tab:green", linewidth=2.5)
            ax_target.plot(df["Time_s"], df["Drop_NoRoute"], label="Rớt do Mất đường đi", color="tab:red", linewidth=2)
            ax_target.plot(df["Time_s"], df["Drop_Dead"], label="Rớt do Trạm chuyển chết", color="tab:orange", linewidth=2)
            ax_target.plot(df["Time_s"], df["Drop_Interf"], label="Rớt do Nhiễu sóng", color="tab:purple", linewidth=2)

            ax_target.set_title(f"Phân rã gói tin - {algo} ({r_label})", fontsize=13, fontweight="bold")
            ax_target.plot(df["Time_s"], df["Drop_Cutoff"], label="Kết thúc mô phỏng", color="tab:gray", linewidth=2)
            ax_target.set_xlabel(f"Thời gian (s) · giới hạn {duration_s:g} s", fontsize=11)
            ax_target.set_xlim(0, duration_s)
            ax_target.grid(True, linestyle=":", alpha=0.6)

            if idx % ncols == 0:
                ax_target.set_ylabel("Số lượng gói tin cộng dồn", fontsize=11)
            if idx == 0:
                ax_target.legend(loc="upper left", fontsize="9.5")

        # Đặt mốc 0 sau cùng để không khóa trục tung theo biểu đồ đầu tiên
        axes_flat[0].set_ylim(bottom=0)

        for idx in range(n_algos, len(axes_flat)):
            axes_flat[idx].set_visible(False)

        fig_pkt.tight_layout()
        fig_pkt.savefig(fig_dir / "stage2_algo_5_packet_breakdown.pdf", format="pdf")
        plt.close(fig_pkt)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description="Run WSN scenarios and draw the original report figures.")
    parser.add_argument("--plots-only", action="store_true", help="rebuild the figures from existing run data")
    parser.add_argument("--input", type=Path, help="timeseries directory for --plots-only")
    parser.add_argument("--source-index", type=Path, help="verify every published input against sources.json")
    parser.add_argument("--duration", type=float, help="override the configured simulation duration")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "results")
    args = parser.parse_args()
    if args.duration is not None and (not isfinite(args.duration) or args.duration <= 0):
        parser.error("--duration must be finite and greater than zero")
    if (args.input or args.source_index) and not args.plots_only:
        parser.error("--input and --source-index require --plots-only")

    results_dir = args.output.resolve()
    csv_dir = args.input.resolve() if args.input else results_dir / "csv"
    fig_dir = results_dir / "figures"
    csv_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    config = SimulationConfig.from_json(wsn_main.CONFIG_PATH)
    if args.duration is not None:
        config = replace(config, duration_s=args.duration)
    ranges = config.communication_ranges_m
    initial_energy = config.initial_energy_j
    algorithms_to_compare = wsn_main.STAGE2_ALGORITHMS

    if not args.plots_only:
        wsn_main.run_project(config, csv_dir)
    scenarios = wsn_main.project_scenarios(config)
    sources = _validate_sources(csv_dir, config, scenarios)
    source_index = {
        "configuration": config.to_dict(),
        "stage1": [source for source in sources if source["algorithm"] == "EMHR"],
        "stage2": [source for source in sources if source["radius_m"] == wsn_main.ANALYSIS_RADIUS_M],
        "topology_radii_m": list(ranges),
    }
    if args.source_index and json.loads(args.source_index.read_text(encoding="utf-8")) != source_index:
        raise ValueError("plot inputs differ from the published source index")
    generate_topologies(ranges, config.to_dict(), fig_dir)

    # Giai đoạn 1: Khảo sát 3 bán kính trên thuật toán EMHR
    plot_range_selection(
        ranges=ranges,
        csv_dir=csv_dir,
        fig_dir=fig_dir,
        algo="EMHR",
        initial_energy_j=initial_energy,
        duration_s=config.duration_s
    )

    # Giai đoạn 2: Cố định R=300m, đối chứng MHR với 4 thuật toán tối ưu năng lượng
    plot_algorithm_comparison(
        fixed_range=wsn_main.ANALYSIS_RADIUS_M,
        algos=algorithms_to_compare,
        csv_dir=csv_dir,
        fig_dir=fig_dir,
        initial_energy_j=initial_energy,
        duration_s=config.duration_s
    )

    save_json(source_index, fig_dir / "sources.json")

    print("\n" + "=" * 70)
    print(" HOÀN TẤT! DỮ LIỆU 2 GIAI ĐOẠN ĐÃ ĐƯỢC XUẤT CHO BÁO CÁO ĐỒ ÁN.")
    print("=" * 70)
