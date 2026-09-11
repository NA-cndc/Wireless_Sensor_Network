# Hướng dẫn Cài đặt và Chạy Dự án trên Ubuntu và Windows

Tài liệu hướng dẫn thiết lập môi trường để đảm bảo **cả hai máy** (Ubuntu và Windows) đều chạy được mã nguồn và tái lập chính xác kết quả mô phỏng WSN.

---

## 1. Yêu cầu hệ thống ban đầu
- Python 3.10 trở lên và `pip` đã được cài đặt.
- Git đã được cài đặt.
- Khuyến nghị sử dụng môi trường ảo (`venv`) để cách ly thư viện.

Kiểm tra phiên bản Python:
```bash
python --version   # hoặc python3 --version trên Linux
```

---

## 2. Thiết lập Môi trường Ảo (Virtual Environment)

### Trên Ubuntu / Linux:
```bash
# Tạo môi trường ảo
python3 -m venv .venv

# Kích hoạt môi trường
source .venv/bin/activate
```

### Trên Windows (PowerShell / Command Prompt):
```powershell
# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường (PowerShell)
.venv\Scripts\Activate.ps1

# Hoặc kích hoạt môi trường (Command Prompt)
.venv\Scripts\activate.bat
```

> **Mẹo xác nhận:** Kiểm tra đường dẫn Python đang sử dụng trỏ đúng vào thư mục `.venv`:
> ```bash
> python -c "import sys; print(sys.executable)"
> ```

---

## 3. Cài đặt Package và Thư viện Phụ thuộc

Dự án quản lý thư viện qua chuẩn `pyproject.toml`. Cài đặt gói ở chế độ editable kèm toàn bộ công cụ dev:

```bash
python -m pip install -e ".[dev]"
```

Kiểm tra các thư viện cốt lõi đã sẵn sàng:
```bash
python -c "import networkx, simpy, numpy, pandas, matplotlib, scipy; print('Imports = OK')"
```

---

## 4. Chạy Kiểm thử và Xác nhận Môi trường

Chạy bộ kiểm thử khởi tạo và kiểm tra môi trường:

```bash
# 1. Chạy bài test môi trường và tính tái lập (độc lập)
python test_env.py

# 2. Chạy toàn bộ pytest suite (40 bài test)
python -m pytest -q

# 3. Kiểm tra chất lượng mã nguồn bằng Ruff
python -m ruff check .
```

---

## 5. Chạy Demo Mô phỏng Toàn diện Hệ thống

Chạy script demo để sinh dữ liệu mô phỏng và trực quan hóa:

```bash
python scripts/run_demo.py
```

Các đầu ra sinh tự động:
- `results/csv/topology_summary.csv`: Bảng tổng hợp topology ở 3 bán kính $R \in \{250, 300, 350\}$ m.
- `results/figures/topology_R*.png`: Biểu đồ trực quan hóa đồ thị mạng ở từng bán kính.
- `results/logs/simulation.log`: Nhật ký ghi log quá trình mô phỏng.
- `results/run_manifest.json`: Siêu dữ liệu tái lập (random seed, git commit, phiên bản thư viện).
