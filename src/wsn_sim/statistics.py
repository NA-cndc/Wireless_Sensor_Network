"""Công cụ phân tích thống kê khoa học theo đề cương (Mục 3.9).

Thực hiện:
- Mean (Trung bình mẫu)
- Sample SD (Độ lệch chuẩn mẫu với ddof=1)
- 95% Confidence Interval (Khoảng tin cậy 95% theo Student-t với n-1 bậc tự do)
- Paired comparison: Paired t-test hoặc Wilcoxon signed-rank test
- Effect size (Cohen's d cho mẫu cặp)
- Xử lý dữ liệu censored (thời gian sống chưa kết thúc).
"""

from __future__ import annotations

import math
from typing import Any, Sequence

import numpy as np
from scipy import stats


def calculate_sample_statistics(values: Sequence[float | None]) -> dict[str, Any]:
    """Tính toán thống kê mô tả cho một tập dữ liệu quan sát.

    Tự động xử lý và tách riêng các giá trị censored (None / chưa đạt mốc).
    """
    valid_vals = [float(v) for v in values if v is not None and not math.isnan(v)]
    censored_count = len(values) - len(valid_vals)

    if not valid_vals:
        return {
            "count_total": len(values),
            "count_valid": 0,
            "count_censored": censored_count,
            "censored_ratio": (censored_count / len(values)) if values else 0.0,
            "mean": None,
            "std": None,
            "ci_95_lower": None,
            "ci_95_upper": None,
            "min": None,
            "max": None,
        }

    n = len(valid_vals)
    mean_val = float(np.mean(valid_vals))

    if n > 1:
        sample_sd = float(np.std(valid_vals, ddof=1))
        se = sample_sd / math.sqrt(n)
        t_crit = float(stats.t.ppf(0.975, df=n - 1))
        ci_lower = mean_val - t_crit * se
        ci_upper = mean_val + t_crit * se
    else:
        sample_sd = 0.0
        ci_lower = mean_val
        ci_upper = mean_val

    return {
        "count_total": len(values),
        "count_valid": n,
        "count_censored": censored_count,
        "censored_ratio": (censored_count / len(values)) if values else 0.0,
        "mean": round(mean_val, 6),
        "std": round(sample_sd, 6),
        "ci_95_lower": round(ci_lower, 6),
        "ci_95_upper": round(ci_upper, 6),
        "min": round(float(np.min(valid_vals)), 6),
        "max": round(float(np.max(valid_vals)), 6),
    }


def compare_paired_experiments(
    baseline_values: Sequence[float | None],
    proposed_values: Sequence[float | None],
    alpha: float = 0.05,
) -> dict[str, Any]:
    """So sánh cặp giữa hai thuật toán (ví dụ: MHR vs EMHR, hoặc MHR-SF vs S-EMHR).

    Quy trình:
    1. Lọc các cặp hoàn chỉnh (loại bỏ cặp có ít nhất 1 giá trị censored).
    2. Kiểm định tính chuẩn của chênh lệch (Shapiro-Wilk test).
    3. Chọn Paired t-test nếu chuẩn, hoặc Wilcoxon signed-rank test nếu không chuẩn.
    4. Tính Cohen's d effect size: d = mean(diff) / std(diff, ddof=1).
    """
    if len(baseline_values) != len(proposed_values):
        raise ValueError("baseline_values and proposed_values must have the same length")

    paired_data = [
        (float(b), float(p))
        for b, p in zip(baseline_values, proposed_values)
        if b is not None and p is not None and not math.isnan(b) and not math.isnan(p)
    ]

    censored_pairs_count = len(baseline_values) - len(paired_data)

    if len(paired_data) < 2:
        return {
            "pairs_total": len(baseline_values),
            "pairs_valid": len(paired_data),
            "censored_pairs_count": censored_pairs_count,
            "error": "insufficient valid paired samples (need at least 2)",
        }

    b_arr = np.array([x[0] for x in paired_data], dtype=float)
    p_arr = np.array([x[1] for x in paired_data], dtype=float)
    diffs = p_arr - b_arr

    mean_b = float(np.mean(b_arr))
    mean_p = float(np.mean(p_arr))
    mean_diff = float(np.mean(diffs))
    abs_diff = abs(mean_p - mean_b)
    pct_change = ((mean_p - mean_b) / abs(mean_b) * 100.0) if abs(mean_b) > 1e-12 else None

    sd_diff = float(np.std(diffs, ddof=1))
    cohens_d = (mean_diff / sd_diff) if sd_diff > 1e-12 else 0.0

    is_normal = True
    shapiro_p = None
    if len(diffs) >= 3 and float(np.ptp(diffs)) > 1e-12:
        try:
            shapiro_stat, p_val = stats.shapiro(diffs)
            if not math.isnan(p_val):
                shapiro_p = round(float(p_val), 6)
                is_normal = bool(shapiro_p >= alpha)
        except Exception:
            is_normal = True

    test_name = "paired_t_test"
    p_value = 1.0

    if np.all(np.abs(diffs) < 1e-12):
        test_name = "identical_pairs"
        p_value = 1.0
    else:
        try:
            if is_normal or len(diffs) >= 30:
                test_res = stats.ttest_rel(p_arr, b_arr)
                p_value = float(test_res.pvalue)
                test_name = "paired_t_test"
            else:
                test_res = stats.wilcoxon(p_arr, b_arr)
                p_value = float(test_res.pvalue)
                test_name = "wilcoxon_signed_rank"
        except Exception:
            test_res = stats.ttest_rel(p_arr, b_arr)
            p_value = float(test_res.pvalue)

    if math.isnan(p_value):
        p_value = 1.0

    return {
        "pairs_total": len(baseline_values),
        "pairs_valid": len(paired_data),
        "censored_pairs_count": censored_pairs_count,
        "mean_baseline": round(mean_b, 6),
        "mean_proposed": round(mean_p, 6),
        "mean_difference": round(mean_diff, 6),
        "absolute_difference": round(abs_diff, 6),
        "percent_change": round(pct_change, 2) if pct_change is not None else None,
        "test_used": test_name,
        "shapiro_p_value": round(float(shapiro_p), 6) if shapiro_p is not None else None,
        "is_difference_normal": is_normal,
        "p_value": round(p_value, 6),
        "statistically_significant": bool(p_value < alpha),
        "cohens_d_effect_size": round(cohens_d, 4),
    }
