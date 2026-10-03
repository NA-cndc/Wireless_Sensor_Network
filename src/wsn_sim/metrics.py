"""Tabular topology metrics built with pandas."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import pandas as pd

TOPOLOGY_SUMMARY_COLUMNS = [
    "seed",
    "communication_range_m",
    "sensors",
    "sinks",
    "nodes",
    "edges",
    "routable_sensors",
    "isolated_sensors",
]


def topology_summary_frame(
    summaries: Iterable[Mapping[str, int | float]],
) -> pd.DataFrame:
    """Convert per-range summary mappings into a consistently ordered table.

    Args:
        summaries: One topology summary mapping per communication range.

    Returns:
        A DataFrame sorted by communication range with the documented columns.
    """
    frame = pd.DataFrame(list(summaries), columns=TOPOLOGY_SUMMARY_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values("communication_range_m", ignore_index=True)
    return frame
