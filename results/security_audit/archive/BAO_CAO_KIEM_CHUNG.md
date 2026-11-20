# Kiểm tra Selective Forwarding và giám sát relay ngày 17 tháng 11 năm 2026

Hai module đã hoạt động đúng chức năng cơ bản. Công việc này bổ sung truy nguyên cảnh báo nhầm, đối chứng benign đủ 10.000 giây, hiệu chỉnh có đăng ký protocol, freeze mới và đánh giá trên seed độc lập. Đã giữ nguyên thư mục dự án gốc vì phiên thực thi chỉ có quyền đọc ổ F. Các thay đổi được hoàn thiện trong bản sao và bàn giao qua bản vá có kiểm tra hash cùng sao lưu.

Trên30 seed mới của S-EMHR, FPR giảm từ9.70% xuống1.83%; precision tăng từ34.50% lên71.71%. Đổi lại, TPR giảm từ87.10% xuống81.30%, coverage giảm từ87.47% xuống79.34%, delay capped trung bình tăng từ1777.2s lên2489.3s. PDR thay đổi từ31.782% lên31.849%; CI95 của chênh lệch cặp bao gồm0 nên chưa đủ bằng chứng kết luận tăng PDR.

## Kết luận có bằng chứng

- Baseline: 303 kiểm thử đạt. Script kiểm chứng attacker và detector đều đạt. Đối chiếu lại 60 summary gốc khớp TP, FP, FN và các giá trị trung bình đã nêu.
- Ca SF3 seed51001 tái hiện khớp toàn bộ performance và security của dữ liệu gốc: TP=17, FP=49, FN=6.
- Cả 894 timeout của relay lành trong ca đó đều gắn với `unreachable`; đối chiếu quyết định reroute cho thấy nguyên nhân `relay_energy`, khi relay xuống dưới Eth=1J. Đây là chứng cứ trong một ca cụ thể, không suy rộng thành nguyên nhân duy nhất ở mọi topology.
- Không đưa attacker_ids, drop_reason hoặc năng lượng vào detector. Việc nối nguyên nhân mất gói chỉ diễn ra sau mô phỏng.
- K chỉ quyết định cách ly; tăng K không thay đổi điều kiện suspected hoặc FPR ever_suspected trên cùng chuỗi quan sát. Đã bổ sung phản ví dụ kiểm thử cho khác biệt này.
- Bộ mới: beta=0.8, W=80s, N_min=10, tau=0.95, K=2, timeout=0.02s, cách ly=60.0s.

Ba cửa sổ cảnh báo nhầm đầu tiên của ca chẩn đoán:

| Relay lành | Thời điểm s | N | F | FR | Trust trước | Trust sau |
|---|---:|---:|---:|---:|---:|---:|
| sensor_071 | 480 | 13 | 4 | 0.307692 | 1.000000 | 0.861538 |
| sensor_160 | 600 | 9 | 6 | 0.666667 | 1.000000 | 0.933333 |
| sensor_147 | 800 | 26 | 17 | 0.653846 | 1.000000 | 0.930769 |


Ví dụ sensor_071: FR=4/13=0.307692; trust mới=0.8×1+0.2×0.307692=0.861538, nhỏ hơn0.95 nên bị nghi ngờ. Log reroute và trạng thái pin cho thấy các gói không chuyển tiếp được do relay xuống dưới Eth. Một gói khác tại sensor_212 có pin0.994043J khi bị loại: node vẫn sống nhưng không còn hợp lệ làm relay theo Eth=1J, nên gói ghi unreachable với nguyên nhân reroute relay_energy. Điều này khác energy_depletion khi không đủ năng lượng TX/RX, và khác selective_forwarding. Detector chỉ thấy RX rồi không thấy TX nên có thể cảnh báo nhầm; không được sửa bằng cách cho detector đọc nhãn drop_reason.

## Quy trình hiệu chỉnh

Protocol và kiểm kê seed được lưu trước khi thu dữ liệu fit mới. Nhóm seed ban đầu dự kiến 71001/72001 đã bị kiểm tra trùng chặn trước khi chạy fit; bộ cuối dùng fit171001..171006, benign validation172001..172004, attack validation173001..173004, evaluation174001..174030. Bốn tập tách biệt và không dùng seed51001..51030 để chọn tham số.

18 lượt benign fit = 6 seed × 3 mức mất kênh. Lưới gồm 216 bộ tham số; tính FR/EWMA từ phép chiếu RX/TX không chứa nhãn tấn công. K không đi vào phép chiếu ever_suspected. K=2 là quy tắc phá hòa đã đăng ký, không phải bằng chứng K giảm FPR. Đã đối chiếu lại candidate được chọn với ForwardingDetector thật trên một trace của mỗi mức kênh, so sánh từng node về trust, số cửa sổ hợp lệ và thời điểm nghi ngờ đầu tiên.

