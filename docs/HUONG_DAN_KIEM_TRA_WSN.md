# HƯỚNG DẪN KIỂM TRA VÀ VẬN HÀNH NỀN TẢNG MÔ PHỎNG WSN

> **Dành cho:** Sinh viên năm 3 ngành Mạng máy tính, Kỹ thuật Viễn thông & Đồ án tốt nghiệp  
> **Dự án:** Nền tảng mô phỏng mạng cảm biến không dây (Wireless Sensor Network - WSN) đa sink  
> **Ngôn ngữ:** Python 3 (SimPy, NetworkX, NumPy, SciPy, pandas, Matplotlib)  
> **Mục tiêu:** Kiểm tra toàn diện kiến trúc mô phỏng, thuật toán định tuyến MHR / EMHR / S-EMHR, mô hình năng lượng First-Order Radio, cơ chế phát hiện tấn công Selective Forwarding và phân tích thống kê đối ngẫu 30 hạt giống (seeds).

---

## 1. PHẠM VI BẢN SỬA VÀ THÔNG TIN PHIÊN BẢN

* **Nhánh làm việc (Branch):** `integration/wsn-all` (nhánh tích hợp chính thức hợp nhất giữa nhánh `main/NA` và `origin/XB`).
* **Commit gốc tích hợp:** `c8ca329` (*Merge branch 'XB' into integration/wsn-all with resolved conflicts*).
* **Trạng thái làm việc (Working Tree):** Toàn bộ các module cốt lõi đã được tái cấu trúc, chuẩn hóa API, sửa lỗi năng lượng, thuật toán định tuyến, chống ghi đè dữ liệu và phân tích thống kê.
* **Ngày kiểm tra & xác nhận:** 03/10/2026.
* **Nguồn kế hoạch tham chiếu:** Bản đề cương nghiên cứu `kế hoạch1 (1).docx` (đối chiếu chi tiết các mục 2.4, 3.2–3.9, 3.10, 4.3 và mốc thời hạn 20/08/2026 – 15/11/2026).

---

## 2. BẢNG CÔNG CỤ & THƯ VIỆN BẮT BUỘC

| Công cụ / Thư viện | Phân loại | Phiên bản khuyến nghị | Vai trò trong hệ thống WSN |
| :--- | :---: | :---: | :--- |
| **Git** | Bắt buộc | $\ge 2.30$ | Quản lý mã nguồn, chuyển đổi nhánh, kiểm tra diff và commit |
| **Python** | Bắt buộc | $3.10 - 3.14$ | Ngôn ngữ thực thi chính của toàn bộ mô phỏng |
| **venv** | Bắt buộc | Tích hợp sẵn | Tạo môi trường ảo độc lập, cô lập dependencies |
| **NetworkX** | Bắt buộc | $\ge 3.0$ | Quản lý đồ thị topo mạng 2D, tính đường đi ngắn nhất, phân lớp BFS |
| **SimPy** | Bắt buộc | $\ge 4.0$ | Mô phỏng sự kiện rời rạc (Discrete-Event Simulation), quản lý tiến trình truyền tin và đồng hồ ảo |
| **NumPy** | Bắt buộc | $\ge 1.24$ | Tính toán ma trận khoảng cách, vector hóa tọa độ, quản lý seed ngẫu nhiên độc lập |
| **pandas** | Bắt buộc | $\ge 2.0$ | Xử lý dữ liệu bảng, trích xuất metrics, xuất kết quả CSV |
| **SciPy** | Bắt buộc | $\ge 1.10$ | Phân tích thống kê: kiểm định chuẩn Shapiro-Wilk, Student t-test ghép cặp, Wilcoxon signed-rank test |
| **Matplotlib** | Bắt buộc | $\ge 3.7$ | Trực quan hóa topo mạng $3000\text{ m} \times 3000\text{ m}$, xuất biểu đồ PNG không cần màn hình đồ họa (headless) |
| **pytest** | Bắt buộc | $\ge 7.0$ | Khung kiểm thử tự động toàn diện (72 bài kiểm thử) |
| **VS Code** | Khuyến nghị | Bản mới nhất | IDE soạn thảo mã nguồn, debug trực quan |
| **seaborn** | Tùy chọn | $\ge 0.12$ | Nâng cao thẩm mỹ các đồ thị phân phối (nếu vẽ báo cáo chuyên sâu) |

