"""Logging configuration and CSV persistence helpers for WSN simulation."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Sequence

DEFAULT_LOG_FORMAT = "%(asctime)s - [%(levelname)s] - %(message)s"


def setup_logger(
    name: str = "WSN_Logger",
    log_file: str | Path | None = "results/logs/simulation.log",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure and return a standard logger for WSN simulation.

    Args:
        name: Name of the logger.
        log_file: Optional file path to write logs to.
        level: Logging level (e.g. logging.INFO).

    Returns:
        Configured :class:`logging.Logger`.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid duplicate handlers if setup is called multiple times
    if not logger.handlers:
        formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

        # Stream handler for console output
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        # File handler if log_file is provided
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "WSN_Logger") -> logging.Logger:
    """Return the configured logger or initialize a default one."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


def save_to_csv(
    filename: str | Path,
    headers: Sequence[str],
    data_row: Sequence[object],
) -> Path:
    """Append a row of data to a CSV file, writing headers if file is new.

    Args:
        filename: Destination CSV file path.
        headers: Column headers written when the file is newly created.
        data_row: Sequence of cell values to append.

    Returns:
        Path of the modified CSV file.
    """
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.is_file() and path.stat().st_size > 0

    with path.open(mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(headers)
        writer.writerow(data_row)

    return path
