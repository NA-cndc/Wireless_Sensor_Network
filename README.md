# NỀN TẢNG MÔ PHỎNG MẠNG CẢM BIẾN KHÔNG DÂY (WSN) ĐA SINK

> **Dự án:** Nghiên cứu và đánh giá hiệu năng các giải thuật định tuyến (MHR, EMHR, S-EMHR), mô hình tiêu hao năng lượng và cơ chế an ninh mạng chống tấn công Selective Forwarding trên mạng cảm biến không dây quy mô lớn.  
> **Không gian mô phỏng:** $3000\text{ m} \times 3000\text{ m}$ gồm **450 sensor nodes** và **7 sink nodes**.  
> **Công nghệ:** Python 3, SimPy (Discrete-Event Simulation), NetworkX (Đồ thị), NumPy, pandas, SciPy, Matplotlib.  
> **Nhánh phát triển:** `integration/wsn-all` | **Trạng thái kiểm thử:** **72/72 tests PASSED (100%)**

---

## 📌 1. TỔNG QUAN HỆ THỐNG VÀ CÁC MODULE CỐT LÕI

Dự án được cấu trúc theo chuẩn `src-layout` (`src/wsn_sim/`), phân tách rõ ràng giữa các tầng chức năng:

* **Tầng cấu hình (`wsn_sim.config` / `configs/default.json`):**
  * Quản lý các tham số không gian: 450 sensors, 7 sinks, $E_0 = 5.0\text{ J}$, $E_{th} = 1.0\text{ J}$ (20%), kích thước gói 128 bytes, chu kỳ phát 10s, bán kính $R \in \{250, 300, 350\}\text{ m}$.
* **Tầng mô hình miền (`wsn_sim.models`):**
  * `Sensor`: Theo dõi tọa độ, năng lượng tiêu thụ phát/nhận, kiểm tra điều kiện phát $E \ge E_{tx}$ và chuyển tiếp $E > E_{th}$.
  * `Sink`: Trạm thu thập năng lượng vô hạn, tích hợp cơ chế khử trùng lặp (`deduplication`) và đo lường băng thông `total_received_bits`.
  * `Packet`: Quản lý vòng đời gói tin (`CREATED`, `IN_TRANSIT`, `DELIVERED`, `DROPPED`, `NO_ROUTE`), đánh số `sequence_number`, lưu vết đường truyền (`path`) và nguyên nhân dừng gói (`drop_reason`).
* **Tầng đồ thị và topo mạng (`wsn_sim.network`):**
  * Sinh 457 tọa độ ngẫu nhiên từ hạt giống (seed) cố định, xây dựng đồ thị vô hướng NetworkX theo khoảng cách Euclid $d \le R$.
  * Tích hợp nút ảo **Virtual Super-Sink ($K_0$)** để kết nối 7 sink phục vụ bài toán tìm đường đa sink tối ưu.
* **Tầng mô hình năng lượng radio (`wsn_sim.energy`):**
  * Mô hình *First-Order Radio Model* với ngưỡng khoảng cách tính động:
    $$d_0 = \sqrt{\frac{\epsilon_{fs}}{\epsilon_{mp}}} \approx 87.7\text{ m}$$
  * Tiêu hao năng lượng phát: $E_{tx} \sim d^2$ khi $d \le d_0$ và $E_{tx} \sim d^4$ khi $d > d_0$.
  * Tiêu hao năng lượng nhận: $E_{rx} = L \cdot E_{elec}$.
  * Trừ năng lượng theo cơ chế nguyên tử (`atomic transaction`), không bao giờ để pin bị âm và chỉ trừ khi cả nút phát và nhận đều đủ năng lượng.
* **Tầng thuật toán định tuyến (`wsn_sim.routing`):**
  * **MHR (Minimum Hop Routing):** Tìm đường đi có số chặng ít nhất tới trạm sink gần nhất, tự động tránh các nút đã chết pin.
  * **EMHR (Energy-aware Minimum Hop Routing):** Lọc bỏ các nút chuyển tiếp có năng lượng pin $E \le E_{th}$, tối ưu nghiêm ngặt theo **Thứ tự từ điển (Lexicographic Order)**:
    $$\text{Hop } H \quad \longrightarrow \quad \text{Khoảng cách } D \quad \longrightarrow \quad \text{Năng lượng tích lũy } \Phi_E \quad \longrightarrow \quad \text{Node ID nhỏ nhất}$$
  * **S-EMHR (Secure EMHR):** Định tuyến an toàn kết hợp danh sách Blacklist từ bộ phát hiện tấn công, né tránh các nút gian lận và tự động đổi trạm sink dự phòng nếu cần.
