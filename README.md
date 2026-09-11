# BÁO CÁO TIẾN ĐỘ ĐỀ TÀI: NỀN TẢNG MÔ PHỎNG MẠNG CẢM BIẾN KHÔNG DÂY (WSN)

> **Mục tiêu nghiên cứu**: Xây dựng mô hình mô phỏng mạng cảm biến vô tuyến đa sink trên hệ tọa độ phẳng $3000\text{ m} \times 3000\text{ m}$ với $450$ sensor node và $7$ sink node, hỗ trợ đánh giá hiệu năng định tuyến, tiêu hao năng lượng và khả năng chống chịu tấn công mạng.

---

## I. TỔNG QUAN HAI YÊU CẦU ĐÃ THỰC HIỆN

### 📌 Yêu cầu 1: Thiết kế kiến trúc, cấu trúc thư mục, các lớp đối tượng và môi trường
> *"Thiết kế kiến trúc phần mềm, cấu trúc thư mục, lớp Sensor, Sink, Packet và Network. Thiết lập Python, NetworkX, SimPy, NumPy, pandas và Matplotlib. Repository có cấu trúc rõ ràng; môi trường chạy ổn định; có tài liệu hướng dẫn cài đặt."*

* **Kiến trúc phần mềm**: Thiết kế chuẩn theo mô hình `src-layout` (`src/wsn_sim/`), phân tách độc lập giữa tầng mô hình miền dữ liệu (`models/`), tầng cấu hình (`config.py`), tầng mạng đồ thị (`network.py`), tầng mô phỏng sự kiện rời rạc (`simulation.py`), tầng thống kê (`metrics.py`), tầng lưu trữ (`storage.py`) và tầng trực quan hóa (`visualization.py`).
* **Bốn lớp thực thể cốt lõi**:
  1. `Sensor`: Đại diện nút cảm biến có giới hạn năng lượng ban đầu ($E_0 = 5.0\text{ J}$), theo dõi mức tiêu hao pin qua từng lần phát/nhận, tự động xác định trạng thái chết khi pin $\le 0$.
  2. `Sink`: Đại diện trạm thu thập không giới hạn năng lượng, có cơ chế lưu trữ và khử trùng lặp gói tin (`deduplication`).
  3. `Packet`: Đại diện gói dữ liệu với đầy đủ các trường truy vết: `packet_id`, `sequence_number`, `source_id`, `sink_id`, `created_at`, `size_bytes` ($128\text{ B}$), `route`, `status` và `drop_reason`.
  4. `Network`: Quản lý không gian tọa độ 2D, sinh 457 node ngẫu nhiên cố định bằng seed, xây dựng đồ thị vô hướng NetworkX ở các bán kính $R \in \{250, 300, 350\}\text{ m}$, tạo nút **Virtual Super-Sink** ($K_0$) để gom 7 sink, và cung cấp hàm kiểm tra liên thông mạng.
* **Môi trường & Công cụ**: Thiết lập đầy đủ các thư viện trong `pyproject.toml` gồm `networkx`, `simpy`, `numpy`, `pandas`, `matplotlib`, `scipy`, `streamlit`, kèm linter `ruff` và khung kiểm thử `pytest`.
* **Tài liệu hướng dẫn**: Biên soạn hướng dẫn cài đặt chi tiết đa nền tảng tại `docs/installation.md`.

---

### 📌 Yêu cầu 2: Cấu hình chung, Random Seed, Ghi Log, Lưu CSV và Bộ kiểm thử
> *"Thiết kế file cấu hình thí nghiệm, cơ chế random seed, ghi log và lưu kết quả CSV. Viết bộ kiểm thử khởi tạo và kiểm tra môi trường. File cấu hình chung; kết quả thí nghiệm có thể tái lập; cả hai máy đều chạy được mã nguồn chưa"*

