"""Scientific figures from seed means; no subtitles, footnotes or error bars."""
import json
from pathlib import Path
from textwrap import fill
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, PercentFormatter
import numpy as np
import pandas as pd

ORDER = ["MHR", "EMHR", "MHR_SF", "EMHR_SF", "SF2", "SF3"]
SHORT = dict(zip(ORDER, ["MHR", "EMHR", "MHR-SF", "EMHR-SF", "SF-2", "S-EMHR"]))
LABELS = dict(zip(ORDER, ["MHR: không tấn công", "EMHR: không tấn công", "MHR-SF: không phòng thủ", "EMHR-SF: không phòng thủ", "SF-2: chỉ phát hiện", "S-EMHR: phát hiện và tránh relay"]))
COLORS = dict(zip(ORDER, ["#586778", "#007d71", "#bb4b19", "#bd8400", "#2765b8", "#7946af"]))
PLACEMENTS = {"random": "Ngẫu nhiên", "near_sink": "Gần sink"}
METRICS = {
    "pdr": ("Tỷ lệ giao gói PDR", "PDR (%)", 100),
    "energy_per_payload_bit_j": ("Năng lượng trên bit nhận thành công", "Năng lượng (µJ/bit payload)", 1e6),
    "throughput_bps": ("Thông lượng tại sink", "Thông lượng (kbit/s)", .001),
    "goodput_bps": ("Tốc độ payload hữu ích", "Goodput (kbit/s)", .001),
    "mean_latency_s": ("Độ trễ của gói nhận thành công", "Độ trễ đầu cuối (ms)", 1000),
    "mean_actual_hops": ("Số hop của gói nhận thành công", "Số hop trung bình", 1),
    "received_payload_bits": ("Payload đến sink tại 10.000 giây", "Payload nhận (Mbit)", 1e-6),
    "alive_sensors": ("Sensor còn sống tại 10.000 giây", "Số sensor còn sống", 1),
    "remaining_energy_j": ("Năng lượng còn lại tại 10.000 giây", "Năng lượng sensor (J)", 1),
    "FND_restricted_s": ("Thời gian giới hạn min(FND, 10.000 s)", "Thời gian giới hạn (s)", 1),
    "FND_observed_fraction": ("Lượt đã quan sát sensor đầu tiên chết", "Tỷ lệ lượt quan sát FND (%)", 100),
    "tpr": ("Phát hiện đúng nút tấn công", "TPR / Recall (%)", 100),
    "fpr": ("Báo nhầm sensor lành", "FPR (%)", 100),
    "precision": ("Độ chính xác của cảnh báo", "Precision (%)", 100),
    "f1": ("Trung bình điều hòa Precision–Recall", "F1 (%)", 100),
    "coverage": ("Nút có đủ quan sát phát hiện", "Độ bao phủ quan sát (%)", 100),
    "detection_capped_delay_s": ("Độ trễ phát hiện giới hạn tại 10.000 s", "Trễ giới hạn gồm chưa phát hiện (s)", 1),
    "reroute_decision_count": ("Quyết định tìm lại tuyến", "Số quyết định trong một lượt", 1),
    "route_edges_changed": ("Số cạnh có hướng thay đổi", "Tổng số cạnh thêm và bớt", 1),
    "isolation_events": ("Quyết định cách ly tạm thời", "Số quyết định trong một lượt", 1),
    "detector_isolation_events": ("Đề xuất cách ly của detector", "Số sự kiện trong một lượt", 1),
}
PERFORMANCE = ["pdr", "energy_per_payload_bit_j", "throughput_bps", "goodput_bps", "mean_latency_s", "mean_actual_hops"]


def is_center(row):
    return row["placement"] == "random" and (row["rho"] == 0 or (row["rho"] == .05 and row["p_drop"] == .5))


def number_label(value, ylabel):
    if "%" in ylabel:
        return f"{value:.2f}%".replace(".", ",")
    digits = 3 if any(unit in ylabel for unit in ("µJ", "kbit/s", "hop", "ms")) else 2
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


