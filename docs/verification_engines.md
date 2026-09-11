# Hướng dẫn Kiểm chứng với các Simulator Bên Ngoài (Verification Engines)

Tài liệu này cung cấp hướng dẫn tích hợp và kiểm chứng mô phỏng mạng cảm biến không dây (WSN) trên các nền tảng mô phỏng mạng chuyên dụng: **ns-3**, **OMNeT++**, **INET Framework**, và **Contiki-NG**.

---

## 1. Danh sách các Engine Kiểm chứng (Verification Group)

| Engine | Kho lưu trữ chính thức | Ngôn ngữ | Vai trò kiểm chứng |
| :--- | :--- | :--- | :--- |
| **ns-3** | [gitlab.com/nsnam/ns-3-dev](https://gitlab.com/nsnam/ns-3-dev) | C++ / Python | Mô phỏng chính xác lớp vật lý (PHY), MAC IEEE 802.15.4, suy hao kênh truyền vô tuyến (LogDistance, Nakagami). |
| **OMNeT++** | [github.com/omnetpp/omnetpp](https://github.com/omnetpp/omnetpp) | C++ | Nền tảng mô phỏng sự kiện rời rạc hướng module với giao diện đồ họa Qtenv trực quan. |
| **INET** | [github.com/inet-framework/inet](https://github.com/inet-framework/inet) | C++ / NED | Bộ giao thức mạng mở rộng chạy trên OMNeT++, hỗ trợ WirelessHost, SensorNode, và mô hình tiêu thụ năng lượng vô tuyến. |
| **Contiki-NG** | [github.com/contiki-ng/contiki-ng](https://github.com/contiki-ng/contiki-ng) | C | Hệ điều hành nhúng thế hệ mới cho IoT, tích hợp bộ mô phỏng Cooja cho phép chạy trực tiếp firmware của sensor mote. |

---

## 2. Quy trình Kết nối & Xuất Topology từ Dự án

Dự án cung cấp module `wsn_sim.exporters` để xuất mạng $450$ cảm biến và $7$ trạm sink sang định dạng tương thích với các engine trên.

### Xuất tự động bằng Python API:
```python
from wsn_sim.config import SimulationConfig
from wsn_sim.network import Network
from wsn_sim.exporters import (
    export_to_ns3_mobility,
    export_to_omnetpp_ned,
    export_to_cooja,
)

# 1. Khởi tạo mạng WSN
config = SimulationConfig.from_json("configs/default.json")
network = Network(config, communication_range_m=300.0)

# 2. Xuất dữ liệu kiểm chứng
export_to_ns3_mobility(network, "results/ns3_wsn_mobility.tcl")
export_to_omnetpp_ned(network, "results/wsn_network.ned")
export_to_cooja(network, "results/cooja_sim.csc")
```

---

## 3. Hướng dẫn chi tiết từng Engine

### A. ns-3 (Discrete-Event Network Simulator)
1. **Mục đích**: Đối chiếu tỉ lệ phân phát gói tin (PDR) và trễ end-to-end với mô hình chuẩn 802.15.4.
2. **Sử dụng file mobility**:
   File `.tcl` được nạp vào ns-3 bằng `Ns2MobilityHelper`:
   ```cpp
   Ns2MobilityHelper ns2 = Ns2MobilityHelper("ns3_wsn_mobility.tcl");
   ns2.Install();
   ```

### B. OMNeT++ & INET Framework
1. **Mục đích**: Phân tích trực quan luồng dữ liệu truyền từ sensor về sink thông qua giao diện Qtenv, kiểm tra tình trạng nghẽn hàng đợi (Queue overflow) và tiêu hao năng lượng pin.
2. **Sử dụng file `.ned`**:
   Import file `wsn_network.ned` vào OMNeT++ project và cấu hình `omnetpp.ini`:
   ```ini
   [General]
   network = wsn.simulations.WsnNetwork
   *.radioMedium.pathLoss.typename = "LogNormalShadowing"
   *.radioMedium.backgroundNoise.power = -110dBm
   ```

### C. Contiki-NG & Cooja Simulator
1. **Mục đích**: Kiểm tra mã nguồn C nhúng thực tế (RPL, TSCH, CoAP) trên vi điều khiển (như Tmote Sky, Zolertia Z1).
2. **Sử dụng file `.csc`**:
   Mở Cooja:
   ```bash
   cd contiki-ng/tools/cooja
   ./gradlew run
   ```
   Chọn **File -> Open simulation -> `cooja_sim.csc`**. Tất cả 457 mote sẽ được định vị đúng tọa độ 3km x 3km theo seed ban đầu.