---

## 3. CÁC MÔI TRƯỜNG THỰC THI ĐƯỢC HỖ TRỢ

Hệ thống được thiết kế hướng tới tính di động đa nền tảng (cross-platform):

1. **Windows PowerShell / Command Prompt (CMD):**
   * Môi trường phát triển và kiểm thử thực tế trên máy trạm Windows.
   * Đã cấu hình chống lỗi bảng mã ký tự tiếng Việt (`UTF-8`) và khắc phục cơ chế tiến trình con `multiprocessing.spawn`.
2. **Ubuntu 24.04 LTS (Terminal / Native Linux):**
   * Môi trường server / máy ảo tiêu chuẩn.
   * Matplotlib được cấu hình tự động dùng backend `Agg` (Headless) nên chạy tốt ngay cả khi không có GUI (No X11 display).
3. **Ubuntu trong VMware Workstation / VirtualBox:**
   * Tương thích hoàn toàn tương tự Ubuntu Native.
4. **VS Code Remote - SSH tới Ubuntu:**
   * *Lưu ý quan trọng:* Đây là công cụ kết nối từ xa của VS Code đến máy Linux để lập trình và chạy lệnh, **không phải là một phần mềm mô phỏng mạng riêng biệt**.
5. **WSL2 (Windows Subsystem for Linux):**
   * Hoạt động tương đương Ubuntu Native.

> **Cảnh báo dành cho sinh viên:**  
> Hệ thống mô phỏng này được lập trình toán học và sự kiện rời rạc thuần túy bằng Python (`SimPy` + `NetworkX`), dựa trên mô hình năng lượng vô tuyến bậc một (*First-Order Radio Model*). **Không sử dụng và không được tích hợp vào các phần mềm mô phỏng thiết bị đồ họa như Cisco Packet Tracer, GNS3, ns-3, hoặc OMNeT++**.

---

## 4. THIẾT LẬP MÔI TRƯỜNG VÀ CHỌN PYTHON INTERPRETER

### 4.1. Nhận biết môi trường Terminal đang mở
* **Windows PowerShell:** Dòng nhắc lệnh thường có dạng: `PS C:\Users\...>` hoặc `PS D:\...>`
* **Windows CMD:** Dòng nhắc lệnh có dạng: `C:\Users\...>` hoặc `D:\...>`
* **Ubuntu / Linux Bash:** Dòng nhắc lệnh có dạng: `sinhvien@ubuntu:~$`

### 4.2. Khởi tạo môi trường ảo (Virtual Environment)

#### 🔹 Trên Windows PowerShell:
```powershell
# 1. Kiểm tra phiên bản Python và Git
python --version
git --version

# 2. Tạo môi trường ảo .venv tại thư mục gốc của dự án
python -m venv .venv

# 3. Cài đặt mã nguồn ở chế độ editable kèm gói dev
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 4. Kiểm tra xung đột phụ thuộc
.\.venv\Scripts\python.exe -m pip check

# 5. Kiểm tra import module mô phỏng
.\.venv\Scripts\python.exe -c "import wsn_sim; print('wsn_sim version:', wsn_sim.__file__)"
```

#### 🔹 Trên Windows CMD:
```bat
:: 1. Kiểm tra phiên bản
python --version
git --version

:: 2. Tạo môi trường ảo .venv
python -m venv .venv

:: 3. Cài đặt dự án
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"

:: 4. Kiểm tra phụ thuộc và import
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -c "import wsn_sim; print('wsn_sim version:', wsn_sim.__file__)"
```

#### 🔹 Trên Ubuntu / Linux Bash:
```bash
# 1. Kiểm tra phiên bản Python 3 và Git
python3 --version
git --version

# 2. Cài gói venv của hệ điều hành nếu chưa có, sau đó tạo .venv
sudo apt update && sudo apt install -y python3-venv python3-pip
python3 -m venv .venv

# 3. Cài đặt dự án
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"

# 4. Kiểm tra phụ thuộc và import
.venv/bin/python -m pip check
.venv/bin/python -c "import wsn_sim; print('wsn_sim version:', wsn_sim.__file__)"
```

