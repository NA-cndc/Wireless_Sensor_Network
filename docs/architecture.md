# Kiến trúc phần mềm

## Luồng phụ thuộc

```text
Config
  ↓
Network + Models
  ↓
Simulation
  ↓
Metrics/Storage
  ↓
Visualization/Results
```

Các module phía dưới có thể phụ thuộc dữ liệu của tầng phía trên, nhưng model
không phụ thuộc storage hoặc giao diện. Cách chia này giữ cho logic khoa học có
thể được kiểm thử mà không cần tạo file hay figure.

## Trách nhiệm module

### `config.py`

`SimulationConfig` đọc JSON UTF-8, giữ toàn bộ tham số và từ chối kiểu dữ liệu,
kích thước, số node, năng lượng, packet hoặc bán kính không hợp lệ. Lớp này
không sinh node, không xây topology và không chọn route.

### `models/`

- `Sensor` giữ ID, tọa độ, năng lượng sống và các bộ đếm packet. Nó tính khoảng
  cách và cập nhật năng lượng không âm, nhưng không chứa routing hay công thức
  radio-energy.
- `Sink` giữ ID, tọa độ và tập ID packet duy nhất đã nhận. `receive()` bỏ qua ID
  trùng và đánh dấu packet hợp lệ là `DELIVERED`; sink không có trạng thái năng
  lượng.
- `Packet` giữ nguồn, kích thước, route, hop hiện tại, timestamp và trạng thái.
  `PacketStatus` phân biệt rõ `CREATED`, `IN_TRANSIT`, `DELIVERED`, `DROPPED`
  và `NO_ROUTE`.

### `network.py`

`Network` dùng `numpy.random.default_rng(seed)` để sinh tất cả tọa độ một lần.
Mỗi lần `build_graph(R)` tạo một `networkx.Graph` mới trên cùng bộ node. Một
cạnh sensor–sensor hoặc sensor–sink tồn tại khi khoảng cách Euclid không vượt
`R`; cạnh sink–sink luôn bị loại. Module cũng cung cấp neighbor, sensor cô lập,
sensor thuộc thành phần có sink và topology summary.

Routing không nằm trong `Network` vì graph mô tả kết nối vật lý, trong khi MHR,
EMHR và các chiến lược sau này là những chính sách độc lập có thể cùng chạy trên
một topology. Tách chúng giúp so sánh thuật toán mà không tái sinh mạng hoặc sửa
lớp domain.

### `simulation.py`

`Simulation` sở hữu hoặc nhận `simpy.Environment`. Giai đoạn hiện tại chỉ đưa
một process chứa `env.timeout()` vào hàng đợi và xác nhận đồng hồ mô phỏng tăng;
chưa sinh traffic và chưa chuyển packet qua route.

### `metrics.py`, `storage.py`, `visualization.py`

`metrics.py` biến các summary thành `pandas.DataFrame` theo schema ổn định.
`storage.py` lưu CSV/JSON bằng `pathlib.Path`, đồng thời tạo run manifest từ cấu
hình, phiên bản thư viện và các lệnh Git chỉ đọc. `visualization.py` dùng backend
Matplotlib `Agg`, biểu diễn sensor, sink và cạnh, rồi luôn đóng figure sau khi
lưu.

## Quan hệ đối tượng

`Network` sở hữu collection `Sensor`, `Sink` và graph. `Packet` hiện là model
độc lập; `Sink.receive(packet, time)` là điểm tương tác tối thiểu để quản lý giao
nhận. `Simulation` nhận một `Network` thay vì tự tạo topology, cho phép test và
thí nghiệm truyền vào đúng graph đã chọn. Lớp routing tương lai nên nhận graph,
trạng thái sensor và nguồn/đích, sau đó trả route cho `Packet.assign_route()`.
