"""Cơ chế cấu hình ghi Log đa kênh và hàm tiện ích lưu kết quả dạng CSV."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Sequence

# Định dạng chuẩn của dòng log: [Thời gian] - [Mức độ log] - [Nội dung thông điệp]
DEFAULT_LOG_FORMAT = "%(asctime)s - [%(levelname)s] - %(message)s"


def setup_logger(
    name: str = "WSN_Logger",
    log_file: str | Path | None = "results/logs/simulation.log",
    level: int = logging.INFO,
) -> logging.Logger:
    """Cấu hình và trả về đối tượng Logger tiêu chuẩn cho hệ thống WSN.

    Cơ chế ghi log hai kênh đồng thời:
    1. Kênh 1 (StreamHandler): Xuất log ra màn hình console / terminal trực tiếp.
    2. Kênh 2 (FileHandler): Lưu trữ vĩnh viễn vào tệp tin 'results/logs/simulation.log' (UTF-8).

    Args:
        name: Tên của logger.
        log_file: Đường dẫn file nhật ký log cần ghi. Nếu None, chỉ xuất ra console.
        level: Ngưỡng mức độ ghi log (mặc định INFO).

    Returns:
        Đối tượng logging.Logger đã được cấu hình hoàn chỉnh.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Kiểm tra tránh đăng ký lặp lại handler nếu hàm được gọi nhiều lần
    if not logger.handlers:
        formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

        # Kênh 1: Handler xuất log ra màn hình console
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        # Kênh 2: Handler ghi log ra tệp tin với bộ mã hóa UTF-8
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(
                parents=True, exist_ok=True
            )  # Tự động tạo thư mục cha nếu chưa có
            file_handler = logging.FileHandler(log_path, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "WSN_Logger") -> logging.Logger:
    """Lấy đối tượng logger đã được thiết lập hoặc tự động khởi tạo mặc định nếu chưa có."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger


def save_to_csv(
    filename: str | Path,
    headers: Sequence[str],
    data_row: Sequence[object],
) -> Path:
    """Ghi bổ sung (Append) một dòng kết quả vào file CSV.

    Tính năng thông minh:
    - Nếu file chưa tồn tại hoặc rỗng: Tự động ghi dòng tiêu đề (headers) trước, sau đó ghi dòng dữ liệu.
    - Nếu file đã có dữ liệu: Chỉ ghi tiếp dòng dữ liệu mới vào cuối file mà không ghi đè tiêu đề.

    Args:
        filename: Đường dẫn tới file CSV đích.
        headers: Danh sách tên các cột tiêu đề.
        data_row: Danh sách các giá trị dữ liệu của một hàng.

    Returns:
        Đối tượng Path trỏ tới file CSV đã lưu.
    """
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)  # Đảm bảo thư mục đích tồn tại
    file_exists = path.is_file() and path.stat().st_size > 0

    with path.open(mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(headers)  # Ghi tiêu đề nếu là file mới
        writer.writerow(data_row)  # Ghi dòng dữ liệu

    return path