### 4.3. Chọn đúng Python Interpreter trong VS Code
1. Nhấn tổ hợp phím `Ctrl + Shift + P` (hoặc `Cmd + Shift + P` trên macOS).
2. Gõ `Python: Select Interpreter` và nhấn Enter.
3. Chọn đường dẫn có đuôi `('.venv': venv)`:
   * Windows: `.\.venv\Scripts\python.exe`
   * Linux: `./.venv/bin/python`
4. Mở một terminal mới trong VS Code (`Ctrl + ~`), VS Code sẽ tự động kích hoạt môi trường ảo.

---

## 5. THAO TÁC VỚI GIT VÀ KIỂM TRA MÃ NGUỒN

Thay `<duong-dan-thu-muc-du-an>` bằng thư mục thực tế trên máy tính của bạn:

```bash
# Di chuyển vào thư mục dự án
cd <duong-dan-thu-muc-du-an>

# Kiểm tra nhánh hiện tại (phải là integration/wsn-all)
git branch --show-current

# Kiểm tra trạng thái git (working tree)
git status

# Xem thông tin commit mới nhất
git log -1 --stat
```

---

## 6. QUY TRÌNH CHẠY BỘ KIỂM THỬ TỰ ĐỘNG (TEST SUITE)

Bộ kiểm thử gồm **72 bài test** chia thành 7 nhóm module chức năng độc lập.

### 6.1. Chạy nhanh toàn bộ test và xuất file báo cáo

#### 🔹 Windows PowerShell:
```powershell
# Chạy toàn bộ 72 test hiển thị chi tiết tên từng test
.\.venv\Scripts\python.exe -m pytest -v

# Chạy dạng tóm tắt và ghi kết quả ra file text
.\.venv\Scripts\python.exe -m pytest -q *> pytest-result.txt
```

#### 🔹 Windows CMD:
```bat
# Chạy toàn bộ test
.venv\Scripts\python.exe -m pytest -v

# Xuất kết quả ra file
.venv\Scripts\python.exe -m pytest -q > pytest-result.txt 2>&1
```

#### 🔹 Ubuntu Bash:
```bash
# Chạy toàn bộ test
.venv/bin/python -m pytest -v

# Xuất kết quả ra file
.venv/bin/python -m pytest -q > pytest-result.txt 2>&1
```

### 6.2. Chạy kiểm thử theo từng module chuyên biệt

Khi cần kiểm tra sâu từng tính năng, sinh viên chạy từng lệnh tương ứng:

| Lệnh chạy kiểm thử (chạy trên PowerShell / CMD / Bash) | Mục đích kiểm tra | Số lượng test |
| :--- | :--- | :---: |
| `pytest tests/test_environment.py` | Kiểm tra seed tái lập, Virtual Super-Sink $K_0$, ghi log và xuất CSV | 3 tests |
| `pytest tests/test_radio_energy_model.py` | Kiểm tra mô hình tiêu hao năng lượng $d^2 / d^4$, ngưỡng $d_0$, atomic transmission | 8 tests |
| `pytest tests/test_packet_lifecycle_and_sink.py` | Kiểm tra trạng thái gói tin, deduplication tại Sink, FIFO queue, chống rò rỉ gói | 11 tests |
| `pytest tests/test_routing_algorithms.py` | Kiểm tra MHR, thứ tự từ điển EMHR ($H \rightarrow D \rightarrow \Phi_E \rightarrow ID$), S-EMHR tránh blacklist | 12 tests |
| `pytest tests/test_attack_and_detection.py` | Kiểm tra tấn công Selective Forwarding, EWMA trust update, Blacklist cách ly | 14 tests |
| `pytest tests/test_statistics_and_experiments.py` | Kiểm tra Paired t-test, Wilcoxon, Cohen's d, $ddof=1$, chạy thí nghiệm đối ngẫu | 13 tests |
| `pytest tests/test_outputs.py` | Kiểm tra tính bất biến của seed, chống ghi đè file kết quả và tạo manifest | 11 tests |