class FigureWriter:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.manifest = []
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11, "axes.labelsize": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.axisbelow": True, "grid.alpha": .18, "savefig.dpi": 170, "svg.fonttype": "none"})

    def layout(self, title, nrows=2, ncols=3):
        fig, axes = plt.subplots(nrows, ncols, figsize=(15.2, 8.8 if nrows > 1 else 5.1), squeeze=False)
        fig.patch.set_facecolor("white")
        fig.subplots_adjust(left=.075, right=.98, top=.86 if nrows > 1 else .78, bottom=.20 if nrows > 1 else .27, hspace=.74, wspace=.38)
        fig.suptitle(title, y=.97, fontsize=17, fontweight="bold", color="#182c3e")
        return fig, axes

    def save(self, fig, name, data, handles, labels, sources=()):
        from wsn_sim.experiment_execution import file_hash
        annotations, bars = [], []
        for index, axis in enumerate(fig.axes):
            columns = {}
            for rectangle in axis.patches:
                if not isinstance(rectangle, plt.Rectangle) or rectangle.get_height() < 0:
                    continue
                x = round(rectangle.get_x() + rectangle.get_width() / 2, 10)
                value, top, origins = columns.get(x, (0, 0, []))
                columns[x] = (value + rectangle.get_height(), max(top, rectangle.get_y() + rectangle.get_height()), origins + [getattr(rectangle, "_source_record", None)])
            for x, (value, top, origins) in columns.items():
                if isinstance(axis.yaxis.get_major_formatter(), PercentFormatter):
                    value = value / axis.yaxis.get_major_formatter().xmax * 100
                value, top = float(value), float(top)
                label = number_label(value, axis.get_ylabel())
                annotation = axis.annotate(label, (x, top), xytext=(0, 6), textcoords="offset points", ha="center", va="bottom", fontsize=8.8, fontweight="bold", color="#21354a", clip_on=False)
                annotations.append((axis, annotation, top))
                state = "positive" if value > 0 else "zero"
                if value == 0:
                    marker = axis.scatter([x], [0], marker="o", s=34, facecolors="white", edgecolors="#21354a", linewidths=1.3, zorder=5, clip_on=False)
                    marker.set_gid(f"true_zero_marker_{index}_{len(bars)}")
                bars.append({"axis": index, "x": x, "top_data_coordinate": top, "value_in_axis_units": value, "label": label, "ylabel": axis.get_ylabel(), "data_state": state, "zero_marker_shown": value == 0, "sources": [origin for origin in origins if origin is not None]})
        legend = fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5, .025), ncol=3 if len(labels) > 3 else len(labels), frameon=False, fontsize=9.5)
        fig.canvas.draw()
        for attempt in range(14):
            renderer, changed = fig.canvas.get_renderer(), False
            for axis in fig.axes:
                placed = []
                for _, annotation, top in sorted((item for item in annotations if item[0] is axis), key=lambda item: item[1].xy[0]):
                    box = annotation.get_window_extent(renderer)
                    while any(box.expanded(1.14, 1.12).overlaps(previous) for previous in placed):
                        x, y = annotation.get_position()
                        annotation.set_position((x, y + 13))
                        box = annotation.get_window_extent(renderer)
                        changed = True
                    placed.append(box)
                if placed and max(box.y1 for box in placed) > axis.get_window_extent(renderer).y1 - 5:
                    low, high = axis.get_ylim()
                    axis.set_ylim(low, high + (high - low) * .22)
                    changed = True
            if not changed:
                break
            fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        for bar in bars:
            axis = fig.axes[bar["axis"]]
            bar["rendered_height_pixels"] = float(abs(axis.transData.transform((bar["x"], bar["top_data_coordinate"]))[1] - axis.transData.transform((bar["x"], 0))[1]))
            bar["tiny_positive_marker_shown"] = False
            if bar["data_state"] == "positive" and bar["rendered_height_pixels"] < 2:
                marker = axis.scatter([bar["x"]], [bar["top_data_coordinate"]], marker="D", s=30, facecolors="white", edgecolors="#21354a", zorder=5, clip_on=False)
                marker.set_gid(f"tiny_positive_marker_{bar['axis']}_{len(bars)}")
                bar["tiny_positive_marker_shown"] = True
        legend_box = legend.get_window_extent(renderer)
        for axis in fig.axes:
            if axis.get_visible() and legend_box.overlaps(axis.get_window_extent(renderer)):
                raise ValueError(f"legend overlaps data: {name}")
        for index, (axis, annotation, top) in enumerate(annotations):
            box = annotation.get_window_extent(renderer)
            if box.y0 <= axis.transData.transform((0, top))[1] or box.y1 > axis.get_window_extent(renderer).y1:
                raise ValueError(f"label not above bar inside panel: {name}")
            if any(other_axis is axis and box.overlaps(other.get_window_extent(renderer)) for other_axis, other, _ in annotations[index + 1:]):
                raise ValueError(f"overlapping numeric labels: {name}")
        point_labels = []
        for axis_index, axis in enumerate(fig.axes):
            placed = []
            for line in axis.lines:
                for annotation in getattr(line, "_point_labels", []):
                    box = annotation.get_window_extent(renderer)
                    if any(box.overlaps(previous) for previous in placed):
                        raise ValueError(f"overlapping point labels: {name}")
                    axis_box = axis.get_window_extent(renderer)
                    if box.y0 < axis_box.y0 or box.y1 > axis_box.y1:
                        raise ValueError(f"point label outside panel: {name}")
                    placed.append(box)
                    point_labels.append({"axis": axis_index, "series": line.get_gid(), "x": float(annotation.xy[0]), "y": float(annotation.xy[1]), "label": annotation.get_text(), "ylabel": axis.get_ylabel()})
        # All nonempty rendered text must fit in the exported image, including ticks/legend.
        for text in fig.findobj(matplotlib.text.Text):
            if not text.get_visible() or not text.get_text():
                continue
            box = text.get_window_extent(renderer)
            if not fig.bbox.contains(box.x0, box.y0) or not fig.bbox.contains(box.x1, box.y1):
                raise ValueError(f"text clipped in {name}: {text.get_text()}")
        from matplotlib.container import ErrorbarContainer
        if any(isinstance(container, ErrorbarContainer) for axis in fig.axes for container in axis.containers):
            raise ValueError("error bars forbidden")
        if len(fig.texts) != 1:
            raise ValueError("configuration subtitles or footnotes are forbidden")
        for axis in fig.axes:
            for line in axis.lines:
                low, high = axis.get_ylim()
                if max(line.get_ydata()) > high - .02 * (high - low):
                    raise ValueError(f"line or marker too close to top border: {name}")
        data_path = self.directory / f"{name}_du_lieu.csv"
        pd.DataFrame(data).to_csv(data_path, index=False, encoding="utf-8-sig")
        png, svg = self.directory / f"{name}.png", self.directory / f"{name}.svg"
        fig.savefig(png, facecolor="white")
        fig.savefig(svg, facecolor="white")
        plt.close(fig)
        lines = [{"axis": index, "series": line.get_gid(), "x": np.asarray(line.get_xdata(), dtype=float).tolist(), "y": np.asarray(line.get_ydata(), dtype=float).tolist()} for index, axis in enumerate(fig.axes) for line in axis.lines]
        self.manifest.append({"figure": png.name, "vector": svg.name, "data_csv": data_path.name, "data_sha256": file_hash(data_path), "png_sha256": file_hash(png), "svg_sha256": file_hash(svg), "script_sha256": file_hash(Path(__file__)), "source_csv": "../aggregate.csv", "source_sha256": file_hash(self.directory.parent / "aggregate.csv"), "extra_sources": [{"path": str(path), "sha256": file_hash(path)} for path in sources], "bars": bars, "lines": lines, "point_labels": point_labels, "language": "vi", "layout_checks": {"legend_outside_all_axes": True, "labels_above_bars": True, "numeric_labels_do_not_overlap": True, "all_text_inside_figure": True, "point_labels_fit_axes": True, "configuration_subtitle_count": 0, "footnote_count": 0, "error_bar_count": 0}})