Sau fit, kiểm tra một biên số học tổng quát phát hiện phép cộng float0.1+0.2 có thể làm bộ phân tích tăng tốc coi TX đúng deadline0.3 là thành công. Detector lõi đã xử lý đúng bằng Decimal. Đã gia cố nhánh gần deadline của công cụ phân tích và thêm phản ví dụ hồi quy. Kiểm tra cả3.735.890 quan sát trong18 trace fit cho thấy không có TX nào rơi vào nhánh bị sửa; các ma trận N/F, cả216 điểm ứng viên và bộ được chọn vì vậy giữ nguyên. Đây là sửa biên của công cụ phân tích, không thay mô hình hoặc hiệu chỉnh trên evaluation. Hash đăng ký ban đầu, selection, source lõi và freeze được giữ nguyên; thay đổi được công bố trong analysis_boundary_fix.json và final_analysis_provenance.json.

Chọn candidate chỉ từ fit và lưu selection trước validation. Sau đó chạy 12 benign validation và 12 attack validation, kiểm tra P_drop=0.25/0.50/0.75. Các cổng benign=True, attack=True. Nếu một cổng thất bại thì không được tạo CALIBRATED hoặc chọn lại trên validation. Freeze mới được lưu trước evaluation, kèm hash nguồn, protocol, tham số và chứng cứ validation. Validator đã có kiểm thử từ chối chứng cứ bị sửa và cổng attack thất bại.

## Kết quả đánh giá trên 30 seed mới

Các ô dưới đây ghi mean ± std mẫu và CI95 Student-t theo seed. FPR, TPR, precision và coverage dùng đơn vị phần trăm. CI là ước lượng hữu hạn trên các seed này, không bảo đảm tổng thể cho mọi topology. Các nhóm SF2 dùng cùng luồng vật lý cho bộ mới và observer cũ; hai observer không thay đổi định tuyến EMHR. Hai nhóm SF3 được chạy riêng, dùng cùng topology, traffic, link-loss seed và attacker set.

Nhóm tấn công chính dùng rho danh nghĩa5%, P_drop=0.5, placement=random và mất kênh1%. Quy tắc half-up chọn23/450 attacker, tỷ lệ thực5.111%; không ghi nhầm thành đúng22.5 node hoặc đúng5% thực tế.

| Nhóm | Kênh mất gói | Bộ | FPR % | TPR % | Precision % | Coverage % |
|---|---:|---|---|---|---|---|
| eval_benign | 0 | old | 6.933 ± 2.307 [6.072; 7.795] | NA | 0.000 ± 0.000 [0.000; 0.000] | 85.607 ± 2.789 [84.566; 86.649] |
| eval_benign | 0 | new | 2.000 ± 0.819 [1.694; 2.306] | NA | 0.000 ± 0.000 [0.000; 0.000] | 78.422 ± 3.760 [77.018; 79.826] |
| eval_benign | 0.01 | old | 7.015 ± 2.840 [5.954; 8.075] | NA | 0.000 ± 0.000 [0.000; 0.000] | 85.637 ± 2.739 [84.614; 86.660] |
| eval_benign | 0.01 | new | 1.696 ± 0.812 [1.393; 1.999] | NA | 0.000 ± 0.000 [0.000; 0.000] | 78.259 ± 3.772 [76.851; 79.668] |
| eval_benign | 0.05 | old | 7.230 ± 2.429 [6.323; 8.136] | NA | 0.000 ± 0.000 [0.000; 0.000] | 85.681 ± 2.946 [84.581; 86.782] |
| eval_benign | 0.05 | new | 1.652 ± 0.597 [1.429; 1.875] | NA | 0.000 ± 0.000 [0.000; 0.000] | 78.089 ± 4.266 [76.496; 79.682] |
| eval_SF2 | 0.01 | old | 7.283 ± 2.276 [6.434; 8.133] | 85.942 ± 7.193 [83.256; 88.628] | 40.291 ± 8.504 [37.116; 43.467] | 85.719 ± 2.625 [84.738; 86.699] |
| eval_SF2 | 0.01 | new | 1.710 ± 0.967 [1.349; 2.071] | 79.420 ± 7.124 [76.760; 82.081] | 73.033 ± 10.166 [69.237; 76.829] | 78.193 ± 3.996 [76.701; 79.685] |
| eval_SF3 | 0.01 | old | 9.703 ± 3.616 [8.353; 11.054] | 87.101 ± 6.990 [84.491; 89.712] | 34.497 ± 8.662 [31.263; 37.732] | 87.467 ± 2.817 [86.415; 88.519] |
| eval_SF3 | 0.01 | new | 1.827 ± 0.819 [1.521; 2.133] | 81.304 ± 6.769 [78.777; 83.832] | 71.709 ± 8.628 [68.488; 74.931] | 79.341 ± 4.102 [77.809; 80.873] |