### 6.3. Chạy script kiểm tra môi trường nhanh (Zero-dependency check)
```bash
# Chạy script độc lập không cần pytest
python test_env.py
```
*Kết quả chuẩn:* Cả 3 test môi trường (thông số hằng số, tính tái lập seed, độ liên thông mạng $\ge 95\%$) đều đạt `OK`.

---

## 7. CÁC CẤP ĐỘ MÔ PHỎNG: SMOKE, PILOT VÀ RESEARCH BATCH

Giao diện dòng lệnh (`main.py`) hỗ trợ 4 chế độ chạy có cấp bậc rõ ràng:

### 7.1. Cấp độ 1: Smoke Demo (Kiểm tra nhanh khói - 10 đến 30 giây)
Mục đích: Xác thực rằng toàn bộ pipeline (tạo mạng, routing, truyền nhận gói tin, SimPy event loop, ghi file) vận hành trơn tru mà không xảy ra lỗi.
```bash
# Cách 1: Chạy demo mặc định tạo topo và ảnh trực quan hóa
python scripts/run_demo.py

# Cách 2: Chạy chế độ smoke qua main CLI (thời gian mô phỏng 30s)
python main.py --mode smoke --duration 30
```
* **Thời gian thực (Wall-clock):** ~1 – 3 giây.
* **Kết quả cần mở kiểm tra:**
  * `results/csv/topology_summary.csv`: Bảng thống kê số node (457), số cạnh, số sensor liên thông tại các bán kính $R \in \{250, 300, 350\}\text{ m}$.
  * `results/figures/topology_R250.png`, `topology_R300.png`, `topology_R350.png`: Ảnh vẽ topo không gian $3000\text{ m} \times 3000\text{ m}$.
  * `results/run_manifest.json`: Thông tin Git commit, Python version, OS và thông số seed.

### 7.2. Cấp độ 2: Mô phỏng 1 Seed duy nhất (Single Simulation)
Chạy thử nghiệm một kịch bản với thời gian mô phỏng ảo 100 giây:
```bash
# Chạy giải thuật EMHR với bán kính R=300m, thời gian ảo 100s
python main.py --mode single --algorithm emhr --radius 300 --duration 100 --seed 42
```
* **Thời gian thực (Wall-clock):** ~0.5 – 1.5 giây.
* **Kết quả cần kiểm tra:** Thư mục `results/single/` chứa file `metrics_emhr_R300_s42.json`.

### 7.3. Cấp độ 3: Pilot Run (Thử nghiệm thăm dò - 5 hạt giống)
Chạy thử nghiệm đối ngẫu giữa 2 giải thuật (MHR vs EMHR) trên 5 seeds để kiểm tra hàm thống kê:
```bash
python main.py --mode pilot --seeds 5 --duration 100 --workers 2
```
* **Thời gian thực (Wall-clock):** ~8 – 15 giây.
* **Kết quả cần kiểm tra:** Thư mục `results/experiments/pilot/` chứa:
  * `batch_summary.csv`: Thống kê PDR, năng lượng tiêu thụ, số hop trung bình từng seed.
  * `statistical_analysis.json`: Bảng kiểm định Paired t-test / Wilcoxon, Cohen's d và 95% Confidence Interval.

### 7.4. Cấp độ 4: Research Batch (Thí nghiệm nghiên cứu chính thức - 30 hạt giống)
Chạy toàn bộ 30 cặp seed độc lập theo đúng quy chuẩn thống kê khoa học:
```bash
# Khuyến nghị: Chạy 30 seed, duration 1000s với 4 worker song song
python main.py --mode research --seeds 30 --duration 1000 --workers 4
```
* **Thời gian mô phỏng ảo (Virtual simulation time):** $1000\text{ s}$ cho mỗi lượt chạy.
* **Thời gian thực tế (Wall-clock time):** Tùy thuộc vào tốc độ CPU của máy tính:
  * CPU 4 Cores: ~15 – 25 phút.
  * CPU 8 Cores / 16 Threads: ~5 – 10 phút.