def format_axis(axis, metric):
    title, ylabel, _ = METRICS[metric]
    axis.set_title(fill(title, 39), pad=12)
    axis.set_ylabel(ylabel)
    axis.set_ylim(bottom=0)
    axis.margins(y=.22)
    axis.yaxis.set_major_locator(MaxNLocator(nbins=5))


def center_bars(writer, aggregates, name, title, metrics, scenarios=ORDER, scenario_groups=None, columns=3):
    ncols = min(columns, len(metrics))
    fig, axes = writer.layout(title, int(np.ceil(len(metrics) / ncols)), ncols)
    used = []
    for axis, metric in zip(axes.flat, metrics):
        selected = scenario_groups.get(metric, scenarios) if scenario_groups else scenarios
        counts = []
        for index, scenario in enumerate(selected):
            row = next(row for row in aggregates if row["scenario"] == scenario and row["metric"] == metric and is_center(row))
            counts.append(row["n_used"])
            used.append(row)
            if row["mean"] is not None:
                bars = axis.bar(index, row["mean"] * METRICS[metric][2], width=.65, color=COLORS[scenario])
                bars[0]._source_record = {"case_id": row["case_id"], "scenario": scenario, "metric": metric, "mean": row["mean"], "unit_factor": METRICS[metric][2], "n_used": row["n_used"], "reason": "measured_mean"}
            else:
                raise ValueError(f"main figure has undefined mean: {name}/{scenario}/{metric}")
        format_axis(axis, metric)
        ticklabels = [SHORT[key] + (f"\nn={count}" if count != 30 else "") for key, count in zip(selected, counts)]
        axis.set_xticks(range(len(selected)), ticklabels, rotation=25 if len(selected) > 3 else 0, ha="right" if len(selected) > 3 else "center")
        if metric == "FND_observed_fraction":
            axis.set_yticks([0, 25, 50, 75, 100])
    for axis in axes.flat[len(metrics):]:
        axis.set_visible(False)
    writer.save(fig, name, used, [plt.Rectangle((0, 0), 1, 1, color=COLORS[key]) for key in scenarios], [LABELS[key] for key in scenarios])