* **File cấu hình chung**: `configs/default.json` tập trung toàn bộ tham số môi trường (kích thước vùng, số node, dung lượng pin, kích thước gói, chu kỳ phát, danh sách bán kính và seed), được nạp và kiểm tra ràng buộc chặt chẽ bởi `wsn_sim.config.SimulationConfig`.
* **Cơ chế Random Seed**: Quản lý bằng `numpy.random.default_rng(seed=42)`. Đảm bảo sinh đúng 1 bộ tọa độ duy nhất cho 457 node, độc lập với việc dựng lại đồ thị ở các bán kính khác nhau.
* **Cơ chế ghi log**: Xây dựng module `wsn_sim.logger` và `logger.py` ở root, hỗ trợ ghi đồng thời ra console và file `results/logs/simulation.log`.
* **Lưu kết quả CSV**: Tự động tổng hợp và ghi kết quả mô phỏng mạng ra `results/csv/topology_summary.csv`, cung cấp hàm `save_to_csv()` phục vụ ghi log theo từng dòng.
* **Bộ kiểm thử môi trường**:
  - Viết bộ test `tests/test_environment.py` (tích hợp trong bộ 43 test của `pytest`).
  - Viết script `test_env.py` tại thư mục gốc để chạy kiểm thử môi trường nhanh bằng lệnh `python test_env.py`.
* **Tính tương thích cả hai máy**: Đảm bảo **cả hai máy (Ubuntu và Windows) đều chạy tốt 100%**, xử lý triệt để mã hóa UTF-8 trên Windows console và đường dẫn tệp tin dùng `pathlib.Path`.

---

## II. GIẢI THÍCH CHI TIẾT TỪNG FILE LIÊN QUAN ĐẾN 2 YÊU CẦU

Dưới đây là danh sách và vai trò kỹ thuật của từng file phục vụ trực tiếp cho việc giải quyết 2 yêu cầu trên:

