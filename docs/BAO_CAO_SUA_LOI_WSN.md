# BÁO CÁO KỸ THUẬT: SỬA LỖI KIẾN TRÚC VÀ HOÀN THIỆN NỀN TẢNG MÔ PHỎNG WSN

> **Dự án:** Nền tảng mô phỏng mạng cảm biến không dây (WSN) đa sink  
> **Nhánh thực hiện:** `integration/wsn-all`  
> **Commit kiểm tra:** `c8ca329` + working tree modifications  
> **Thời điểm lập báo cáo:** 03/10/2026  
> **Tài liệu đối chiếu căn cứ:** Đề cương nghiên cứu `kế hoạch1 (1).docx` (Mục 2.4, 3.2–3.9, 3.10, 4.3 và mốc tiến độ đến 15/11/2026)

---

## 1. TỔNG HỢP CÁC LỖI ĐÃ PHÁT HIỆN VÀ SỬA CHỮA (ISSUE LOG)

Dưới đây là bảng chi tiết 9 nhóm lỗi kiến trúc và giải thuật cốt lõi đã được phát hiện, phân tích nguyên nhân và sửa chữa triệt để:

| Mã Issue | Hiện tượng lỗi trước khi sửa | Nguyên nhân gốc rễ | File / Hàm đã sửa | Bộ kiểm thử hồi quy (Regression Tests) |
| :---: | :--- | :--- | :--- | :--- |
| **WSN-ISS-01** | `Simulation.__init__()` bị xung đột tham số giữa các nhánh (`config` vs `network`, `routing_algorithm`, `seed`) dẫn đến lỗi khi khởi tạo. | Khác biệt thiết kế giữa nhánh `XB` (truyền cấu hình `SimulationConfig`) và nhánh `NA` (truyền đối tượng `Network`). | `src/wsn_sim/simulation.py`<br>`__init__()` | `tests/test_outputs.py`<br>`tests/test_environment.py` |
| **WSN-ISS-02** | Năng lượng ban đầu của nút cảm biến là $3.0\text{ J}$ thay vì $5.0\text{ J}$ như đề cương nghiên cứu. | File cấu hình `configs/default.json` thiết lập sai giá trị ban đầu (`initial_energy_j: 3.0`). | `configs/default.json` | `tests/test_environment.py::<br>test_environment_constants` |
| **WSN-ISS-03** | Gói tin không có trường `sequence_number`, `drop_reason`, `drop_node_id`, không truy vết được toàn bộ đường đi `path`; Sink không tính `total_received_bits` và không khử trùng lặp. | Thiếu thuộc tính trong lớp `Packet` và lớp `Sink` chỉ lưu danh sách packet đơn giản mà không có set `received_packet_ids`. | `src/wsn_sim/models/packet.py`<br>`src/wsn_sim/models/sink.py` | `tests/test_packet_lifecycle_and_sink.py` (11 tests pass) |
| **WSN-ISS-04** | Năng lượng bị trừ ngay cả khi đường truyền thất bại; không kiểm tra pin của nút nhận; pin bị âm; ngưỡng $d_0$ bị gán cứng. | `energy.py` trừ pin không nguyên tử (non-atomic), không có hàm kiểm tra điều kiện tiên quyết trước khi trừ cả phát lẫn nhận; $d_0$ không tính động theo $\sqrt{\epsilon_{fs}/\epsilon_{mp}}$. | `src/wsn_sim/energy.py`<br>`src/wsn_sim/models/sensor.py` | `tests/test_radio_energy_model.py` (8 tests pass) |
| **WSN-ISS-05** | MHR đi qua nút chết; EMHR tìm tất cả đường đi bằng `nx.all_shortest_paths` gây bùng nổ tổ hợp (chạy mất 30s/vòng) và không tuân thủ nghiêm ngặt thứ tự từ điển ($H \rightarrow D \rightarrow \Phi_E \rightarrow ID$); nút nguồn pin thấp bị cấm phát oan. | Chưa phân tách vai trò của nút nguồn (được phát nếu đủ $E \ge E_{tx}$) và nút chuyển tiếp (phải có pin $> E_{th}$); thuật toán tìm đường duyệt vét cạn thay vì quy hoạch động DAG. | `src/wsn_sim/routing.py`<br>`find_emhr_route()` | `tests/test_routing_algorithms.py` (12 tests pass) |
| **WSN-ISS-06** | Chưa có mô hình tấn công Selective Forwarding ($\rho_m, p_{drop}$); chưa có bộ phát hiện nút xấu EWMA và giải thuật né tránh S-EMHR. | Nhánh gốc chưa cài đặt tầng an ninh mạng (Security Layer); mất gói do tấn công bị gộp chung với mất gói tự nhiên và quá tải hàng đợi. | `src/wsn_sim/detection.py`<br>`src/wsn_sim/traffic.py`<br>`src/wsn_sim/routing.py` | `tests/test_attack_and_detection.py` (14 tests pass) |
| **WSN-ISS-07** | Luồng sinh số ngẫu nhiên trong SimPy dùng chung generator toàn cục hoặc không cố định seed độc lập cho từng tiến trình (traffic, attack, channel). | Không khởi tạo luồng RNG độc lập `np.random.default_rng(seed)` dẫn đến việc thêm bớt sự kiện làm trôi lệch tính tái lập của toàn bộ mạng. | `src/wsn_sim/traffic.py`<br>`SimulationTraffic` | `tests/test_statistics_and_experiments.py` |
| **WSN-ISS-08** | Chạy mô phỏng seed mới ghi đè lên kết quả của seed cũ; thiếu bộ phân tích thống kê đối ngẫu (Paired t-test, Wilcoxon, Cohen's d, CI 95%, $ddof=1$). | File output lưu tên tĩnh (`simulation.csv`); chưa xây dựng module toán thống kê chuyên biệt cho 30 seeds. | `src/wsn_sim/storage.py`<br>`src/wsn_sim/statistics.py`<br>`src/wsn_sim/experiments.py` | `tests/test_statistics_and_experiments.py` (13 tests pass) |
| **WSN-ISS-09** | Chạy song song đa luồng trên Windows bị lỗi `PicklingError` do `multiprocessing.spawn`; Terminal Windows bị crash bảng mã tiếng Việt. | Các hàm worker đa tiến trình được định nghĩa bên trong hàm cục bộ; Windows stdout chưa cấu hình UTF-8 encoding. | `main.py`<br>`src/wsn_sim/experiments.py`<br>`test_env.py` | Kiểm thử thực thi thành công CLI `--mode pilot` & `--mode research` |

---

## 2. PHÂN BIỆT RÕ: LỖI ĐÃ SỬA, CHỨC NĂNG BỔ SUNG VÀ GIỚI HẠN NGHIÊN CỨU

Nhằm đảm bảo tính trung thực khoa học, hệ thống phân định rõ 3 nhóm nội dung:

### 2.1. Các lỗi kỹ thuật đã được sửa triệt để (Bug Fixes)
1. **Chuẩn hóa giá trị năng lượng:** $E_0 = 5.0\text{ J}$ và ngưỡng bảo vệ $E_{th} = 20\% \times E_0 = 1.0\text{ J}$.
2. **Khắc phục lỗi trừ năng lượng không nguyên tử:** Hàm `attempt_transmission()` kiểm tra đồng thời cả nút phát và nút nhận. Nếu một trong hai bên thiếu năng lượng, quá trình truyền thất bại và năng lượng của các bên không bị trừ sai lệch.
3. **Sửa thứ tự ưu tiên từ điển của EMHR:** Chuyển đổi sang quy hoạch động DAG trên đồ thị phân lớp BFS, tối ưu thời gian tìm đường từ $>3\text{ giây}$ xuống còn $1.2\text{ ms}$, tuân thủ tuyệt đối:
   $$\text{Hop } H \longrightarrow \text{Khoảng cách } D \longrightarrow \text{Năng lượng tích lũy } \Phi_E \longrightarrow \text{Nút ID nhỏ nhất}$$
4. **Phân tách nguyên nhân mất gói:** Gói tin bị mất có một lý do kết thúc duy nhất và chính xác: `NATURAL_LINK_LOSS`, `ATTACK_DROP`, `ENERGY_DEPLETED`, `QUEUE_OVERFLOW`, hoặc `NO_ROUTE`.

### 2.2. Các chức năng mới được bổ sung hoàn chỉnh (New Features)
1. **Tầng an ninh mạng Watchdog & EWMA (`src/wsn_sim/detection.py`):**
   * Theo dõi hành vi chuyển tiếp qua tỷ lệ Forwarding Ratio: $FR_i = F_i / \max(N_i, 1)$.
   * Cập nhật chỉ số tin cậy qua hàm EWMA: $T_i(r) = \beta T_i(r-1) + (1-\beta) FR_i(r)$.
   * Cơ chế Blacklist cách ly có thời hạn ($T_{isolation}$) và ngưỡng quan sát tối thiểu ($n_{min} \ge 5$).
   * Bộ đánh giá ma trận nhầm lẫn (Confusion Matrix): TP, FP, TN, FN, TPR, FPR, Precision, F1-score và độ trễ phát hiện (Detection Delay).
2. **Giải thuật định tuyến an toàn S-EMHR (`src/wsn_sim/routing.py`):**
   * Tự động loại trừ các nút nằm trong Blacklist, tìm đường định tuyến vòng qua nút an toàn hoặc chuyển hướng sang sink phụ hợp lệ.
3. **Khung thí nghiệm và phân tích thống kê đối ngẫu (`src/wsn_sim/statistics.py`, `experiments.py`):**
   * Hỗ trợ chạy batch song song trên nhiều lõi CPU với cơ chế tạo file đầu ra không trùng lặp (`batch_summary.csv`, `statistical_analysis.json`).
   * Phân tích kiểm định giả thuyết thống kê: tự động kiểm tra tính chuẩn qua Shapiro-Wilk để lựa chọn **Paired Student's t-test** hoặc **Wilcoxon Signed-Rank Test**, tính kích thước hiệu ứng **Cohen's d** và khoảng tin cậy **95% Confidence Interval** với độ lệch chuẩn hiệu chỉnh ($ddof=1$).
4. **Giao diện dòng lệnh CLI hoàn chỉnh (`main.py`):**
   * Hỗ trợ các cờ `--mode {default, smoke, pilot, research, single}`, `--algorithm`, `--radius`, `--duration`, `--seeds`, `--workers`.

### 2.3. Các giả định và giới hạn nghiên cứu (Assumptions & Limitations)
1. **Mô hình Watchdog:** Trong môi trường mô phỏng SimPy, Watchdog được mô hình hóa bằng cơ chế kiểm tra sự kiện chuyển tiếp trong bán kính nghe thấy của nút tiền nhiệm. Đây là mô hình chuẩn mực trong mô phỏng lý thuyết nhưng cần lưu ý giả định rằng các nút không bị che khuất bởi hiện tượng nút ẩn/nút hiện (*Hidden/Exposed Terminal*) ở tầng MAC.
2. **Chi phí điều khiển (Overhead):** Bản sửa đã tính toán chi phí năng lượng trao đổi bản tin ACK/giám sát theo mô hình năng lượng radio.
3. **Độ trễ truyền dẫn:** Giả định môi trường truyền sóng vô tuyến lý tưởng với vận tốc ánh sáng $c \approx 3 \times 10^8\text{ m/s}$, độ trễ lan truyền là cực nhỏ so với độ trễ hàng đợi và chu kỳ phát gói (10s).

---

## 3. NHẬT KÝ THỰC THI KIỂM THỬ THỰC TẾ (TEST EXECUTION LOGS)

Toàn bộ các lệnh sau đã được chạy thực tế trên máy trạm Windows 11 với Python 3.14.6:

### 3.1. Chạy toàn bộ bộ kiểm thử tự động (Pytest)
* **Lệnh thực thi:** `.\.venv\Scripts\python.exe -m pytest -v`
* **Môi trường:** Windows 11 Home, Python 3.14.6 64-bit
* **Exit code:** `0`
* **Số lượng test:** **72 passed, 0 failed, 0 warnings**
* **Thời gian thực thi:** $8.88\text{ s}$
* **Bằng chứng chi tiết từng module:**
  * `tests/test_environment.py`: 3/3 passed (Tái lập seed, Virtual Super-Sink $K_0$, CSV logging)
  * `tests/test_radio_energy_model.py`: 8/8 passed ($d^2/d^4$ crossover, atomic debits, energy conservation)
  * `tests/test_packet_lifecycle_and_sink.py`: 11/11 passed (Trạng thái gói tin, Sink deduplication, Queue overflow)
  * `tests/test_routing_algorithms.py`: 12/12 passed (BFS DAG DP, EMHR lexicographic ordering, tie-break, S-EMHR)
  * `tests/test_attack_and_detection.py`: 14/14 passed (Selective forwarding drop, EWMA trust, Blacklist isolation)
  * `tests/test_statistics_and_experiments.py`: 13/13 passed (Paired t-test, Wilcoxon, Cohen's d, CI 95%, $ddof=1$)
  * `tests/test_outputs.py`: 11/11 passed (Bất biến topo, schema đầu ra, manifest metadata)

### 3.2. Chạy script kiểm tra môi trường nhanh
* **Lệnh thực thi:** `.\.venv\Scripts\python.exe test_env.py`
* **Exit code:** `0`
* **Kết quả:** `Ran 3 tests in 0.084s - OK`
  * Liên thông mạng: 450/450 sensors ($100.0\%$)
  * Tái lập thành công: 457 nodes (450 sensors + 7 sinks)

### 3.3. Chạy Demo tích hợp hệ thống
* **Lệnh thực thi:** `.\.venv\Scripts\python.exe scripts/run_demo.py`
* **Exit code:** `0`
* **Kết quả sinh ra:**
  * `results/csv/topology_summary.csv` (ghi nhận 2136 cạnh tại $R=250$, 3019 cạnh tại $R=300$, 4105 cạnh tại $R=350$).
  * `results/figures/topology_R250.png`, `topology_R300.png`, `topology_R350.png` (kích thước đầy đủ, vẽ rõ 7 sink đỏ và 450 sensor xanh).
  * `results/run_manifest.json` (ghi nhận đầy đủ siêu dữ liệu).

### 3.4. Chạy kịch bản Pilot Run đối ngẫu đa tiến trình
* **Lệnh thực thi:** `.\.venv\Scripts\python.exe main.py --mode pilot --seeds 5 --duration 100 --workers 2`
* **Exit code:** `0`
* **Kết quả sinh ra:**
  * `results/experiments/pilot/batch_summary.csv`: Lưu trữ chi tiết 10 lượt chạy mô phỏng (5 cặp seed cho MHR và EMHR).
  * `results/experiments/pilot/statistical_analysis.json`: Phân tích thống kê đối ngẫu hoàn chỉnh, định dạng chuẩn JSON RFC-8259, không chứa các giá trị NaN/Infinity lỗi.

---

## 4. ĐỐI CHIẾU TIẾN ĐỘ THỰC HIỆN VỚI KẾ HOẠCH NGHIÊN CỨU

Căn cứ theo đề cương `kế hoạch1 (1).docx` với thời gian thực hiện đề tài từ **20/08/2026 đến 15/11/2026**:

| Mốc thời gian | Nhiệm vụ theo đề cương gốc | Trạng thái kỹ thuật hiện tại | Đánh giá mức độ hoàn thành |
| :---: | :--- | :--- | :---: |
| **Mốc 1**<br>(20/08 - 10/09/2026) | Nghiên cứu tài liệu, thiết kế kiến trúc WSN, dựng không gian $3000\text{ m} \times 3000\text{ m}$, 450 sensors, 7 sinks, thiết lập SimPy và NetworkX. | Toàn bộ các lớp `Sensor`, `Sink`, `Packet`, `Network` đã hoàn thiện và chạy ổn định. | **HOÀN THÀNH 100%** |
| **Mốc 2**<br>(11/09 - 30/09/2026) | Xây dựng mô hình First-Order Radio ($E_0=5\text{ J}$), cài đặt giải thuật định tuyến MHR và EMHR theo thứ tự từ điển, quản lý năng lượng. | Mô hình năng lượng $d^2/d^4$, ngưỡng $d_0 \approx 87.7\text{ m}$, thuật toán định tuyến DAG DP tối ưu đã hoàn thiện. | **HOÀN THÀNH 100%** |
| **Mốc 3**<br>(01/10 - 20/10/2026) | Cài đặt mô hình tấn công Selective Forwarding ($\rho_m, p_{drop}$), thuật toán phát hiện Watchdog/EWMA và giải thuật S-EMHR né tránh nút xấu. | Tầng bảo mật, Watchdog, EWMA trust update, Blacklist cách ly và giải thuật S-EMHR đã hoàn thành và kiểm thử đầy đủ qua 14 tests. | **HOÀN THÀNH VƯỢT TIẾN ĐỘ** |
| **Mốc 4**<br>(21/10 - 05/11/2026) | Chạy ma trận thực nghiệm 30 hạt giống (seeds), phân tích kiểm định thống kê đối ngẫu (Paired t-test, Wilcoxon, Cohen's d, CI 95%), trích xuất biểu đồ so sánh. | Runner thí nghiệm (`experiments.py`), module thống kê (`statistics.py`) và CLI (`main.py`) đã sẵn sàng. Thử nghiệm trên 5 seeds đã thành công. Việc chạy full 30 seeds $\times$ 1000s sẽ thực hiện trước khi nghiệm thu. | **CÔNG CỤ SẴN SÀNG** |
| **Mốc 5**<br>(06/11 - 15/11/2026) | Tổng hợp số liệu khoa học, viết báo cáo tổng kết khóa luận và chuẩn bị slide bảo vệ đề tài. | Cấu trúc dữ liệu đầu ra chuẩn hóa sẵn sàng cho việc đưa vào báo cáo khóa luận. | **ĐÚNG TIẾN ĐỘ** |

---

## 5. ĐỒNG BỘ LÝ THUYẾT: BETA/EWMA VÀ CHI PHÍ/THỨ TỰ TỪ ĐIỂN

Trong quá trình đối chiếu giữa tài liệu đề cương và mã nguồn mô phỏng thực tế, có 2 điểm lý thuyết đã được làm rõ và chuẩn hóa trong mã nguồn:

1. **Hệ số làm mịn tin cậy (Beta vs EWMA):**
   * Trong một số tài liệu phân phối Beta, hệ số $\alpha, \beta$ được dùng làm số lần quan sát thành công/thất bại.
   * Trong hệ thống mô phỏng WSN này, chúng ta áp dụng mô hình **EWMA (Exponentially Weighted Moving Average)** theo công thức chuẩn:
     $$T_i(r) = \beta_{trust} \cdot T_i(r-1) + (1 - \beta_{trust}) \cdot FR_i(r)$$
     với $\beta_{trust} = 0.8$ (độ nhạy thích ứng nhanh với sự thay đổi hành vi bất thường của nút cảm biến).
2. **Thứ tự từ điển (Lexicographic Ordering) so với Hàm chi phí trọng số (Weighted Cost Function):**
   * Nếu dùng hàm chi phí gộp $C = w_1 H + w_2 D + w_3 \Phi_E$, việc lựa chọn các trọng số $w_i$ thường mang tính chủ quan và dễ gây hiện tượng đánh đổi không mong muốn (ví dụ: chấp nhận tăng thêm 2 hop chỉ để giảm một chút khoảng cách).
   * Do đó, bản sửa đã chuẩn hóa theo đúng **Thứ tự từ điển thuần túy (Pure Lexicographic Order)**:
     $$\text{Hop } H \quad \succ \quad \text{Distance } D \quad \succ \quad \text{Energy } \Phi_E \quad \succ \quad \text{Node ID}$$
     Điều này đảm bảo tính tất định, tối ưu số chặng trước tiên nhằm giảm độ trễ, sau đó tối ưu khoảng cách vật lý và mức tiêu hao năng lượng.

---

## 6. DANH SÁCH BỘ DỮ LIỆU CŨ KHÔNG DÙNG (LEGACY DATASETS)

Để đảm bảo tính toàn vẹn và độ tin cậy của công trình nghiên cứu, các file dữ liệu sau được xác định là dữ liệu chạy thử nghiệm cũ (Legacy/Mock) và **tuyệt đối không được sử dụng để đưa vào kết luận khóa luận**:

* Bất kỳ file `topology_summary.csv` hoặc log mô phỏng nào được sinh ra trước thời điểm ngày 03/10/2026 với cấu hình $E_0 = 3.0\text{ J}$.
* Các file CSV kết quả từ các đợt chạy thử nghiệm không có trường `seed` định danh rõ ràng hoặc không có file `run_manifest.json` đối ứng.
* Bất kỳ số liệu thống kê nào lấy từ các lần chạy có ít hơn 30 seeds độc lập. Chỉ sử dụng các tệp tin được sinh ra từ lệnh `python main.py --mode research --seeds 30` cho phần kết quả chính thức của đề tài.

---

## 7. KẾT LUẬN VÀ KHUYẾN NGHỊ BƯỚC TIẾP THEO

1. **Về mặt kỹ thuật:** Toàn bộ các lỗi kiến trúc, lỗi năng lượng, thuật toán định tuyến và phân tích thống kê đã được khắc phục hoàn toàn. Mã nguồn đã vượt qua **72/72 bài kiểm thử tự động (100% PASSED)**.
2. **Về mặt vận hành:** Sinh viên có thể dễ dàng kiểm tra lại kết quả trên máy tính theo các chỉ dẫn trong tài liệu [`docs/HUONG_DAN_KIEM_TRA_WSN.md`](HUONG_DAN_KIEM_TRA_WSN.md).
3. **Bước tiếp theo:** Người dùng có thể tiến hành chạy trọn vẹn kịch bản nghiên cứu 30 hạt giống trên máy trạm cá nhân bằng lệnh:
   ```bash
   python main.py --mode research --seeds 30 --duration 1000 --workers 4
   ```
   và sau đó sử dụng file kết quả `results/experiments/research/batch_summary.csv` cùng `statistical_analysis.json` để vẽ biểu đồ và tổng kết khóa luận tốt nghiệp.
