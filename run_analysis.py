import sys
import os
import json
import shutil
from math import ceil
from pathlib import Path

# Cấu hình UTF-8 cho console trên Windows tránh lỗi encode
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

for path_dir in (str(PROJECT_ROOT), str(SRC_DIR)):
    if path_dir not in sys.path:
        sys.path.insert(0, path_dir)

import pandas as pd
import matplotlib.pyplot as plt

from config import SimulationConfig
from network import Network
from visualization import save_topology_plot


def generate_topologies(ranges, config_data, fig_dir):
    print("\n[1] ĐANG VẼ 3 BẢN ĐỒ TOPOLOGY (VECTOR PDF)...")
    cfg = SimulationConfig.from_dict(config_data)
    for r in ranges:
        network = Network(cfg, communication_range_m=r)
        out_path = fig_dir / f"topology_R{int(r)}m.pdf"
        save_topology_plot(network, out_path)
        print(f" -> Đã lưu: {out_path}")


def organize_csv_files(results_dir, csv_dir):
    print("\n[3] ĐANG LƯU DỮ LIỆU VÀO THƯ MỤC results/csv...")
    if results_dir.exists():
        for file in os.listdir(results_dir):
            if file.endswith(".csv") and file.startswith("simulation_log"):
                old_path = results_dir / file
                new_path = csv_dir / file
                shutil.move(str(old_path), str(new_path))


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

    energy_palette = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
    color_idx = 0
    actual_sensors = 450
    valid_dfs = []
    algo_styles = {}

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

        if algo == "MHR":
            c = "dimgray"
            ls = "--"
            label_name = "MHR (Chuẩn đối chứng)"
        else:
            c = energy_palette[color_idx % len(energy_palette)]
            color_idx += 1
            ls = "-"
            label_name = algo

        algo_styles[algo] = (c, ls)

        r_t = (df["Routable_Nodes"] / df["Alive_Nodes"].replace(0, 1)) * 100
        r_t[df["Alive_Nodes"] == 0] = 0
        ax_life.plot(df["Time_s"], r_t, label=label_name, color=c, linestyle=ls, linewidth=2.2)

        dead_nodes = actual_sensors - df["Alive_Nodes"]
        ax_dead.plot(df["Time_s"], dead_nodes, label=label_name, color=c, linestyle=ls, linewidth=2.2)
        ax_energy.plot(df["Time_s"], df["Total_Energy_J"], label=label_name, color=c, linestyle=ls, linewidth=2.2)
        ax_lat.plot(df["Time_s"], df["Avg_Latency_s"], label=label_name, color=c, linestyle=ls, linewidth=2.2)

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

    if valid_dfs:
        n_algos = len(valid_dfs)
        ncols = n_algos if n_algos <= 3 else ceil(n_algos / 2)
        nrows = 1 if n_algos <= 3 else 2

        fig_pkt, axes = plt.subplots(
            nrows, ncols,
            figsize=(6.5 * ncols, 5.5 * nrows),
            sharey=False,
            squeeze=False
        )
        axes_flat = axes.flatten()

        end_time = int(valid_dfs[0][1]["Time_s"].iloc[-1])
        print(f"\n   [SỐ LIỆU CHÍNH XÁC GÓI TIN TẠI {r_label} (t = {end_time}s)]")
        print(f"   {'Thuật toán':<20} | {'Đến đích':>10} | {'Mất đường':>10} | {'Chết giữa chừng':>15} | {'Nhiễu sóng':>10}")
        print("   " + "-" * 77)

        max_main_y = 0
        for _, df in valid_dfs:
            max_main_y = max(
                max_main_y,
                df[["Delivered_Packets", "Drop_NoRoute", "Drop_Dead", "Drop_Interf"]].max().max()
            )

        for idx, (algo, df) in enumerate(valid_dfs):
            last_row = df.iloc[-1]
            delivered = int(last_row["Delivered_Packets"])
            drop_noroute = int(last_row["Drop_NoRoute"])
            drop_dead = int(last_row["Drop_Dead"])
            drop_interf = int(last_row["Drop_Interf"])

            print(f"   {algo:<20} | {delivered:>10,} | {drop_noroute:>10,} | {drop_dead:>15,} | {drop_interf:>10,}")

            ax_target = axes_flat[idx]
            ax_target.plot(df["Time_s"], df["Delivered_Packets"], label="Đến đích thành công", color="tab:green", linewidth=2.5)
            ax_target.plot(df["Time_s"], df["Drop_NoRoute"], label="Rớt do Mất đường đi", color="tab:red", linewidth=2)
            ax_target.plot(df["Time_s"], df["Drop_Dead"], label="Rớt do Trạm chuyển chết", color="tab:orange", linewidth=2)
            ax_target.plot(df["Time_s"], df["Drop_Interf"], label="Rớt do Nhiễu sóng", color="tab:purple", linewidth=2)

            ax_target.set_ylim(0, max_main_y * 1.05)
            ax_target.set_title(f"Phân rã gói tin - {algo} ({r_label})", fontsize=13, fontweight="bold")
            ax_target.set_xlabel("Thời gian (s)", fontsize=11)
            ax_target.grid(True, linestyle=":", alpha=0.6)

            if idx % ncols == 0:
                ax_target.set_ylabel("Số lượng gói tin cộng dồn", fontsize=11)
            if idx == 0:
                ax_target.legend(loc="upper left", fontsize="9.5")

            if n_algos < len(axes_flat):
                c, ls = algo_styles[algo]
                axes_flat[n_algos].plot(
                    df["Time_s"],
                    df["Drop_Dead"],
                    label=f"{algo} ({drop_dead:,} gói)",
                    color=c,
                    linestyle=ls,
                    linewidth=2.2
                )

        if n_algos < len(axes_flat):
            ax_zoom = axes_flat[n_algos]
            ax_zoom.set_ylim(bottom=0)
            ax_zoom.set_title(f"Phóng đại: Rớt do Trạm chuyển chết ({r_label})", fontsize=13, fontweight="bold")
            ax_zoom.set_xlabel("Thời gian (s)", fontsize=11)
            ax_zoom.set_ylabel("Số gói rớt cộng dồn", fontsize=11)
            ax_zoom.legend(title="Thuật toán (Cuối kỳ)", loc="upper left", fontsize="9.5")
            ax_zoom.grid(True, linestyle=":", alpha=0.6)

        for idx in range(n_algos + 1, len(axes_flat)):
            axes_flat[idx].set_visible(False)

        fig_pkt.tight_layout()
        fig_pkt.savefig(fig_dir / "stage2_algo_5_packet_breakdown.pdf", format="pdf")
        plt.close(fig_pkt)