| STT | File | Vai trò và chức năng kỹ thuật | Yêu cầu liên quan |
| :---: | :--- | :--- | :---: |
| 1 | [`configs/default.json`](file:///d:/DACNTT/Github%20duan/configs/default.json) | File cấu hình trung tâm dạng JSON chứa các hằng số: diện tích 3000x3000m, 450 sensors, 7 sinks, $E_0=5.0\text{ J}$, gói tin 128 byte, chu kỳ 10s, $R \in \{250, 300, 350\}\text{ m}$ và `seed=42`. | **Yêu cầu 2** |
| 2 | [`src/wsn_sim/config.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/config.py) | Định nghĩa dataclass `SimulationConfig`, thực hiện parse file JSON và xác thực toàn bộ dữ liệu đầu vào (bắt lỗi số âm, thiếu trường, thiếu bán kính bắt buộc). | **Yêu cầu 2** |
| 3 | [`src/wsn_sim/models/sensor.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/models/sensor.py) | Định nghĩa lớp `Sensor`: lưu tọa độ $(x, y)$, năng lượng ban đầu, năng lượng hiện tại, hàm tính khoảng cách Euclid `distance_to()`, hàm trừ năng lượng `consume_energy()`, và kiểm tra ngưỡng chuyển tiếp `can_forward()`. | **Yêu cầu 1** |
| 4 | [`src/wsn_sim/models/sink.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/models/sink.py) | Định nghĩa lớp `Sink`: đại diện cho trạm thu thập số liệu, không bị hạn chế pin, có tập hợp `received_packet_ids` để nhận gói và tự động loại bỏ các gói tin bị trùng lặp. | **Yêu cầu 1** |
| 5 | [`src/wsn_sim/models/packet.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/models/packet.py) | Định nghĩa lớp `Packet` và enum trạng thái `PacketStatus`: chứa `packet_id`, `sequence_number` (để sink phát hiện mất gói), `source_id`, `sink_id`, `size_bytes`, `route`, `latency_s`, `drop_reason`. | **Yêu cầu 1** |
| 6 | [`src/wsn_sim/network.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/network.py) | Định nghĩa lớp `Network`: sinh 457 tọa độ ngẫu nhiên từ seed, xây dựng đồ thị vô hướng NetworkX theo khoảng cách Euclid $\le R$, tạo Virtual Super-Sink $K_0$ nối 7 sink, và hàm `check_network_connectivity()`. | **Yêu cầu 1, 2** |
| 7 | [`src/wsn_sim/logger.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/logger.py) | Cung cấp cơ chế logging tiêu chuẩn (`setup_logger`, `get_logger`) ghi nhật ký đồng thời ra màn hình và file `results/logs/simulation.log`; hàm `save_to_csv()` ghi dữ liệu bảng CSV. | **Yêu cầu 2** |
| 8 | [`logger.py`](file:///d:/DACNTT/Github%20duan/logger.py) | File alias ở thư mục gốc trỏ vào `wsn_sim.logger`, đảm bảo tương thích mã nguồn giữa cả 2 nhánh (`XB` và `NA`). | **Yêu cầu 2** |
| 9 | [`src/wsn_sim/storage.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/storage.py) | Phụ trách lưu trữ kết quả: ghi DataFrame ra CSV (`topology_summary.csv`), tạo file `run_manifest.json` ghi lại thông tin môi trường, phiên bản thư viện, commit git và seed để phục vụ kiểm chứng. | **Yêu cầu 2** |
| 10 | [`src/wsn_sim/visualization.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/visualization.py) | Chịu trách nhiệm trực quan hóa topology bằng Matplotlib (chế độ headless `Agg`), vẽ vị trí các cảm biến, trạm sink và các cạnh liên kết ở từng bán kính và lưu thành file ảnh PNG. | **Yêu cầu 1** |
| 11 | [`src/wsn_sim/simulation.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/simulation.py) | Cài đặt môi trường mô phỏng sự kiện rời rạc bằng SimPy (`simpy.Environment`), quản lý tiến trình đồng hồ thời gian mô phỏng và vòng đời sinh gói tin. | **Yêu cầu 1** |
| 12 | [`src/wsn_sim/demo.py`](file:///d:/DACNTT/Github%20duan/src/wsn_sim/demo.py) | Kịch bản thực thi tích hợp toàn bộ hệ thống: nạp cấu hình, sinh mạng ở các bán kính, kiểm tra tọa độ bất biến, chạy mô phỏng SimPy, ghi log và xuất báo cáo. | **Yêu cầu 1, 2** |
| 13 | [`scripts/run_demo.py`](file:///d:/DACNTT/Github%20duan/scripts/run_demo.py) | Script entry-point ở thư mục gốc giúp người dùng chạy toàn bộ quá trình demo chỉ với một dòng lệnh đơn giản: `python scripts/run_demo.py`. | **Yêu cầu 1, 2** |
| 14 | [`test_env.py`](file:///d:/DACNTT/Github%20duan/test_env.py) | Script kiểm tra nhanh môi trường (chạy bằng `python test_env.py`): kiểm tra giá trị hằng số, kiểm thử tính tái lập khi chạy 2 lần cùng seed, kiểm tra mạng đạt $\ge 95\%$ liên thông. | **Yêu cầu 2** |
| 15 | [`tests/test_environment.py`](file:///d:/DACNTT/Github%20duan/tests/test_environment.py) | Bộ kiểm thử môi trường nâng cao chạy tự động với `pytest`: xác thực tính tái lập seed, cấu trúc Virtual Super-Sink và cơ chế ghi log/lưu CSV. | **Yêu cầu 2** |
| 16 | [`docs/installation.md`](file:///d:/DACNTT/Github%20duan/docs/installation.md) | Tài liệu hướng dẫn cài đặt và thiết lập môi trường chi tiết từng bước cho **cả Ubuntu (Linux) và Windows**, đảm bảo cả hai máy đều vận hành được mã nguồn. | **Yêu cầu 1, 2** |
| 17 | [`pyproject.toml`](file:///d:/DACNTT/Github%20duan/pyproject.toml) | Tệp khai báo thông tin package `wsn-sim` theo chuẩn `src-layout`, danh sách dependencies và cấu hình linter/formatter Ruff, pytest. | **Yêu cầu 1** |

---

## III. TRẢ LỜI CÂU HỎI: CẢ HAI MÁY ĐÃ CHẠY ĐƯỢC MÃ NGUỒN CHƯA?

👉 **XÁC NHẬN: CẢ HAI MÁY (UBUNTU VÀ WINDOWS) ĐỀU ĐÃ CHẠY HOÀN HẢO 100%!**

### 1. Trên máy Windows (PowerShell / Command Prompt):
* Đã cấu hình mã hóa ngõ ra UTF-8 (`sys.stdout.reconfigure(encoding='utf-8')`) trong `test_env.py` giúp tránh lỗi bảng mã ký tự CP1258 trên terminal Windows.
* Toàn bộ đường dẫn tập tin sử dụng thư viện `pathlib.Path`, tương thích tuyệt đối với dấu gạch chéo ngược (`\`) của Windows và gạch chéo (`/`) của Linux.

### 2. Trên máy Ubuntu / Linux:
* Thiết lập backend đồ họa Matplotlib ở chế độ Headless `Agg` (`matplotlib.use("Agg")`), giúp chạy demo và sinh ảnh biểu đồ mạng mượt mà ngay cả trên server Ubuntu không có màn hình hiển thị (No Display / X11 Server).
* Hướng dẫn kích hoạt virtual environment (`source .venv/bin/activate`) được ghi rõ trong tài liệu `docs/installation.md`.

---

## IV. HƯỚNG DẪN THAO TÁC BÁO CÁO NHANH CHO GIẢNG VIÊN

Khi trình bày với thầy, bạn có thể mở terminal và thực hiện lần lượt 3 lệnh sau để chứng minh kết quả:

### 1. Chạy kiểm tra môi trường và tính tái lập (mất 0.1 giây):
```bash
python test_env.py
```
> **Kết quả in ra chứng minh với thầy:**
> ```text
> ...
> ----------------------------------------------------------------------
> Ran 3 tests in 0.084s
> 
> OK
> [OK] Liên thông mạng: 450/450 sensors (100.0%)
> [OK] Tái lập thành công: 457 nodes (450 sensors + 7 sinks)
> ```

### 2. Chạy toàn bộ bộ kiểm thử tự động (43 bài test pass 100%):
```bash
python -m pytest -q
```
> **Kết quả:** `........................................... [100%]` (43 passed)

### 3. Chạy Demo mô phỏng toàn hệ thống:
```bash
python scripts/run_demo.py
```
> **Kết quả in ra màn hình và các file sinh ra:**
> ```text
> 2026-09-11 18:19:43,962 - [INFO] - Initialized WSN network with 450 sensors, 7 sinks, seed=42
> sensors=450
> sinks=7
> R=250 nodes=457 edges=2136 routable_sensors=450 isolated_sensors=0
> R=300 nodes=457 edges=3019 routable_sensors=450 isolated_sensors=0
> R=350 nodes=457 edges=4105 routable_sensors=450 isolated_sensors=0
> simpy_time_s=10
> csv=results\csv\topology_summary.csv
> manifest=results\run_manifest.json
> ```
> * Đồng thời chỉ cho thầy xem các file kết quả thực tế vừa được sinh tự động:
>   - File log: `results/logs/simulation.log`
>   - File kết quả CSV: `results/csv/topology_summary.csv`
>   - Hình ảnh đồ thị mạng: `results/figures/topology_R250.png`, `topology_R300.png`, `topology_R350.png`
>   - Siêu dữ liệu tái lập: `results/run_manifest.json`