def factor_lines(writer, aggregates, name, title, variable, levels, condition):
    fig, axes = writer.layout(title)
    used, handles = [], []
    for axis, metric in zip(axes.flat, PERFORMANCE):
        series = {}
        for scenario, marker in (("EMHR_SF", "o"), ("SF3", "s")):
            rows = sorted([row for row in aggregates if row["scenario"] == scenario and row["metric"] == metric and condition(row)], key=lambda row: levels.index(row[variable]))
            used.extend(rows)
            line, = axis.plot(range(len(levels)), [row["mean"] * METRICS[metric][2] for row in rows], color=COLORS[scenario], marker=marker, markersize=6, linewidth=2)
            line.set_gid(metric + "|" + scenario)
            series[scenario] = line
            if metric == PERFORMANCE[0]:
                handles.append(line)
        format_axis(axis, metric)
        axis.set_xticks(range(len(levels)), [f"{level * 100:g}%" if variable == "rho" else f"{level:.2f}".replace(".", ",") for level in levels])
        axis.set_xlabel("Tỷ lệ nút tấn công yêu cầu" if variable == "rho" else "Xác suất bỏ gói P_drop")
        axis.margins(x=.12, y=.15)
        all_values = [float(value) for line in series.values() for value in line.get_ydata()]
        low, high = min(all_values), max(all_values)
        padding = max((high - low) * .40, max(abs(high), 1) * .005)
        axis.set_ylim(max(0, low - padding), high + padding)
        for scenario, line in series.items():
            labels_on_line = []
            for index, value in enumerate(line.get_ydata()):
                other = series["SF3" if scenario == "EMHR_SF" else "EMHR_SF"].get_ydata()[index]
                above = value > other or value == other and scenario == "SF3"
                label = number_label(float(value), axis.get_ylabel())
                annotation = axis.annotate(label, (index, value), xytext=(0, 8 if above else -8), textcoords="offset points", ha="center", va="bottom" if above else "top", fontsize=8.8, fontweight="bold", color=COLORS[scenario], clip_on=False)
                labels_on_line.append(annotation)
            line._point_labels = labels_on_line
    writer.save(fig, name, used, handles, [LABELS[key] for key in ("EMHR_SF", "SF3")])


