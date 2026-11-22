# Nghiệm thu mô phỏng nền 10.000 giây

Nghiên cứu được thực hiện trên nhánh `fix/wsn-foundation-10000s`, bắt đầu từ
commit `a217fc06a0040c0b564b88e95c18c9f46517c318`. Bộ mô phỏng nền trên `main`
nằm tại `analysis/foundation/`. Dữ liệu thô nằm tại
`results/backup/.wsn-foundation-10000s/results/study_10000s/`.

## Đối chiếu yêu cầu và bằng chứng

| Mục trong Word hoặc yêu cầu điều chỉnh | Bằng chứng |
|---|---|
| §§2.4, 3.5 · Profile 10.000 giây, chu kỳ 10 giây, dừng sớm LND | Hai manifest R = 300 m tại seed 36 ghi `elapsed_s=10000`, `rounds=1000` và `duration_limit`. Ca một sensor LND ghi `env.now=10`, mẫu CSV cuối `Time_s=10` và lý do `lnd`. Các test kiểm RX hoàn tất đúng mốc, TX qua mốc và sinh gói tại mốc. |
| §§3.2–3.3 · Sensor, sink, đồ thị và pilot | `tests/test_foundation_10000s.py` kiểm seed, cạnh Euclid và tương đương với virtual super-sink. Pilot giữ 90 dòng topology, mỗi mức 250, 300 và 350 m đều có 30/30 topology đạt ít nhất 95% kết nối. Giữ 300 m theo bán kính đề xuất của Word. |
| §§3.4–3.5 · Mô hình radio, bảo toàn pin và gói | Test mất kênh kiểm chứng vẫn tính TX và không tính RX sau mất kênh. Test nguồn cô lập tính cả gói không có đường. Sổ năng lượng và tổng gói được kiểm khi xuất từng lượt. Kiểm lại từng bản ghi gói từ các lượt MHR/EMHR R = 300 m bằng CSV nén. |
| §3.6.1 · MHR | BFS vẫn chọn tuyến tới lớp sink gần nhất. Test so với virtual super-sink ở R = 250, 300 và 350 m. |
| §3.6.2 · EMHR | Mạng nhỏ kiểm relay 0,5 J, relay 1 J, nguồn dưới ngưỡng, ưu tiên hop, khoảng cách và phạt pin. Trình định tuyến kiểm điều kiện đổi đường khi đường cũ mất hiệu lực và lưu `unreachable` khi hết đường. |
| §§3.6.3, 3.7, 3.8.8 và các cấu hình bảo mật ở §3.9 | Bộ mô phỏng S-EMHR và Selective Forwarding nằm tại `src/wsn_sim/`. |
| §§3.8.1–3.8.7 · Chỉ số nền | Manifest có FND/HND/LND, payload tại các mốc, functional death, PDR, throughput, goodput, J/bit, hop, trễ và độ cân bằng Jain. CSV relay có số gói chuyển tiếp từng sensor. Các mốc chưa quan sát dùng `null` và được đếm riêng khi tổng hợp. |
| §3.9 · Seed ghép cặp và thống kê | `results/study_10000s/run_index.csv` liên kết từng cấu hình với manifest. `summary.csv` và `paired_differences.csv` ghi số quan sát, mean, SD mẫu, CI95, chênh lệch và kiểm định cặp. |
| Demo, entry point và biểu đồ | Demo trả về 450 sensor, 7 sink và smoke test 10 giây. Bộ chuẩn vẽ lại 12 PDF cùng tên từ hồ sơ 10.000 giây. `results/figures/sources.json` ghi đường dẫn, SHA-256 dữ liệu CSV/JSON và commit từng lượt. |

## Kết quả kiểm chứng

Bộ test sau sửa có 48 đạt. Ma trận đã hoàn tất 240/240 lượt, gồm 180 lượt ở sáu
cấu hình MHR/EMHR theo ba mức mất kênh và 60 lượt ở hai cấu hình độ nhạy α. Cả
240 lượt có cùng ba seed trong mỗi cặp và bộ seed độc lập giữa 30 cặp. Bảng
nguyên nhân mất gói và sổ năng lượng được đối chiếu trên toàn bộ 240 manifest.
Tất cả dừng tại giây 10.000 với 1.000 round. Ở mức mất kênh 0,05, trung bình
PDR của MHR là 36,63% và của EMHR với α = 0,20 là 30,78%. Chênh lệch ghép cặp
EMHR − MHR là −5,85 điểm phần trăm, với CI95 từ −6,74 đến −4,96.

