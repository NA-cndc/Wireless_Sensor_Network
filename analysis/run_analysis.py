import sys
import multiprocessing
from argparse import ArgumentParser
from math import ceil, isfinite
from pathlib import Path

# Cấu hình UTF-8 cho console trên Windows tránh lỗi encode
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

for path_dir in (str(PROJECT_ROOT), str(SRC_DIR)):
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

import pandas as pd
import matplotlib.pyplot as plt

from wsn_sim.config import SimulationConfig
from wsn_sim.visualization import save_topology_plot
from analysis.foundation.network import Network
from analysis.foundation.runner import COMPARISON_ALGORITHMS, COMPARISON_RANGE_M, CONFIG_PATH, run_project


def generate_topologies(ranges, cfg, fig_dir):
    print("\n[1] ĐANG VẼ 3 BẢN ĐỒ TOPOLOGY (VECTOR PDF)...")
    for r in ranges:
        network = Network(cfg, communication_range_m=r)
        out_path = fig_dir / f"topology_R{int(r)}m.pdf"
        save_topology_plot(network, out_path)
        print(f" -> Đã lưu: {out_path}")


def _format(fig, ax, title, xlabel, ylabel, path, legend_title="Thuật toán"):
    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.legend(title=legend_title, fontsize="10", loc="best")
    ax.grid(True, linestyle=":", alpha=0.6)
    fig.tight_layout()
    fig.savefig(path, format="pdf")
    plt.close(fig)


def plot_range_selection(ranges, csv_dir, fig_dir, algo="EMHR", initial_energy_j=5.0):
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
        csv_file = csv_dir / f"simulation_log_{algo}_range_{int(r)}m.csv"
        if not csv_file.exists():
            print(f" [Bỏ qua] Không tìm thấy file: {csv_file.name}")
            continue

        df_raw = pd.read_csv(csv_file)
        if df_raw.empty:
            continue

        # Lấy đúng số sensor thực tế được sinh ngẫu nhiên để tránh lệch mốc 0
        actual_sensors = int(df_raw["Alive_Nodes"].max())
        df = df_raw[df_raw["Time_s"] > 0]

        c = colors.get(float(r), "black")
        label_name = f"R = {int(r)}m"

        r_t = (df["Routable_Nodes"] / df["Alive_Nodes"].replace(0, 1)) * 100
        r_t[df["Alive_Nodes"] == 0] = 0
        ax_life.plot(df["Time_s"], r_t, label=label_name, color=c, linestyle="-", linewidth=2.2)

        dead_nodes = actual_sensors - df["Alive_Nodes"]
        ax_dead.plot(df["Time_s"], dead_nodes, label=label_name, color=c, linestyle="-", linewidth=2.2)
        ax_energy.plot(df["Time_s"], df["Total_Energy_J"], label=label_name, color=c, linestyle="-", linewidth=2.2)
        ax_lat.plot(df["Time_s"], df["Avg_Latency_s"], label=label_name, color=c, linestyle="-", linewidth=2.2)

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
        legend_title="Bán kính truyền"
    )
    _format(
        fig_energy, ax_energy,
        f"Ảnh hưởng của Bán kính truyền đến Tiêu hao Năng lượng ({algo})",
        "Thời gian (s)", "Năng lượng còn lại (Joules)",
        fig_dir / "stage1_range_2_energy.pdf",
        legend_title="Bán kính truyền"
    )
    _format(
        fig_lat, ax_lat,
        f"Ảnh hưởng của Bán kính truyền đến Độ trễ trung bình ({algo})",
        "Thời gian (s)", "Độ trễ (giây)",
        fig_dir / "stage1_range_3_latency.pdf",
        legend_title="Bán kính truyền"
    )
    _format(
        fig_dead, ax_dead,
        f"Số lượng Sensor chết theo Bán kính truyền ({algo})",
        "Thời gian (s)", "Số Sensor đã chết",
        fig_dir / "stage1_range_4_dead_nodes.pdf",
        legend_title="Bán kính truyền"
    )