def run_post_simulation(project_root=PROJECT_ROOT):
    """Hàm hậu xử lý: gom CSV, vẽ toàn bộ biểu đồ và in bảng thống kê."""
    results_dir = Path(project_root) / "results"
    csv_dir = results_dir / "csv"
    fig_dir = results_dir / "figures"
    csv_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    config_path = Path(project_root) / "configs" / "default.json"
    if not config_path.exists():
        print(f"\n[LỖI] Không tìm thấy file cấu hình tại {config_path.absolute()}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    ranges = config_data.get("communication_ranges_m", [250.0, 300.0, 350.0])
    initial_energy = float(config_data.get("initial_energy_j", 5.0))

    generate_topologies(ranges, config_data, fig_dir)
    organize_csv_files(results_dir, csv_dir)

    plot_range_selection(
        ranges=ranges,
        csv_dir=csv_dir,
        fig_dir=fig_dir,
        algo="EMHR",
        initial_energy_j=initial_energy
    )

    algorithms_to_compare = [
        "MHR",
        "EMHR",
        "Weighted_Dijkstra",
        "MMBCR",
        "GPSR",
    ]
    plot_algorithm_comparison(
        fixed_range=300.0,
        algos=algorithms_to_compare,
        csv_dir=csv_dir,
        fig_dir=fig_dir,
        initial_energy_j=initial_energy
    )

    print("\n" + "=" * 70)
    print(" HOÀN TẤT! DỮ LIỆU 2 GIAI ĐOẠN ĐÃ ĐƯỢC XUẤT CHO BÁO CÁO ĐỒ ÁN.")
    print("=" * 70)


if __name__ == "__main__":
    # Vẫn có thể chạy độc lập để vẽ lại biểu đồ từ CSV cũ mà không cần mô phỏng lại
    run_post_simulation()