* **Tầng an ninh mạng và phát hiện tấn công (`wsn_sim.detection`):**
  * Mô hình tấn công **Selective Forwarding** với tỷ lệ nút xấu $\rho_m \in \{0, 0.02, 0.05, 0.10\}$ và xác suất hủy gói $p_{drop} \in \{0.25, 0.50, 0.75\}$. Nút xấu chỉ hủy gói tin quá cảnh, không hủy gói do chính mình sinh ra.
  * Giám sát hành vi qua cơ chế **Watchdog** và tỷ lệ chuyển tiếp $FR_i = F_i / \max(N_i, 1)$.
  * Cập nhật điểm tin cậy bằng hàm **EWMA**:
    $$T_i(r) = \beta_{trust} \cdot T_i(r-1) + (1 - \beta_{trust}) \cdot FR_i(r)$$
  * Tự động đưa nút vào **Blacklist** khi điểm tin cậy dưới ngưỡng trong liên tiếp $K$ cửa sổ trượt, cô lập trong thời gian $T_{isolation}$.
* **Tầng thống kê và thực nghiệm đối ngẫu (`wsn_sim.statistics`, `wsn_sim.experiments`):**
  * Phân tích mẫu với độ lệch chuẩn hiệu chỉnh ($ddof=1$) và khoảng tin cậy **95% Confidence Interval**.
  * Kiểm định phân phối chuẩn (Shapiro-Wilk) để tự động chọn **Paired Student's t-test** hoặc **Wilcoxon Signed-Rank Test**.
  * Đo lường kích thước hiệu ứng chuẩn hóa **Cohen's d**.
  * Hỗ trợ chạy batch đa tiến trình trên 30 seeds đối ngẫu, xuất dữ liệu JSON RFC-8259 và CSV không bị ghi đè.

---

## 🚀 2. HƯỚNG DẪN CÀI ĐẶT NHANH

### 2.1. Yêu cầu hệ thống
* Python $\ge 3.10$ (đã kiểm thử tương thích tuyệt đối trên Python 3.10, 3.11, 3.12, 3.14).
* Hệ điều hành: Windows 10/11 (PowerShell/CMD), Ubuntu 22.04/24.04 LTS, macOS.

### 2.2. Khởi tạo môi trường ảo và cài đặt dự án

#### Trên Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

#### Trên Linux / macOS (Bash):
```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
```

---

## 🧪 3. HƯỚNG DẪN CHẠY KIỂM THỬ VÀ MÔ PHỎNG

### 3.1. Chạy nhanh bộ kiểm thử tự động (72 tests)
```bash
# Windows
.\.venv\Scripts\python.exe -m pytest -v

# Linux
.venv/bin/python -m pytest -v
```
*Kết quả:* Toàn bộ 72 bài test đều vượt qua (**100% PASSED**) trong ~8-9 giây.

### 3.2. Chạy script kiểm tra môi trường nhanh
```bash
python test_env.py
```
*Kết quả:* Kiểm tra độ liên thông $100\%$, tái lập 457 nút và thông số chuẩn.

### 3.3. Chạy các chế độ mô phỏng qua CLI (`main.py`)

Hệ thống cung cấp giao diện dòng lệnh linh hoạt thông qua file `main.py`:

```bash
# 1. Xem hướng dẫn toàn bộ tham số CLI
python main.py --help

# 2. Chế độ Smoke (Kiểm tra nhanh luồng mô phỏng trong 30s)
python main.py --mode smoke --duration 30

# 3. Chế độ Single (Mô phỏng 1 kịch bản chi tiết)
python main.py --mode single --algorithm emhr --radius 300 --duration 100 --seed 42

# 4. Chế độ Pilot (Thử nghiệm thăm dò 5 seeds đối ngẫu MHR vs EMHR)
python main.py --mode pilot --seeds 5 --duration 100 --workers 2

# 5. Chế độ Research Batch (Nghiên cứu chính thức 30 seeds song song)
python main.py --mode research --seeds 30 --duration 1000 --workers 4
```