* **Cách dừng (Stop):** Nhấn `Ctrl + C` tại cửa sổ terminal.
* **Kết quả cần mở kiểm tra:** Thư mục `results/experiments/research/` gồm:
  * `batch_summary.csv`
  * `statistical_analysis.json`

---

## 8. BẢNG ĐỐI CHIẾU HẠNG MỤC KẾ HOẠCH VỚI MÃ NGUỒN VÀ TIÊU CHÍ ĐẠT

| Hạng mục kế hoạch | File mã nguồn triển khai | Test kiểm thử tương ứng | Lệnh chạy kiểm tra | Tiêu chí đạt | Trạng thái |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **1. Topo & Nodes** (450 sensors, 7 sinks, $3000\text{ m} \times 3000\text{ m}$) | `src/wsn_sim/network.py`, `configs/default.json` | `tests/test_environment.py`, `tests/test_outputs.py` | `pytest tests/test_environment.py` | 457 tọa độ bất biến theo seed, bán kính $R \in \{250, 300, 350\}$, độ liên thông $\ge 95\%$ | **ĐẠT** |
| **2. Năng lượng Radio** ($d_0 = \sqrt{\epsilon_{fs}/\epsilon_{mp}} \approx 87.7\text{ m}$) | `src/wsn_sim/energy.py`, `models/sensor.py` | `tests/test_radio_energy_model.py` | `pytest tests/test_radio_energy_model.py` | $E_{tx} \sim d^2$ khi $d \le d_0$, $d^4$ khi $d > d_0$; trừ pin nguyên tử, pin không âm | **ĐẠT** |
| **3. Định tuyến MHR** (Đường đi ít hop nhất tới sink gần nhất) | `src/wsn_sim/routing.py` | `tests/test_routing_algorithms.py` | `pytest tests/test_routing_algorithms.py -k test_mhr` | Tìm đường theo BFS ngắn nhất, né tránh nút chết, trả về `None` khi mất liên thông | **ĐẠT** |
| **4. Định tuyến EMHR** (Từ điển $H \rightarrow D \rightarrow \Phi_E \rightarrow ID$) | `src/wsn_sim/routing.py` | `tests/test_routing_algorithms.py` | `pytest tests/test_routing_algorithms.py -k test_emhr` | Lọc nút có năng lượng $\le E_{th}$ ($1.0\text{ J}$), ưu tiên hop trước distance, determinism tie-break | **ĐẠT** |
| **5. Vòng đời Packet** (Deduplication, Queue, Status) | `src/wsn_sim/models/packet.py`, `models/sink.py`, `traffic.py` | `tests/test_packet_lifecycle_and_sink.py` | `pytest tests/test_packet_lifecycle_and_sink.py` | Gói tin có `sequence_number`, trạng thái chuyển hợp lệ, sink không nhận trùng | **ĐẠT** |
| **6. Tấn công Selective Forwarding** ($\rho_m, p_{drop}$) | `src/wsn_sim/traffic.py` | `tests/test_attack_and_detection.py` | `pytest tests/test_attack_and_detection.py -k test_attack` | Attacker ngẫu nhiên (không phải sink), chỉ drop gói quá cảnh, không drop gói tự sinh | **ĐẠT** |
| **7. Phát hiện EWMA & S-EMHR** (Watchdog, FR, Blacklist) | `src/wsn_sim/detection.py`, `routing.py` | `tests/test_attack_and_detection.py` | `pytest tests/test_attack_and_detection.py -k test_detector` | $T_i = \beta T_{i-1} + (1-\beta) FR_i$, đưa vào blacklist sau $K$ cửa sổ, S-EMHR né nút xấu | **ĐẠT** |
| **8. Phân tích Thống kê Đối ngẫu** (30 seeds, Paired t-test, Cohen's d) | `src/wsn_sim/statistics.py`, `experiments.py` | `tests/test_statistics_and_experiments.py` | `pytest tests/test_statistics_and_experiments.py` | Độ lệch chuẩn mẫu ($ddof=1$), khoảng tin cậy 95%, test tự động chọn Student-t hoặc Wilcoxon | **ĐẠT** |

---

## 9. HƯỚNG DẪN KIỂM TRA SÂU CÁC TÍNH NĂNG CỐT LÕI

### 9.1. Kiểm tra mô hình tiêu hao năng lượng (Energy Ledger)
* Nút cảm biến bắt đầu với $E_0 = 5.0\text{ J}$. Ngưỡng năng lượng dự phòng $E_{th} = 20\% \times E_0 = 1.0\text{ J}$.
* Mỗi bit dữ liệu truyền tốn $E_{elec} = 50\text{ nJ/bit}$. Truyền gói 128 bytes ($1024\text{ bits}$):
  * Nếu $d \le 87.7\text{ m}$: $E_{tx} = 1024 \times (50 \times 10^{-9} + 10 \times 10^{-12} \times d^2)\text{ J}$.
  * Nếu $d > 87.7\text{ m}$: $E_{tx} = 1024 \times (50 \times 10^{-9} + 0.0013 \times 10^{-12} \times d^4)\text{ J}$.
  * Năng lượng nhận: $E_{rx} = 1024 \times 50 \times 10^{-9} = 51.2\,\mu\text{J}$.
* **Kiểm tra atomic debit:** Nếu nút còn $10\,\mu\text{J}$ mà chi phí phát là $50\,\mu\text{J}$, lệnh truyền bị hủy bỏ, pin giữ nguyên, không bao giờ bị âm pin. Nút kế tiếp không bị trừ năng lượng vô lý.

### 9.2. Kiểm tra tính tối ưu từ điển của EMHR
* MHR chỉ chọn đường đi ít hop nhất bất kể pin của các nút trung gian.
* EMHR áp dụng nguyên tắc:
  1. Loại bỏ các nút láng giềng có năng lượng hiện tại $E_i \le E_{th}$ ($1.0\text{ J}$) khỏi vai trò chuyển tiếp (relay). Lưu ý: Bản thân nút nguồn dù dưới $1.0\text{ J}$ vẫn được phép phát gói tin của chính mình nếu còn đủ năng lượng phát ($E \ge E_{tx}$).
  2. Trong các đường đi hợp lệ, ưu tiên chọn đường có số chặng ($H$) nhỏ nhất.
  3. Nếu bằng số chặng, ưu tiên đường có tổng khoảng cách địa lý Euclid ($D$) ngắn nhất.
  4. Nếu vẫn bằng, chọn đường có mức tiêu hao năng lượng tích lũy ($\Phi_E$) thấp nhất.
  5. Giải quyết hòa (tie-break) bằng số ID của nút để đảm bảo tính tất định (deterministic).

### 9.3. Kiểm tra cơ chế Watchdog và Thuật toán Trust EWMA
* Mỗi nút giám sát láng giềng trong bán kính nghe thấy. Khi nút $A$ gửi gói cho nút $B$ để chuyển tiếp tới $C$, nút $A$ lắng nghe xem $B$ có phát lại gói đó hay không.
* Tỷ lệ chuyển tiếp gói: $FR_i = \frac{F_i}{\max(N_i, 1)}$.
* Giá trị tin cậy được làm mịn qua hàm EWMA:
  $$T_i(r) = \beta_{trust} \cdot T_i(r-1) + (1 - \beta_{trust}) \cdot FR_i(r)$$
* Nút bị đưa vào **Blacklist** khi và chỉ khi: có đủ ít nhất $n_{min} \ge 5$ quan sát và $T_i$ nằm dưới ngưỡng cảnh báo ($T_{th} = 0.6$) trong liên tiếp $K = 2$ cửa sổ trượt.
* Nút trong Blacklist bị cô lập trong khoảng thời gian $T_{isolation} = 100\text{ s}$ trước khi được phép xem xét tái hòa nhập mạng nếu cải thiện hành vi.

---

## 10. CÁCH ĐỌC VÀ PHÂN TÍCH CÁC TỆP DỮ LIỆU ĐẦU RA

Sau mỗi lượt chạy mô phỏng, hệ thống lưu kết quả tại thư mục `results/`:

### 10.1. File tóm tắt topo: `results/csv/topology_summary.csv`
* `radius_m`: Bán kính phát sóng vô tuyến ($250, 300, 350\text{ m}$).
* `num_sensors`: Tổng số cảm biến trong mạng (450).
* `num_sinks`: Tổng số trạm thu thập (7).
* `num_edges`: Tổng số liên kết vô tuyến vật lý trong đồ thị.
* `avg_degree`: Bậc trung bình của mỗi nút (số láng giềng trung bình).
* `routable_sensors`: Số lượng cảm biến có ít nhất 1 đường truyền hợp lệ đến 1 trong 7 sink.
* `isolated_sensors`: Số cảm biến bị cô lập (không có láng giềng).

### 10.2. File kết quả thí nghiệm: `results/experiments/.../batch_summary.csv`
* `seed`: Hạt giống số ngẫu nhiên của lượt chạy.
* `algorithm`: Thuật toán định tuyến (`mhr`, `emhr`, `s-emhr`).
* `pdr`: Tỷ lệ phát thành công gói tin (Packet Delivery Ratio):
  $$\text{PDR} = \frac{\text{Tổng gói nhận tại Sink}}{\text{Tổng gói sinh ra tại Sensor}}$$
* `throughput_bps`: Băng thông hiệu dụng của mạng (Bits/giây).
* `energy_consumed_j`: Tổng năng lượng tiêu hao trên toàn mạng (Joule).
* `avg_hops`: Số chặng trung bình mà một gói tin di chuyển từ nguồn đến sink.
* `fnd_time`: Thời điểm nút đầu tiên hết pin (First Node Death - giây). Nếu trong suốt thời gian chạy không có nút nào chết, giá trị được ghi là `null` (Censored data).

### 10.3. File phân tích thống kê: `statistical_analysis.json`
* `metric`: Chỉ số được so sánh (PDR, Energy, Hops).
* `mean_diff`: Hiệu số trung bình giữa 2 giải thuật ($\mu_1 - \mu_2$).
* `ci_95`: Khoảng tin cậy 95% của hiệu số trung bình `[lower, upper]`.
* `test_name`: Tên phép kiểm định (`paired_t_test` nếu dữ liệu thỏa mãn phân phối chuẩn, hoặc `wilcoxon_signed_rank` nếu vi phạm phân phối chuẩn).
* `p_value`: Trị số xác suất $p$. Nếu $p < 0.05$, sự khác biệt giữa 2 giải thuật có ý nghĩa thống kê.
* `cohen_d`: Kích thước hiệu ứng (Effect Size) theo công thức chuẩn: $|d| < 0.2$ (rất nhỏ), $0.5$ (trung bình), $> 0.8$ (lớn).

---

## 11. BẢNG MÃ LỖI THƯỜNG GẶP VÀ CÁCH KHẮC PHỤC

| Hiện tượng lỗi | Nguyên nhân gốc rễ | Hướng dẫn khắc phục |
| :--- | :--- | :--- |
| `'python' or 'py' is not recognized` | Chưa cài Python hoặc chưa tích chọn "Add Python to PATH" | Cài lại Python từ `python.org`, nhớ tích ô *"Add Python to PATH"*. |
| `ModuleNotFoundError: No module named 'wsn_sim'` | Chưa cài đặt gói `wsn_sim` vào môi trường ảo | Chạy lệnh: `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"` (Windows) hoặc `.venv/bin/python -m pip install -e ".[dev]"` (Linux). |
| `pip check báo thiếu thư viện hoặc xung đột` | Các thư viện ngoài bị cài thiếu hoặc sai phiên bản | Chạy `python -m pip install -r requirements.txt` hoặc cài trực tiếp qua `pip install -e ".[dev]"`. |
| `FileNotFoundError: configs/default.json` | Mở terminal ở sai thư mục làm việc (sai cwd) | Dùng lệnh `cd` để trỏ đúng vào thư mục gốc của repository (nơi chứa file `main.py`). |
| `UnicodeEncodeError: 'charmap' codec can't encode...` | Terminal Windows dùng bảng mã cũ (CP1252 / CP437) | Đã được xử lý tự động trong `main.py` qua `sys.stdout.reconfigure(encoding='utf-8')`. |
| `PicklingError: Can't pickle local object...` | Python trên Windows dùng cơ chế `multiprocessing.spawn` không serialize được hàm con | Các hàm worker đã được đưa lên cấp module (`src/wsn_sim/experiments.py`). Chú ý chạy script từ file `main.py`. |
| `PermissionError: [Errno 13] Permission denied: ...csv` | File CSV hoặc PNG đang được mở bởi ứng dụng khác (Excel, Photo Viewer) | Tắt file Excel hoặc cửa sổ xem ảnh đang mở trước khi chạy lại script mô phỏng. |
| `UserWarning: Matplotlib is currently using agg...` | Cảnh báo backend đồ họa headless | Đây là hoạt động hoàn toàn bình thường, đảm bảo mã nguồn chạy được trên server không có màn hình. |

---

## 12. CHECKLIST NGHIỆM THU VÀ XÁC NHẬN KẾT QUẢ

| Hạng mục kiểm tra | Môi trường đã xác nhận | Trạng thái thực tế |
| :--- | :---: | :---: |
| Bộ kiểm thử tự động 72/72 bài test | **Windows 11 / Python 3.14** | **100% PASSED** (thời gian chạy: 8.88s) |
| Script kiểm tra môi trường `test_env.py` | **Windows 11 / Python 3.14** | **100% PASSED** (3/3 tests) |
| Demo hệ thống `scripts/run_demo.py` | **Windows 11 / Python 3.14** | **THÀNH CÔNG** (sinh đủ 3 ảnh PNG, CSV, JSON) |
| Lệnh CLI Smoke `main.py --mode smoke` | **Windows 11 / Python 3.14** | **THÀNH CÔNG** (sinh đầy đủ metrics và log) |
| Lệnh CLI Pilot `main.py --mode pilot` | **Windows 11 / Python 3.14** | **THÀNH CÔNG** (5 seeds đối ngẫu, tính t-test) |
| Kiểm thử trên Ubuntu / Linux | **Ubuntu 24.04 (CI Setup)** | **ĐÃ CẤU HÌNH CI** (File `.github/workflows/ci.yml` sẵn sàng) |
| Nghiệm thu Research Batch (30 seeds $\times$ 1000s) | Toàn bộ môi trường | **CÔNG BỐ RÕ:** Đã kiểm thử chức năng runner thành công trên 5 seeds. Chạy trọn vẹn 30 seed ở thời gian ảo 1000s cho 450 node cần nhiều tài nguyên CPU và được khuyến nghị chạy trước khi viết báo cáo khóa luận chính thức. |

---

## 13. TÀI LIỆU THAM KHẢO VÀ LIÊN KẾT CHÍNH THỨC

* **Tài liệu Git chính thức:** [https://git-scm.com/doc](https://git-scm.com/doc)
* **Tài liệu Python Virtual Environments (venv):** [https://docs.python.org/3/library/venv.html](https://docs.python.org/3/library/venv.html)
* **Tài liệu NetworkX (Shortest Paths & Graph Algorithms):** [https://networkx.org/documentation/stable/](https://networkx.org/documentation/stable/)
* **Tài liệu SimPy (Discrete-Event Simulation):** [https://simpy.readthedocs.io/en/stable/](https://simpy.readthedocs.io/en/stable/)
* **Tài liệu Khung kiểm thử Pytest:** [https://docs.pytest.org/en/stable/](https://docs.pytest.org/en/stable/)
* **Tài liệu Thư viện Thống kê SciPy Stats:** [https://docs.scipy.org/doc/scipy/reference/stats.html](https://docs.scipy.org/doc/scipy/reference/stats.html)
* **Tài liệu First-Order Radio Model trong WSN (Heinzelman et al. - LEACH):** [https://doi.org/10.1109/HICSS.2000.926982](https://doi.org/10.1109/HICSS.2000.926982)