### Hồ sơ mặc định ở R = 300 m

| Thuật toán | Seed | Dừng (s) | Round | Sensor còn sống | Gói sinh | Gói nhận | PDR (%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| MHR tại 300 m | 36 | 10.000 | 1.000 | 248 | 294.137 | 115.465 | 39,26 |
| EMHR tại 300 m | 36 | 10.000 | 1.000 | 335 | 379.747 | 126.479 | 33,31 |

Hai lượt trong bảng đều dừng vì `duration_limit`, chưa tới HND và LND. Bảng hai dòng chỉ mô
tả một seed. Thống kê ghép cặp dùng 30 seed cho từng cấu hình. Lượt chạy lại
cùng seed có SHA-256 trùng nhau cho CSV chuỗi thời gian, CSV relay và CSV gói nén.
Thư mục dữ liệu `verification/` chứa các lượt kiểm chứng MHR, EMHR và ca dừng
sớm LND.

## Lệnh chạy

```bash
python -m pytest -q
python -m analysis.foundation.demo
python analysis/run_analysis.py
python analysis/run_analysis.py --plots-only
python analysis/run_foundation_study.py --report-only
python analysis/run_foundation_study.py --workers 10
```

`python analysis/run_analysis.py` chạy bảy kịch bản và dựng lại hình. Chuỗi thời gian
giữ tên `results/csv/simulation_log_<algo>_range_<R>m.csv`. Hồ sơ nghiên cứu lưu
file thô theo cặp trong `results/backup/.wsn-foundation-10000s/results/study_10000s/runs/` và bảng
tổng hợp trong `results/study_10000s/`. Chế độ `--report-only` đọc dữ liệu lưu trữ.
Để chạy lại đúng mã nguồn của ma trận, dùng commit
`4f8a73b23638942f993e069f7fe5b358d8c02264` ghi trong manifest.
Lượt GPSR trong bộ hình dùng `209a097a98e76704dccac3da722499d15d00dbd9` và dừng
đúng 10.000 giây sau khi sửa lỗi đường phục hồi đi qua một sink rồi tiếp tục
đến sink khác. Sáu kịch bản còn lại dùng nguồn `4f8a73b2`.

## Phạm vi thay đổi theo tệp

| Tệp hoặc nhóm tệp | Yêu cầu xử lý |
|---|---|
| `analysis/foundation/config.json`, `analysis/foundation/config.py` | Tập trung thời lượng 10.000 giây, α, mức mất và seed tái lập. Giữ seed mặc định 36. |
| `analysis/foundation/network.py` | Sinh đúng số node và tọa độ sink ngẫu nhiên. Tái sử dụng đồ thị để đo số sensor sống có đường. |
| `analysis/foundation/routing.py` | Giữ BFS của MHR, sửa điều kiện và ưu tiên EMHR, chốt đường phục hồi GPSR ở sink đầu tiên. |
| `analysis/foundation/simulation.py`, `analysis/foundation/traffic.py`, `analysis/foundation/models/packet.py` | Dừng SimPy đúng mốc, sinh gói từ mọi nguồn đang sống, tính vòng đời gói, TX/RX, payload, tải và mốc chết. |
| `analysis/foundation/storage.py` | Giữ tên CSV và lưu hồ sơ từng lượt. |
| `analysis/run_analysis.py`, `analysis/foundation/demo.py` | Dựng lại PDF từ CSV có thông tin nguồn và chạy demo topology. |
| `analysis/run_foundation_study.py` | Pilot, chạy cấu hình ghép cặp, tổng hợp SciPy và kiểm tra phiên bản nguồn. |
| `tests/test_foundation_10000s.py` | Kiểm EMHR, BFS, dừng thực tế, bảo toàn gói/TX và GPSR. |
| `analysis/foundation/docs/` | Tham chiếu kiến trúc, tham số và cài đặt từ nhánh nghiên cứu. |
| `docs/foundation_acceptance_10000s.md`, `results/figures/`, `results/study_10000s/` | Bảng đối chiếu, biểu đồ thay thế, provenance và dữ liệu nghiệm thu. |