def placement_bars(writer, aggregates):
    fig, axes = writer.layout("Ảnh hưởng của vị trí nút tấn công")
    used = []
    for axis, metric in zip(axes.flat, PERFORMANCE):
        for scenario, offset in (("EMHR_SF", -.18), ("SF3", .18)):
            for index, placement in enumerate(("random", "near_sink")):
                row = next(row for row in aggregates if row["scenario"] == scenario and row["rho"] == .05 and row["p_drop"] == .5 and row["placement"] == placement and row["metric"] == metric)
                used.append(row)
                bars = axis.bar(index + offset, row["mean"] * METRICS[metric][2], width=.33, color=COLORS[scenario])
                bars[0]._source_record = {"case_id": row["case_id"], "scenario": scenario, "metric": metric, "mean": row["mean"], "unit_factor": METRICS[metric][2], "n_used": row["n_used"], "reason": "measured_mean"}
        format_axis(axis, metric)
        axis.set_xticks([0, 1], ["Ngẫu nhiên", "Gần sink"])
    writer.save(fig, "06_vi_tri_attacker", used, [plt.Rectangle((0, 0), 1, 1, color=COLORS[key]) for key in ("EMHR_SF", "SF3")], [LABELS[key] for key in ("EMHR_SF", "SF3")])


def time_curves(writer, records):
    from wsn_sim.experiment_statistics import sample_summary
    fig, axes = writer.layout("Diễn biến mạng trong 10.000 giây", 1, 2)
    used, sources, handles = [], [], []
    for scenario in ORDER:
        group = [record for record in records if record["job"]["case"]["scenario"] == scenario and is_center(record["job"]["case"])]
        frames = []
        for record in group:
            source = record["directory"] / "timeseries.csv"
            frame = pd.read_csv(source)
            if list(frame["time_s"]) != list(range(0, 10001, 100)):
                raise ValueError("unexpected short time grid")
            frames.append(frame)
            sources.append(source)
        for axis, metric, ylabel in zip(axes.flat, ("alive_sensors", "remaining_energy_j"), ("Số sensor còn sống", "Năng lượng sensor (J)")):
            values = []
            for index, time in enumerate(range(0, 10001, 100)):
                stats = sample_summary([float(frame.iloc[index][metric]) for frame in frames], 30)
                used.append({"scenario": scenario, "metric": metric, "time_s": time, **stats})
                values.append(stats["mean"])
            line, = axis.plot(range(0, 10001, 100), values, color=COLORS[scenario], linewidth=1.8, linestyle="--" if scenario in ("MHR_SF", "EMHR_SF", "SF2") else "-")
            line.set_gid(metric + "|" + scenario)
            if metric == "alive_sensors":
                handles.append(line)
            axis.set_ylabel(ylabel)
            axis.set_xlabel("Thời gian mô phỏng (s)")
            axis.set_title("Sensor còn sống" if metric == "alive_sensors" else "Năng lượng còn lại", pad=12)
            axis.set_xlim(0, 10000)
            axis.set_ylim(bottom=0)
    for axis in axes.flat:
        axis.set_ylim(0, max(max(line.get_ydata()) for line in axis.lines) * 1.10)
    writer.save(fig, "07_dien_bien_mang", used, handles, [LABELS[key] for key in ORDER], sources)


