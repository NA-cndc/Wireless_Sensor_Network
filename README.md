# Thiết kế Mạng cảm biến không dây (WSN) – Kiến trúc Multi-sink & Đánh giá Giao thức Định tuyến Tiết kiệm Năng lượng

Hệ thống mô phỏng sự kiện rời rạc bằng Python (SimPy + NetworkX) phục vụ nghiên cứu, tối ưu tốc độ tính toán và đối chứng định lượng các giao thức định tuyến nhận biết năng lượng trên kiến trúc Mạng cảm biến không dây đa trạm gốc đối xứng (Multi-sink WSN).

* **Đơn vị:** Khoa Công nghệ Thông tin – Trường Đại học Tôn Đức Thắng (TDTU)
* **Chuyên ngành:** Mạng máy tính và Truyền thông dữ liệu
* **Giảng viên hướng dẫn:** TS. Trần Thanh Nam
* **Nhóm thực hiện:**
  * Phạm Võ Nhật Anh – `52300176`
  * Nguyễn Xuân Bằng – `52300177`

---

## 1. Tổng quan mô hình mô phỏng

Hệ thống mô hình hóa sát điều kiện vận hành thực tế của mạng WSN phẳng trong chu kỳ dài hạn **$12\,000\,\text{s}$**:

* **Không gian & Cấu trúc mạng:** Vùng triển khai 2D kích thước $3000\,\text{m} \times 3000\,\text{m}$, gồm **$438$ nút cảm biến** phân bố ngẫu nhiên (`seed = 36`) và **$7$ trạm thu (Sink)** bố trí đối xứng đều trên bản đồ.
* **Mô hình năng lượng vô tuyến bậc nhất (First-Order Radio Model):** Áp dụng hai chế độ suy hao không gian tự do ($d^2$) và đa đường ($d^4$) với ngưỡng $d_0 = 87\,\text{m}$ cho cả quá trình truyền (TX) và nhận (RX). Năng lượng khởi tạo mỗi cảm biến là $5.0\,\text{J}$ (tổng toàn mạng $2190\,\text{J}$), trạm sink có nguồn năng lượng vô hạn.
* **Tầng MAC & Lưu lượng thực tế:**
  * Gói tin dữ liệu kích thước $128\,\text{bytes}$, băng thông $250\,\text{kbps}$, hàng đợi phát sóng đơn anten (`CSMA/CA` với `capacity = 1`).
  * Xác suất rớt gói do nhiễu kênh truyền vật lý là **$5\%$ trên mỗi chặng (hop)**.
  * Bản tin điều khiển trạng thái định kỳ (**Beacon**) kích thước $24\,\text{bytes}$ mỗi $50\,\text{s}$ trừ năng lượng phát và nhận thực tế của các nút láng giềng.
* **Tối ưu hiệu năng tính toán:** Áp dụng kỹ thuật duyệt dừng sớm (**Early Exit**) trên từ điển kề nội bộ và lưu đệm chi phí tĩnh/động (**Caching**), kết hợp chạy song song đa tiến trình (`ProcessPoolExecutor`), rút ngắn thời gian chạy toàn bộ $7$ kịch bản $12\,000\,\text{s}$ xuống còn khoảng $20\text{--}30\,\text{giây}$.

### Các thuật toán định tuyến được triển khai
1. **`MHR` (Minimum-Hop Routing):** Định tuyến số bước nhảy tối thiểu (chuẩn đối chứng).
2. **`EMHR` (Energy-Aware Minimum-Hop Routing):** Lọc ứng viên theo ngưỡng năng lượng trung bình láng giềng ($\alpha = 0.8, E > 0.1\,\text{J}$) kèm cơ chế dự phòng (Fallback).
3. **`Weighted_Dijkstra`:** Định tuyến Dijkstra tối ưu hàm chi phí kết hợp khoảng cách chuẩn hóa và nghịch đảo tỷ lệ pin còn lại ($\alpha = 2.0, \beta = 2.0$).
4. **`MMBCR` (Min-Max Battery Cost Routing):** Tối ưu hóa nút thắt cổ chai có mức pin thấp nhất trên toàn tuyến.
5. **`GPSR` (Energy-Aware Greedy Perimeter Stateless Routing):** Chuyển tiếp tham lam theo tọa độ địa lý kết hợp trọng số năng lượng và phục hồi vùng lõm.

---

## 2. Cấu trúc thư mục dự án

```text
.
├── main.py                  # Điểm khởi chạy chính: mô phỏng đa tiến trình & gọi hậu xử lý
├── run_analysis.py          # Hậu xử lý: vẽ topology, xuất biểu đồ PDF và in bảng thống kê
├── requirements.txt         # Danh sách thư viện Python yêu cầu
├── README.md                # Tài liệu hướng dẫn dự án
├── configs/
│   └── default.json         # Tham số cấu hình chuẩn của hệ thống WSN
├── src/
│   ├── config.py            # Đọc và kiểm tra tính hợp lệ của tham số cấu hình
│   ├── energy.py            # Tính toán tiêu thụ năng lượng vô tuyến bậc nhất (d^2 / d^4)
│   ├── network.py           # Khởi tạo sensor, sink đối xứng và đồ thị liên thông NetworkX
│   ├── routing.py           # Cài đặt và tối ưu hóa 5 thuật toán định tuyến
│   ├── simulation.py        # Điều phối tiến trình SimPy và xuất dữ liệu log CSV mỗi 10s
│   ├── traffic.py           # Sinh gói dữ liệu, bản tin Beacon, hàng đợi CSMA/CA và nhiễu kênh
│   ├── visualization.py     # Vẽ bản đồ cấu trúc mạng (Topology) vector PDF
│   └── models/              # Định nghĩa các lớp đối tượng cốt lõi (Sensor, Sink, Packet)
└── results/                 # Thư mục kết quả tự động tạo khi thực thi
    ├── csv/                 # Dữ liệu log mô phỏng từng kịch bản (*.csv)
    └── figures/             # Hệ thống biểu đồ phân tích định lượng (*.pdf)
```

---

## 3. Hướng dẫn cài đặt và chạy chương trình

### Yêu cầu môi trường
* Python **3.10** trở lên
* Các thư viện phụ thuộc: `simpy`, `networkx`, `numpy`, `pandas`, `matplotlib`

### Cài đặt thư viện
```bash
pip install -r requirements.txt
```

### Thực thi mô phỏng & phân tích
Chạy toàn bộ quy trình **2 giai đoạn** (Giai đoạn 1 khảo sát bán kính $R \in \{250\,\text{m}, 300\,\text{m}, 350\,\text{m}\}$ trên EMHR; Giai đoạn 2 đối chứng $5$ thuật toán tại $R = 300\,\text{m}$ trong $12\,000\,\text{s}$), tự động lưu CSV và xuất toàn bộ biểu đồ PDF:

```bash
python main.py
```

Nếu đã có sẵn dữ liệu log trong `results/csv/` và chỉ muốn xuất lại biểu đồ PDF cùng bảng thống kê gói tin ra màn hình:

```bash
python main.py --plot-only
```