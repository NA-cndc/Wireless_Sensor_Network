# WSN Chủ đề 3 — Kiến trúc mô phỏng ban đầu

Repository cung cấp nền tảng Python có khả năng tái lập cho mô phỏng Wireless
Sensor Network (WSN). Giai đoạn này mô hình hóa 450 sensor, 7 sink đứng yên
trong vùng Descartes 3 × 3 km và xây dựng đồ thị liên kết hai chiều ở các bán
kính 250 m, 300 m và 350 m.

## Cấu trúc chính

```text
Wireless_Sensor_Network/
├── configs/default.json           # Tham số thí nghiệm
├── src/wsn_sim/                   # Python package theo src-layout
│   ├── models/                    # Sensor, Sink, Packet
│   ├── config.py                  # Nạp và kiểm tra cấu hình
│   ├── network.py                 # Sinh node và đồ thị NetworkX
│   ├── simulation.py              # Smoke process SimPy
│   ├── metrics.py                 # Bảng tổng hợp pandas
│   ├── storage.py                 # CSV, JSON và run manifest
│   └── visualization.py           # Hình topology Matplotlib
├── scripts/run_demo.py            # Chương trình demo
├── tests/                         # Unit và integration tests
├── data/topologies/               # Dữ liệu topology dành cho mở rộng
├── results/{csv,figures,logs}/    # Kết quả sinh tự động
├── notebooks/                     # Ghi chú sử dụng notebook
└── docs/                          # Cài đặt, kiến trúc, tham số
```

Các thư mục khung có sẵn từ trước trong `src/wsn/`, `data/raw/` và
`data/processed/` được giữ nguyên để không ghi đè công việc của người dùng;
package được cấu hình và kiểm thử trong giai đoạn này là `wsn_sim`.

## Cài đặt trên Ubuntu

Yêu cầu Python 3.10 trở lên. Không cần và không nên dùng `sudo pip install`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pip check
python -c "import networkx, simpy, numpy, pandas, matplotlib; print('imports=OK')"
```

Chi tiết và cách xử lý lỗi môi trường nằm trong
[`docs/installation.md`](docs/installation.md).

## Kiểm thử và chạy demo

Sau khi kích hoạt `.venv`:

```bash
python -m pytest -q
python scripts/run_demo.py
```

Demo dùng `seed=42` để sinh đúng một bộ tọa độ, sau đó xây lại graph độc lập
cho từng bán kính mà không di chuyển node. Các đầu ra gồm:

- `results/csv/topology_summary.csv`: ba hàng tổng hợp topology.
- `results/figures/topology_R250.png`, `topology_R300.png`,
  `topology_R350.png`: hình mạng ở từng bán kính.
- `results/run_manifest.json`: cấu hình, phiên bản môi trường, Git metadata và
  danh sách file đã sinh.

Các đầu ra sinh tự động được `.gitignore` loại khỏi commit.

## Phạm vi đã hoàn thành

- Package `src-layout`, cấu hình JSON có xác thực và mô hình domain bằng
  `dataclass`.
- Sinh topology tái lập bằng NumPy và xây đồ thị vô hướng bằng NetworkX.
- Truy vấn neighbor, sensor cô lập và sensor liên thông tới ít nhất một sink.
- Smoke test SimPy, tổng hợp pandas, lưu CSV/JSON và vẽ Matplotlib headless.
- Unit test, integration test và tài liệu vận hành/kiến trúc.

## Chưa thực hiện

Giai đoạn này chưa triển khai MHR, EMHR/S-EMHR, radio-energy chi tiết,
Selective Forwarding, trust/forwarding ratio, traffic đầy đủ, FND/HND/LND,
PDR, throughput chính thức, ns-3/OMNeT++, dashboard web hoặc mô hình phần cứng.
Các nội dung đó có thể được bổ sung ở các module routing và simulation trong
giai đoạn sau mà không đặt thuật toán vào lớp `Network` hay `Sensor`.