def drop_composition(writer, rows):
    categories = [("delivered_fraction", "Giao thành công", "#168875"), ("unreachable_fraction", "Không có tuyến", "#9ba5b1"), ("selective_forwarding_fraction", "Selective Forwarding", "#ca522a"), ("natural_link_loss_fraction", "Mất kênh tự nhiên", "#d5a023"), ("energy_depletion_fraction", "Cạn năng lượng", "#70509b"), ("in_flight_fraction", "Đang truyền", "#2b6eae")]
    fig, axes = writer.layout("Trạng thái gói tại 10.000 giây", 1, 2)
    axis, table_axis = axes.flat
    used, bottom = [], np.zeros(6)
    for metric, label, color in categories:
        values = []
        for scenario in ORDER:
            group = [row for row in rows if row["scenario"] == scenario and is_center(row)]
            values.append(float(np.mean([row[metric] for row in group])))
            used.extend({"scenario": scenario, "seed": row["seed"], "metric": metric, "value": row[metric]} for row in group)
        axis.bar(range(6), values, bottom=bottom, color=color, width=.65, label=label)
        bottom += values
    axis.set_xticks(range(6), [SHORT[key] for key in ORDER], rotation=25, ha="right")
    axis.set_ylim(0, 1.20)
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.set_ylabel("Tỷ lệ trong số gói sinh ra (%)")
    axis.set_yticks(np.linspace(0, 1, 6))
    table_axis.axis("off")
    table_axis.set_title("Tỷ lệ trung bình từng trạng thái (%)", pad=12)
    cells = [[SHORT[key], *[f"{np.mean([row[metric] for row in rows if row['scenario'] == key and is_center(row)]) * 100:.4f}".replace(".", ",") for metric, _, _ in categories]] for key in ORDER]
    table = table_axis.table(cellText=cells, colLabels=["Kịch bản", "Giao\nđược", "Không\ntuyến", "Bị\ntấn công", "Mất\nkênh", "Hết\npin", "Đang\ntruyền"], cellLoc="center", bbox=[0, 0, 1, .96])
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    for (row, column), cell in table.get_celld().items():
        cell.set_edgecolor("#dce5eb")
        cell.set_facecolor("#eaf0f5" if row == 0 else "white")
    handles, labels = axis.get_legend_handles_labels()
    writer.save(fig, "09_trang_thai_goi", used, handles, labels)


def draw_all(plan, rows, aggregates, records, directory):
    writer = FigureWriter(directory)
    center_bars(writer, aggregates, "01_hieu_nang_trung_tam", "Hiệu năng mạng trong 10.000 giây", PERFORMANCE)
    center_bars(writer, aggregates, "02_trang_thai_10000s", "Dữ liệu và trạng thái mạng tại 10.000 giây", ["received_payload_bits", "alive_sensors", "remaining_energy_j"])
    center_bars(writer, aggregates, "03_phat_hien_bao_mat", "Phát hiện Selective Forwarding tại 10.000 giây", ["tpr", "fpr", "precision", "f1", "coverage", "detection_capped_delay_s"], ["SF2", "SF3"])
    factor_lines(writer, aggregates, "04_ty_le_attacker", "Ảnh hưởng của tỷ lệ nút tấn công", "rho", [.02, .05, .1], lambda row: row["p_drop"] == .5 and row["placement"] == "random")
    factor_lines(writer, aggregates, "05_xac_suat_bo_goi", "Ảnh hưởng của xác suất bỏ gói", "p_drop", [.25, .5, .75], lambda row: row["rho"] == .05 and row["placement"] == "random")
    placement_bars(writer, aggregates)
    time_curves(writer, records)
    center_bars(writer, aggregates, "08_FND_gioi_han", "Mốc sensor đầu tiên chết trong 10.000 giây", ["FND_restricted_s", "FND_observed_fraction"])
    drop_composition(writer, rows)
    center_bars(writer, aggregates, "10_doi_tuyen_va_cach_ly", "Đổi tuyến và đề xuất cách ly trong 10.000 giây", ["reroute_decision_count", "route_edges_changed", "detector_isolation_events"], scenario_groups={"detector_isolation_events": ["SF2", "SF3"]})
    audit = [{"figure": figure["figure"], **bar} for figure in writer.manifest for bar in figure["bars"]]
    pd.DataFrame(audit).to_csv(writer.directory.parent / "bar_visibility_audit.csv", index=False, encoding="utf-8-sig")
    (writer.directory / "figure_manifest.json").write_text(json.dumps(writer.manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return writer.manifest
