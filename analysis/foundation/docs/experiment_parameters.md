# Tham số thí nghiệm nền

| Tham số | Giá trị | Đơn vị |
|---|---:|---|
| Vùng tọa độ | 3.000 × 3.000 | m |
| Sensor và sink | 450 và 7 | nút |
| Năng lượng ban đầu mỗi sensor | 5 | J |
| Payload | 128 | byte/gói |
| Chu kỳ sinh gói | 10 | s |
| Bán kính pilot | 250, 300, 350 | m |
| Giới hạn thực nghiệm | 10.000 | s |
| Ngưỡng relay EMHR | α × E₀ với α = 0,20 | J |
| Mất kênh mỗi hop | 0,05 mặc định | xác suất |
| Seed cấu hình mặc định | 36 | không đơn vị |

Cấu hình nằm ở `configs/default.json`. Tọa độ của sensor và sink được lấy từ cùng
bộ sinh NumPy cho mỗi topology seed. Sink là điểm kết thúc và đồ thị duy trì các
cạnh sensor–sensor và sensor–sink vô hướng. Pilot dùng cùng 30 seed ở mọi bán kính
và ghi cả kết quả không đạt. Giữ R = 300 m theo đề xuất của Word khi bán kính này
đạt tiêu chí trên một nửa số topology. Mỗi topology đạt khi ít nhất 428/450 sensor
có đường đến sink.

## Mốc kết thúc và năng lượng

Mô phỏng xử lý các round từ giây 10 tới giây 10.000, gồm round 1.000. Tại giây
10.000, sensor còn sống sinh gói và các lần truyền đã bắt đầu được ghi nhận nếu
hoàn tất đúng mốc. Anten không bắt đầu lượt phát dữ liệu mới tại mốc chốt. Những
gói vẫn đang chờ hoặc truyền nhận lý do `simulation_end_duration_limit`. Khi
sensor cuối cùng hết pin, SimPy dừng tại đúng sự kiện đó, kể cả khi mốc đó trùng
giới hạn. Gói còn dang dở nhận lý do `simulation_end_lnd`. Hai cột `drop_reason`
và `cutoff_state` thể hiện kết cục và trạng thái chờ/truyền tại mốc dừng.

Mốc 10.000 giây là phạm vi điều chỉnh của thực nghiệm. Word §§2.4 và 3.5 đặt giới
hạn 10.000 round, tương ứng 100.000 giây với chu kỳ 10 giây.

TX được trừ đủ khi anten bắt đầu phát. Khi số dư thấp hơn chi phí TX, số dư được
dùng hết và gói nhận `energy_depletion` trước khi phát. Khi kênh làm mất gói, TX
đã phát vẫn được tính và đầu nhận không bị trừ RX. Chi phí beacon thuộc sổ năng
lượng riêng theo TX và RX. Mô hình giữ beacon 24 byte mỗi 50 giây cho các sensor
có đường ban đầu, với pha phát được tái lập bằng traffic seed. Hàng đợi TX FIFO
không giới hạn chiều dài, nên `queue_drop` mặc định bằng 0.

## Chỉ số và mẫu số

| Chỉ số | Định nghĩa |
|---|---|
| FND, HND, LND (s) | Thời điểm chết sensor đầu tiên, ít nhất một nửa ban đầu, hoặc sensor cuối cùng. |
| Payload tại mốc (bit) | Tổng bit payload các gói đã nhận đến hết thời điểm của mốc. |
| Functional death (s) | Thời điểm đầu tiên số sensor sống nối được tới sink dưới 50% số sensor sống trong đồ thị vật lý. Tỷ số có mẫu số dương. |
| PDR (%) | Gói nhận duy nhất chia cho tất cả gói đã sinh, gồm cả nguồn cô lập và gói còn dang dở tại mốc chốt. |
| Throughput, goodput (bit/s) | Bit dữ liệu đến sink chia cho thời gian SimPy thực chạy. Hai giá trị bằng nhau vì dữ liệu nhận chỉ chứa payload, beacon được mô hình riêng và không có retransmission. |
| Offered rate trung bình (bit/s) | Tổng bit đã sinh chia cho thời gian SimPy thực chạy. |
| Năng lượng trên bit nhận (J/bit) | Tổng Joule mất từ pin sensor, gồm beacon, chia cho số bit payload nhận. |
| Hop và trễ đầu cuối (s) | Trung bình trên gói đã nhận. Trễ là thời điểm nhận trừ thời điểm sinh, gồm cả thời gian đợi anten. |
| Tải relay và Jain | Đếm lần sensor thực sự phát gói quá cảnh, kể cả phát rồi mất trên kênh. Chỉ số Jain dùng toàn bộ sensor, gồm cả relay có tải bằng 0. |

JSON dùng `null` cho mốc chưa quan sát, payload tại mốc chưa quan sát và chỉ số
không có mẫu số. CSV tổng hợp giữ ô trống tương ứng và ghi số quan sát `n` cùng
số lượt thiếu `omitted`. Hay gặp trường hợp HND/LND chưa tới trước 10.000 giây.

## Ghép cặp và dữ liệu

Mỗi cặp dùng cùng topology seed, traffic seed và channel seed độc lập từ
`SeedSequence(36)`. Nguồn còn sống sinh gói đồng bộ theo chu kỳ. Beacon và lần
chọn sink đồng hạng trong MHR có dòng ngẫu nhiên tái lập. Giá trị ngẫu nhiên
của mất kênh được gắn với ID gói và cạnh có hướng; các thuật toán dùng cùng giá
trị khi truyền cùng gói trên cùng cạnh. MHR và EMHR dùng ba mức mất 0, 0,01 và
0,05. Độ nhạy EMHR thêm α = 0,10 và 0,30 tại mức mất 0,05.

Mỗi lượt ghi chuỗi thời gian CSV, tải từng relay CSV, dữ liệu gói CSV nén gzip
và JSON chứa cấu hình, seed, Git commit, mốc dừng và các chỉ số. Thống kê dùng
trung bình, SD mẫu và CI95 Student t. Bảng ghép cặp báo hiệu số theo từng seed,
phần trăm so với trung bình đối chứng trên đúng các cặp có dữ liệu và Cohen d_z.
Kiểm định cặp dùng t-test khi Shapiro–Wilk có p ≥ 0,05, hoặc Wilcoxon signed-rank
khi điều kiện đó không đạt. Các mốc chưa xảy ra không được gán bằng thời lượng.