Các trường hợp benign không có attacker nên TPR/precision/F1 có thể NA do mẫu số bằng 0. Không gán NA thành 0. Độ trễ chỉ trên attacker phát hiện được được báo riêng với detection event coverage; chỉ số capped delay gán cutoff10.000s cho attacker chưa phát hiện để tránh bỏ mất các mẫu bị kiểm duyệt. Danh sách suspect hiện tại và ever_suspected được phân biệt trong CSV.

Cửa sổ thiếu mẫu giữ nguyên trust và bad_windows. Chỉ cửa sổ hợp lệ tốt mới ngắt chuỗi xấu; K được hiểu là K cửa sổ hợp lệ xấu liên tiếp. Sau hết hạn cách ly phải có đủ quan sát RX mới để recovery/reisolation. FR tích lũy nếu được xem từ bộ đếm tổng không phải FR cửa sổ dùng cập nhật EWMA. Số node từng cách ly khác số sự kiện cách ly; tổng sự kiện cách ly của observer cũ phát lại thụ động không được lưu nên báo NA, không thay bằng số node duy nhất.

| Nhóm | Bộ | PDR | Delay quan sát s | Delay capped s | Số node từng nghi ngờ |
|---|---|---|---|---|---|
| eval_SF2 | old | 0.318 ± 0.048 [0.300; 0.336] | 628.165 ± 210.498 [549.564; 706.767] | 1945.913 ± 697.291 [1685.540; 2206.286] | 50.867 ± 9.978 [47.141; 54.593] |
| eval_SF2 | new | 0.318 ± 0.048 [0.300; 0.336] | 795.242 ± 243.832 [704.193; 886.290] | 2690.087 ± 680.429 [2436.010; 2944.163] | 25.567 ± 4.717 [23.805; 27.328] |
| eval_SF3 | old | 0.318 ± 0.048 [0.300; 0.336] | 559.515 ± 200.931 [484.486; 634.544] | 1777.217 ± 682.472 [1522.378; 2032.056] | 61.467 ± 16.182 [55.424; 67.509] |
| eval_SF3 | new | 0.318 ± 0.048 [0.300; 0.337] | 761.366 ± 230.349 [675.353; 847.380] | 2489.275 ± 647.008 [2247.678; 2730.872] | 26.500 ± 4.200 [24.932; 28.068] |

Chênh lệch theo từng cặp seed, mean/std/CI95 nằm trong paired_differences.csv. Không kết luận cải thiện chỉ từ TPR hoặc mean PDR; cần đối chiếu cả precision, coverage, độ trễ và CI của chênh lệch. Một attacker chưa có cửa sổ đủ mẫu không được coi là đã quan sát đầy đủ. TPR toàn sensor giữ các attacker chưa phát hiện trong FN; conditional TPR báo riêng trên node đủ mẫu.

## Mô hình và chi phí giám sát

Detector vẫn là ideal observer từ sự kiện SimPy: RX thành công tạo nghĩa vụ chuyển tiếp, TX bắt đầu với đủ năng lượng được coi là forwarded; không yêu cầu next-hop ACK. Mất kênh sau TX không biến TX đã quan sát thành selective drop. Mô hình chưa mô phỏng mất overhearing, ACK, MAC/queue, idle listening hoặc năng lượng xử lý watchdog. Trong dữ liệu chính, monitoring_energy_j, monitoring_time_s và control_packets vẫn NA; các số này không được thay bằng0.

Để giải quyết phần đo chi phí theo kế hoạch, đã bổ sung công cụ ước lượng độc lập overhead.py. Nó lấy số TX quá cảnh đã quan sát từ kết quả và công thức radio hiện có:

- E_overhear_est = N_TX × số observer mỗi TX × E_RX(8L).
- T_RX_active_est = N_TX × số observer mỗi TX × 8L / bandwidth.
- Nếu khai báo giả thuyết một ACK mỗi TX: E_ACK_est = N_TX × [E_TX(8L_ACK,d_ACK)+E_RX(8L_ACK)].

