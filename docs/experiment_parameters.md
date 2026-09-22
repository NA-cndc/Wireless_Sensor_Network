# Tham số thí nghiệm

Tất cả giá trị dưới đây lấy từ `configs/default.json`; tài liệu không bổ sung
tham số nghiên cứu ngoài phạm vi đã xác định.

| Tên tham số | Ký hiệu | Giá trị | Đơn vị | Vai trò | Trạng thái |
|---|---:|---:|---|---|---|
| Chiều rộng vùng | $W$ | 3000 | m | Giới hạn trục X của miền mô phỏng | Cố định |
| Chiều cao vùng | $H$ | 3000 | m | Giới hạn trục Y của miền mô phỏng | Cố định |
| Số sensor | $N_s$ | 450 | node | Số node cảm biến đứng yên | Cố định |
| Số sink | $N_k$ | 7 | node | Số node thu thập không giới hạn năng lượng | Cố định |
| Năng lượng sensor ban đầu | $E_0$ | 5.0 | J | Trạng thái năng lượng khởi tạo | Cố định |
| Kích thước packet | $L$ | 128 | byte | Kích thước packet mặc định | Cố định |
| Chu kỳ packet | $T_p$ | 10 | s | Khoảng thời gian cấu hình/smoke timeout | Cố định |
| Bán kính truyền | $R$ | 250, 300, 350 | m | Ngưỡng khoảng cách để tạo cạnh | Chạy thử |
| Random seed | $s$ | 42 | không đơn vị | Tái lập tọa độ và tập cạnh | Cố định |

Tọa độ node tuân theo $0 \leq x \leq W$ và $0 \leq y \leq H$. Sensor và sink
đều đứng yên trong giai đoạn kiến trúc ban đầu.
