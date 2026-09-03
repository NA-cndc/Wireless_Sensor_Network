# logger.py
import logging
import csv
import os

# Thiết lập cơ chế ghi log ra màn hình và ra file .log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    handlers=[
        logging.FileHandler("simulation.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("WSN_Logger")

def save_to_csv(filename, headers, data_row):
    """Lưu kết quả chạy mô phỏng ra file CSV"""
    file_exists = os.path.isfile(filename)
    with open(filename, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        # Tự động ghi dòng tiêu đề nếu file chưa tồn tại
        if not file_exists:
            writer.writerow(headers)
        writer.writerow(data_row)