Không mặc định kích thước ACK hoặc số observer khi thiếu thông số. Ví dụ 16 byte,10m là giả định phân tích độ nhạy được ghi rõ, không phải tham số do kế hoạch quy định. Ước lượng này không trừ pin, không làm chậm gói và không chứng minh lifetime hay tổng security overhead. Số lần reroute/cạnh đổi không được đổi thành số gói điều khiển.

Muốn hoàn thành đo động đúng kế hoạch, bước tiếp theo phải bổ sung một mô hình tùy chọn có các thành phần: gán observer vật lý cho từng hop; xác suất quan sát theo khoảng cách/kênh; RX/idle watchdog events và trừ pin; packet ACK/control có kích thước, TX/RX và thời gian truyền; phân biệt ACK không quan sát được với relay không chuyển tiếp; cập nhật lifetime khi pin giám sát cạn; chạy lại calibration/freeze/evaluation khi các chi phí ảnh hưởng tuyến. Cần kiểm thử conservation cho data+monitoring+control và đối chứng bật/tắt chi phí trên cùng seed. Phần đo chi phí động này chưa được tuyên bố hoàn thành trong bản vá hiện tại.

## Đối chiếu yêu cầu và mã nguồn

| Yêu cầu | Vị trí | Kiểm chứng | Trạng thái |
|---|---|---|---|
| Attacker bỏ gói quá cảnh sau RX | src/wsn_sim/attacks.py và traffic.py | check_attacks; test_attacks | Đạt |
| P_drop0.25/0.50/0.75; biên0/1; rho0/0.02/0.05/0.10 | cấu hình, selector, test_attacks | bộ20000 mẫu và kiểm thử | Đạt |
| Tách natural_link_loss/selective_forwarding/energy/unreachable | traffic.py | packet traces, terminal guard tests | Đạt |
| N,F,timeout,pending bảo toàn | detection.py | check_detector và bộ hồi quy | Đạt |
| FR và EWMA cùng cohort đủ hạn | detection.py | test_detector_observer và test_long_horizon_audit | Đạt |
| Hiệu chỉnh theo benign dài và attack validation | analysis/security_crosscheck | protocol, selection, gate, freeze | Đạt trong phạm vi10.000s |
| Danh sách suspected/current/ever/isolated | summary và suspected_nodes.csv | trạng thái từng relay | Đạt |
| ACK/overhearing và chi phí giám sát động | chưa triển khai | NA trong dữ liệu chính, công cụ ước lượng riêng | Chưa hoàn thành mô hình động |

## Thay đổi và bảo toàn

Chỉ mở rộng calibration.py để xác thực protocol/freeze dài hạn và hash chứng cứ validation. Không sửa thuật toán attacker, FR, EWMA, ngữ nghĩa timeout, năng lượng data hoặc lựa chọn tuyến. Thêm pipeline, công cụ ước lượng, kiểm thử hồi quy, cấu hình mới và báo cáo. Source snapshot/freeze/data cũ giữ nguyên. Hash cũ không được chỉnh sửa để vượt kiểm tra. Các freeze cũ thuộc phiên nguồn lịch sử và không còn hợp lệ với source sau khi thêm validator; cấu hình hiện hành là detector_long_horizon_20261117.json.

10.000 giây =1.000 round khi Tg=10s. Đây không phải10.000 round/100.000s của kế hoạch gốc. Không dùng các mốc HND/LND chưa quan sát để suy diễn lifetime đầy đủ.

## Lệnh PowerShell sau khi áp dụng bản vá

```powershell
Set-Location 'F:\bangdzaihjhj\dancctt'
& '.\.venv\Scripts\python.exe' -B -m pytest -q -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -B scripts\check_attacks.py --samples 20000
& '.\.venv\Scripts\python.exe' -B scripts\check_detector.py
& '.\.venv\Scripts\python.exe' -B scripts\run_calibration.py --verify-freeze configs\detector_long_horizon_20261117.json
Import-Csv '.\results\security_crosscheck_20261117\suspected_nodes.csv' | Where-Object suspected -eq 'True' | Select-Object group,seed,channel,node_id,trust,suspected_at,isolated_until
```

Không dùng freeze cũ để chạy CLI trên source mới. Pipeline.py report dựng lại bảng từ CSV/summary hiện có; các lệnh validate/freeze/evaluate kiểm tra source và protocol, không chọn lại trên evaluation. Full diagnostic trace có trong bản làm việc; gói bàn giao giữ trace đầy đủ cho các packet đại diện, các cohort cảnh báo đầu tiên và liên kết nguyên nhân để tránh gói quá lớn.
