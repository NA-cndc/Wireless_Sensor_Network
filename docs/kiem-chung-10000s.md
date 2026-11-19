# Đối chiếu nghiệm thu WSN 10.000 giây

Kế hoạch Word quy định các thông số mạng, tiêu chí phát hiện và thiết kế ghép cặp. Mốc đo chính cập nhật là 10.000 giây. Các dữ liệu lưu tại thời lượng 100.000 giây chỉ dùng để đối chiếu nguồn gốc.

| Nhóm | Triển khai và kiểm tra | Bằng chứng và giới hạn |
| --- | --- | --- |
| Topology và connectivity | `src/wsn_sim/network.py`, `python -m analysis.check_foundation` | 450 cảm biến, 7 sink, cùng tọa độ khi đổi bán kính. `pilot_topologies.csv` ghi 30 topology mỗi bán kính cho bộ nền. |
| Traffic và TX/RX | `src/wsn_sim/traffic.py`, `energy.py`, `tests/test_energy_traffic.py` | Gói 128 byte mỗi 10 giây. Tách TX, RX, mất liên kết và năng lượng. Các chi phí MAC và giám sát chưa mô hình hóa ghi NA. |
| MHR và EMHR | `src/wsn_sim/routing.py`, `tests/test_routing.py`, `tests/test_foundation_10000s.py` | MHR ưu tiên số hop. EMHR áp ngưỡng relay 1 J. Mô phỏng nền dùng `analysis/foundation`, phân tích cùng mô hình của nó. |
| Selective Forwarding | `src/wsn_sim/attacks.py`, `tests/test_attacks.py` | 2%, 5%, 10% và p_drop 0,25, 0,50, 0,75 trong thiết kế một yếu tố quanh mốc chính, gồm random và near_sink. Thiết kế này không ước lượng tương tác toàn phần. |
| Giám sát relay và S-EMHR | `detection.py`, `routing.py`, `tests/test_detector_observer.py`, `tests/test_semhr.py` | Observer lý tưởng, khóa stage78 cho gói công bố. Khóa dài hạn có bằng chứng hiệu chỉnh riêng, không dùng để đổi kết quả 480 lượt trước đó. |
| Metrics và censoring | `metrics.py`, `experiment_statistics.py`, `analysis/security_10000s/tables.py` | PDR, throughput, goodput, năng lượng/bit, hop, delay, FND/HND/LND, functional death, TPR/FPR/F1, detection delay và đổi tuyến. Mốc chưa quan sát có giá trị rỗng và số seed quan sát riêng. |
| Thí nghiệm ghép cặp | `analysis/run_foundation_study.py`, `analysis/security_10000s/study.py` | Bộ nền 8 cấu hình × 30 seed. Bộ bảo mật 16 cấu hình × 30 seed. Cặp có cùng seed, topology và attacker set theo cấu hình so sánh. |
| Thống kê và đồ thị | Lệnh tái tạo trong README | Mean, SD mẫu, CI 95%, kiểm định cặp. 12 PDF nền và 10 hình bảo mật có dữ liệu đầu vào kiểm tra được. |

`data/security_10000s.zip` giữ nguyên metadata lịch sử và fingerprint `55bb401b…`, kiểm bằng snapshot trong gói. Các ca nghiệm thu mới và khóa dài hạn dùng fingerprint `82df2484…`. Không gộp lượt từ hai mô hình hoặc hai thời lượng để tính thống kê chung.

Phép so ca đại diện so số nguyên, chuỗi, topology và CSV theo giá trị chính xác. Số thực dùng `atol=1e-9` và `rtol=1e-12`. Phép so bảng bảo mật dùng cùng dung sai, riêng p-value Shapiro dùng `atol=1e-8` để chấp nhận sai số số học giữa các bản thư viện. Các đường dẫn gốc, thời gian thực và metadata của đồ thị không tham gia so chỉ số.