### 3.4. Chạy demo tạo đồ thị và ảnh topo
```bash
python scripts/run_demo.py
```
*Kết quả sinh ra tại thư mục `results/`:*
* `results/csv/topology_summary.csv`: Thống kê bậc, cạnh, độ liên thông ở $R \in \{250, 300, 350\}\text{ m}$.
* `results/figures/topology_R250.png`, `topology_R300.png`, `topology_R350.png`: Ảnh vẽ topo mạng.
* `results/run_manifest.json`: Siêu dữ liệu phiên bản, hệ điều hành và Git commit.

---

## 📊 4. TỔ CHỨC THƯ MỤC DỰ ÁN

```text
Wireless_Sensor_Network/
├── configs/
│   └── default.json             # File cấu hình tham số trung tâm của mạng WSN
├── docs/
│   ├── HUONG_DAN_KIEM_TRA_WSN.md# Cẩm nang 13 mục hướng dẫn kiểm tra chi tiết
│   ├── BAO_CAO_SUA_LOI_WSN.md   # Báo cáo kỹ thuật chi tiết lỗi và đối chiếu tiến độ
│   └── installation.md          # Hướng dẫn thiết lập môi trường đa nền tảng
├── results/
│   ├── csv/                     # Lưu trữ bảng thống kê topo mạng
│   ├── figures/                 # Lưu trữ biểu đồ và hình ảnh topo PNG
│   ├── logs/                    # Nhật ký mô phỏng chi tiết
│   └── experiments/             # Lưu trữ kết quả batch runs và kiểm định thống kê
├── scripts/
│   └── run_demo.py              # Script chạy demo nhanh hệ thống
├── src/
│   └── wsn_sim/                 # Gói mã nguồn cốt lõi (src-layout)
│       ├── models/              # Thực thể Sensor, Sink, Packet
│       ├── config.py            # Dataclass xác thực cấu hình
│       ├── detection.py         # An ninh mạng, Watchdog, EWMA trust detector
│       ├── energy.py            # Mô hình năng lượng First-Order Radio
│       ├── experiments.py       # Trình thực thi batch song song
│       ├── logger.py            # Quản lý ghi log console và file
│       ├── metrics.py           # Tính toán PDR, Throughput, Hops, Lifetime
│       ├── network.py           # Khởi tạo topo mạng, Virtual Super-Sink
│       ├── routing.py           # Thuật toán MHR, EMHR, S-EMHR
│       ├── simulation.py        # Quản lý tiến trình SimPy
│       ├── statistics.py        # Paired t-test, Wilcoxon, Cohen's d, CI 95%
│       ├── storage.py           # Lưu trữ kết quả và tạo run manifest
│       ├── traffic.py           # Cơ chế sinh gói tin, hàng đợi FIFO, tấn công
│       └── visualization.py     # Trực quan hóa đồ thị Matplotlib
├── tests/                       # 72 bài kiểm thử tự động toàn diện
├── .github/workflows/ci.yml     # Cấu hình kiểm thử tự động CI trên Windows & Ubuntu
├── main.py                      # Entry point dòng lệnh chính của hệ thống
├── pyproject.toml               # Khai báo gói, dependencies và cấu hình linter/test
├── test_env.py                  # Script kiểm tra nhanh tính sẵn sàng của môi trường
└── README.md                    # Tài liệu giới thiệu tổng quan hệ thống
```

---

## 📚 5. TÀI LIỆU CHI TIẾT DÀNH CHO BÁO CÁO VÀ NGHIÊN CỨU

1. **Hướng dẫn chi tiết dành cho người kiểm tra:** Vui lòng xem tài liệu [`docs/HUONG_DAN_KIEM_TRA_WSN.md`](docs/HUONG_DAN_KIEM_TRA_WSN.md) với 13 mục giải thích toàn diện, hướng dẫn từng lệnh trên PowerShell, CMD, Bash và cách phân tích từng cột dữ liệu CSV.
2. **Báo cáo kỹ thuật sửa lỗi và tiến độ đề tài:** Vui lòng xem tài liệu [`docs/BAO_CAO_SUA_LOI_WSN.md`](docs/BAO_CAO_SUA_LOI_WSN.md) để tra cứu bảng tổng hợp lỗi mã nguồn, nhật ký chạy test thực tế, đối chiếu mốc tiến độ nghiên cứu đến ngày 15/11/2026 và các lưu ý lý thuyết.