def plot_algorithm_comparison(fixed_range, algos, csv_dir, fig_dir, initial_energy_j=5.0):
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
        csv_file = csv_dir / f"simulation_log_{algo}_range_{int(fixed_range)}m.csv"
        if not csv_file.exists():
            print(f" [Bỏ qua] Không tìm thấy file: {csv_file.name}")
            continue

        df_raw = pd.read_csv(csv_file)
        if df_raw.empty:
            continue

        actual_sensors = int(df_raw["Alive_Nodes"].max())
        df = df_raw[df_raw["Time_s"] > 0]
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

        r_t = (df["Routable_Nodes"] / df["Alive_Nodes"].replace(0, 1)) * 100
        r_t[df["Alive_Nodes"] == 0] = 0
        ax_life.plot(df["Time_s"], r_t, label=label_name, color=c, linestyle=ls, linewidth=2.2)

        dead_nodes = actual_sensors - df["Alive_Nodes"]
        ax_dead.plot(df["Time_s"], dead_nodes, label=label_name, color=c, linestyle=ls, linewidth=2.2)
        ax_energy.plot(df["Time_s"], df["Total_Energy_J"], label=label_name, color=c, linestyle=ls, linewidth=2.2)
        ax_lat.plot(df["Time_s"], df["Avg_Latency_s"], label=label_name, color=c, linestyle=ls, linewidth=2.2)

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
        fig_dir / "stage2_algo_1_lifetime.pdf"
    )
    _format(
        fig_energy, ax_energy,
        f"So sánh Tiêu hao Năng lượng toàn mạng ({r_label})",
        "Thời gian (s)", "Năng lượng còn lại (Joules)",
        fig_dir / "stage2_algo_2_energy.pdf"
    )
    _format(
        fig_lat, ax_lat,
        f"So sánh Độ trễ truyền tin trung bình ({r_label})",
        "Thời gian (s)", "Độ trễ (giây)",
        fig_dir / "stage2_algo_3_latency.pdf"
    )
    _format(
        fig_dead, ax_dead,
        f"So sánh Số lượng Sensor chết - FND/HND ({r_label})",
        "Thời gian (s)", "Số Sensor đã chết",
        fig_dir / "stage2_algo_4_dead_nodes.pdf"
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
            ax_target.set_xlabel("Thời gian (s)", fontsize=11)
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


def main():
    parser = ArgumentParser(description="So sánh bán kính truyền và năm thuật toán định tuyến.")
    parser.add_argument("--duration", type=float, default=12000.0)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "results")
    args = parser.parse_args()
    if not isfinite(args.duration) or args.duration <= 0:
        parser.error("--duration phải là số hữu hạn lớn hơn 0")

    results_dir = args.output.resolve()
    csv_dir = results_dir / "csv"
    fig_dir = results_dir / "figures"
    csv_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    config = SimulationConfig.from_json(CONFIG_PATH)
    ranges = config.communication_ranges_m
    initial_energy = config.initial_energy_j

    generate_topologies(ranges, config, fig_dir)
    run_project(config, args.duration, csv_dir)

    # Giai đoạn 1: Khảo sát 3 bán kính trên thuật toán EMHR
    plot_range_selection(
        ranges=ranges,
        csv_dir=csv_dir,
        fig_dir=fig_dir,
        algo="EMHR",
        initial_energy_j=initial_energy
    )

    # Giai đoạn 2: Cố định R=300m, đối chứng MHR với 4 thuật toán tối ưu năng lượng
    plot_algorithm_comparison(
        fixed_range=COMPARISON_RANGE_M,
        algos=COMPARISON_ALGORITHMS,
        csv_dir=csv_dir,
        fig_dir=fig_dir,
        initial_energy_j=initial_energy
    )

    print("\n" + "=" * 70)
    print(" HOÀN TẤT! DỮ LIỆU 2 GIAI ĐOẠN ĐÃ ĐƯỢC XUẤT CHO BÁO CÁO ĐỒ ÁN.")
    print("=" * 70)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
