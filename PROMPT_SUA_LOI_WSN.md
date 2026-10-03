# Prompt sửa lỗi và kiểm chứng dự án Wireless Sensor Network

Sao chép toàn bộ nội dung từ “Vai trò và nhiệm vụ” đến cuối file vào Codex hoặc công cụ AI lập trình đang mở repository. Đính kèm kế hoạch1 (1).docx; tên file người dùng có thể gọi là kế hoạch(1).docx. Nếu có, đính kèm Thời gian.docx và Bao_cao_giai_doan_1_WSN.docx.

Đây là chỉ dẫn cho lần sửa mã tiếp theo, chưa phải xác nhận rằng mã nguồn đã được sửa hoặc đã vượt qua kiểm thử.

## Vai trò và nhiệm vụ

Bạn là kỹ sư Python chuyên mô phỏng WSN, NetworkX, SimPy, định tuyến, mô hình năng lượng và kiểm thử nghiên cứu. Hãy trực tiếp sửa mã trong repository hiện có, kiểm thử các thay đổi và tạo tài liệu Markdown hướng dẫn kiểm tra sau sửa. Không dừng ở việc đề xuất giải pháp hoặc cung cấp đoạn mã để tôi tự ghép.

Repository: https://github.com/NA-cndc/Wireless_Sensor_Network

Mục tiêu là một bản mã tích hợp giữ được chức năng của main, XB, NA; sửa lỗi hiện có; đáp ứng yêu cầu phần mềm mô phỏng trong kế hoạch; cung cấp bằng chứng kiểm tra có thể tái lập. Ưu tiên hoàn tất sửa nền tảng trước, sau đó bổ sung các module bắt buộc còn thiếu theo thứ tự phụ thuộc. Không mở rộng sang website, AI/ML, thiết bị vật lý hoặc giao thức ngoài kế hoạch.

Tài liệu có thứ tự ưu tiên:
1. Yêu cầu trực tiếp trong prompt này và kế hoạch1 (1).docx.
2. Thời gian.docx để đối chiếu phân công và lịch.
3. Báo cáo giai đoạn 1 để tham khảo lý thuyết, không ghi đè đặc tả kế hoạch.

Báo cáo giai đoạn 1 nói về Beta trust và cost có trọng số, trong khi kế hoạch yêu cầu EWMA trust và chọn tuyến lexicographic. Dùng EWMA và lexicographic cho cấu hình nghiên cứu chính. Không âm thầm kết hợp hai cơ chế.

Nếu không có file DOCX trong môi trường, vẫn thực hiện phần đặc tả được trích đầy đủ trong prompt này; ghi rõ chưa đối chiếu trực tiếp file gốc. Nếu đọc DOCX, phải đọc cả công thức OMML; trích văn bản thông thường có thể làm mất số, ký hiệu và phương trình.

## 1 Kiểm tra repository và tích hợp mã hiện có

Tại lần kiểm tra ngày 03/10/2026:
- main và NA cùng trỏ tới 5d2287a0b5540fb54e30fb432a90e986b36d35dd.
- XB trỏ tới fec0b0fa39b7adc4e504c440dc5abe08ecb1290a.
- XB có 3 commit riêng; main có 4 commit riêng so với XB.
- Commit có tên “Merge branch 'XB' into NA” không có đủ các commit riêng của XB hiện tại.

Đây là mốc tham khảo, phải kiểm tra lại HEAD, nhánh và diff hiện tại trước khi sửa. Các lỗi dưới đây là phát hiện ở mốc đó; không giả định chúng còn tồn tại nếu repository đã thay đổi.

Đọc AGENTS.md nếu có. Kiểm tra git status, remote, nhánh, cấu trúc package và API. Giữ nguyên thay đổi chưa commit của người dùng. Nếu đang ở nhánh integration/wsn-all, tiếp tục trên nhánh đó; nếu chưa có nhánh tích hợp, tạo một nhánh sửa riêng phù hợp từ bản tích hợp. Không reset --hard, clean -fd, force-push hoặc tự push/merge lên main.

Nếu cần tích hợp, dùng các ref đã fetch mới của origin/main, origin/NA và origin/XB, xử lý xung đột theo chức năng. Không nhận toàn bộ ours/theirs để bỏ qua xung đột. Nếu không truy cập được remote, dùng ref local đang có và báo mốc được kiểm tra.

Giữ và hợp nhất:
- main/NA: energy.py, routing.py, traffic.py, mô phỏng SimPy, giám sát CSV, entry point main.py.
- XB: logger của package, tests/test_environment.py, sequence_number và sink_id của Packet, helper virtual super-sink và kiểm tra connectivity, tài liệu môi trường.
- Giữ tương thích các caller đang dùng range_m khi hợp nhất Network.
- Chọn một API Simulation thống nhất, sửa toàn bộ caller và test; không để smoke simulation thay thế traffic simulation.
- Quy về package src/wsn_sim làm nguồn logic chính. Các file root cũ có thể là wrapper tương thích, không để hai bộ topology/config độc lập tạo kết quả khác nhau mà không giải thích.
- Trước khi sửa, chạy bộ test hiện có, ghi nhận lỗi và phiên bản môi trường. Không sửa test chỉ để che lỗi.

## 2 Đặc tả bắt buộc từ kế hoạch

| Thành phần | Yêu cầu |
|---|---|
| Vùng mô phỏng | 3000 m × 3000 m |
| Node | 450 sensor và 7 sink; ID duy nhất; đứng yên |
| Phân bố | Sensor và sink sinh ngẫu nhiên đều trên vùng, tái lập bằng seed |
| Pin | Sensor đồng nhất E0 = 5 J; sink không giới hạn pin |
| Liên kết thật | Đồ thị vô hướng; khoảng cách Euclid d <= R; không có cạnh vật lý sink–sink trong mô hình đang dùng |
| Bán kính | Pilot R = 250, 300, 350 m; đề xuất ban đầu 300 m |
| Reachability | Đánh giá >= 95% sensor tới ít nhất một sink trên nhiều topology; ghi cả seed thất bại |
| Traffic | Mỗi sensor còn sống sinh 128 byte mỗi 10 giây |
| Ngưỡng relay | Eth = alpha_energy × E0; mặc định alpha_energy = 0.20, Eth = 1 J |
| Độ nhạy ngưỡng | alpha_energy = 0.10, 0.20, 0.30 |
| Kết thúc | LND hoặc giới hạn 10.000 round; định nghĩa rõ round và thời gian |
| Routing | MHR, EMHR, MHR-SF, S-EMHR |
| Mất gói tự nhiên | p_ch = 0, 0.01, 0.05 |
| Tỷ lệ attacker | 0, 0.02, 0.05, 0.10; chỉ chọn từ sensor |
| Selective Forwarding | p_drop = 0.25, 0.50, 0.75; chỉ bỏ gói quá cảnh tại relay |
| Phát hiện | Forwarding ratio + EWMA; n_min, W, K cửa sổ, ngưỡng hiệu chỉnh benign |
| Phục hồi | Blacklist tạm thời; hết T_isolation thì đánh giá lại; đổi tuyến/sink |
| Thí nghiệm | Tối thiểu 30 seed độc lập cho mỗi cấu hình chính; so sánh theo cặp |
| Thống kê | Mean, sample SD, CI 95%, kiểm định cặp, effect size |

Phân biệt alpha_energy với hệ số EWMA beta_trust; không dùng một biến alpha cho cả hai ý nghĩa.

Giới hạn 10.000 round không phải 10.000 giây. Nếu dùng round = chu kỳ traffic 10 giây, công bố ánh xạ đó và cho phép cấu hình. Chế độ smoke có giới hạn ngắn riêng; không thay cấu hình nghiên cứu chính bằng smoke.

Các tham số chưa được kế hoạch chốt, như queue capacity, W, n_min, K, beta_trust, T_isolation, bandwidth, phải được khai báo, có đơn vị và lý do lựa chọn. Không ghi lựa chọn của lập trình viên thành yêu cầu của giảng viên.

## 3 Danh sách lỗi cần xác minh và sửa

### 3.1 API Simulation và các entry point

Simulation trên main/NA đã đổi sang nhận config, current_range_m, env nhưng demo và tests còn gọi Simulation(network). Điều này gây TypeError hoặc AttributeError: Network không có seed.

Thống nhất constructor hoặc cung cấp tương thích có kiểm soát. Kiểm tra scripts/run_demo.py, wsn-demo, main.py, API smoke, tests/test_simulation.py và integration test. Không tạo lại topology khác một cách ngầm định khi người gọi truyền Network có sẵn.

### 3.2 Test và cấu hình sai theo nhánh

Test manifest đang ép git_branch == "XB". Thay bằng test metadata trong một repository tạm có nhánh biết trước hoặc kiểm tra đúng ngữ nghĩa. Phải hoạt động trên main, NA, XB, nhánh tích hợp, detached HEAD và source archive không có Git metadata.

main/NA đang dùng E0 = 3 J, EMHR mặc định 0.5 J. Sửa cấu hình chính về 5 J và Eth = 1 J tính từ tỷ lệ 20%; không tiếp tục hard-code ngưỡng trong routing.

Các giá trị nhỏ dành cho unit test được phép khác mặc định nghiên cứu và phải được ghi rõ.

### 3.3 MHR

MHR phải tìm đường ít hop nhất tới bất kỳ sink thật nào trên đồ thị hoạt động. Loại sensor chết khỏi tuyến; source chết không được tạo/gửi gói.

Xử lý source không tồn tại, không có sink tiếp cận, nhiều sink cùng số hop và không tạo vòng lặp. Tie-break cuối phải cố định hoặc dùng RNG có seed riêng được ghi trong manifest.

Nếu dùng virtual super-sink, cạnh ảo có chi phí thích hợp; loại node/cạnh ảo khỏi route thực và hop count. Không để thuật toán hiểu một cạnh vật lý không có weight thành chi phí 1 trong khi cạnh ảo bằng 0 theo cách làm sai mục tiêu. Có test đối chiếu minimum-hop trực tiếp đến từng sink.

### 3.4 EMHR

Mã cũ lọc ngưỡng rồi random.choice giữa các shortest paths, chưa đúng kế hoạch.

Đối với tập đường khả thi, chọn lexicographic theo:
1. H(P): số cạnh thật nhỏ nhất.
2. D(P): tổng khoảng cách thật nhỏ nhất.
3. Phi_E(P) = tổng E0 / (E_i + epsilon) của các sensor trong đường theo công thức kế hoạch.
4. ID/tuyến ổn định nếu toàn bộ tiêu chí trên bằng nhau.

Source là cố định nên phần năng lượng source không thay đổi thứ hạng; ghi rõ tập node dùng khi tính penalty. Relay cần còn sống và E_i >= Eth. Source còn sống được phép gửi gói của mình dù dưới ngưỡng relay, nhưng vẫn phải đủ năng lượng TX. Sink không chịu ngưỡng pin.

Không fallback sang relay dưới ngưỡng. Nếu không còn tuyến, trả unreachable.

Không liệt kê toàn bộ shortest paths của mạng 450 sensor sau mỗi gói. Dùng BFS tạo lớp/DAG minimum-hop rồi tối ưu tiêu chí phụ, hoặc phương pháp tương đương có test chứng minh đúng thứ tự ưu tiên. Cache phải vô hiệu đúng khi năng lượng/ngưỡng/trust làm thay đổi eligibility hoặc thứ hạng.

### 3.5 Reroute và đồ thị hoạt động

Kiểm tra tuyến khi relay chết, xuống dưới ngưỡng, liên kết mất hoặc relay bị blacklist. Thực hiện reroute theo chính sách công bố, bao gồm thay sink khi cần. Không dùng route cũ không hợp lệ đến hết hành trình.

Phân biệt route dự kiến và path thực tế đã đi. Ghi route-change event, nguyên nhân và chi phí. Không tạo vòng lặp khi reroute. Không để graph node energy_j lỗi thời được dùng thay năng lượng thực của Sensor.

### 3.6 Radio energy và node thiếu pin

Dùng first-order radio model:
- l = size_bytes × 8.
- ETX(l,d) = l E_elec + l epsilon_fs d² khi d < d0.
- ETX(l,d) = l E_elec + l epsilon_mp d⁴ khi d >= d0.
- ERX(l) = l E_elec.
- d0 = sqrt(epsilon_fs / epsilon_mp).
- Data aggregation chỉ bật nếu có mô hình rõ, nếu tắt ghi E_DA = 0.

Chuyển E_elec, epsilon_fs, epsilon_mp và tham số năng lượng vào cấu hình. Không giữ d0 = 87 m cố định nếu hệ số được đổi.

Mã cũ chỉ clamp pin về 0, không kiểm tra đủ chi phí TX/RX. Đã có trường hợp sender còn 1e-12 J nhưng cần khoảng 5.22e-5 J mà gói vẫn được đếm delivered.

Thiết kế rõ trình tự debit và outcome; ghi ledger TX/RX cùng kết quả. Gói không thể thành công khi một endpoint cần thiết không đủ năng lượng cho thao tác. Trường hợp pin bằng đúng chi phí vẫn có thể hoàn thành thao tác rồi node chết, cần test riêng.

Nếu thất bại giữa hop, năng lượng đã tiêu đúng ở phần trước vẫn được ghi; không hoàn pin vô lý, không trừ năng lượng hop sau. Công bố chính sách khi RX không đủ hoặc link loss; không tự tạo hay bỏ qua chi phí radio đã xảy ra. Sink không bị trừ pin trong accounting của sensor.

### 3.7 Packet và sink

Mã cũ chỉ append vào delivered_packets; Packet vẫn IN_TRANSIT, delivered_at None và sink chưa ghi nhận gói.

Khi thực sự tới sink, cập nhật qua một đường xử lý thống nhất: sink nhận, deduplicate, Packet DELIVERED, delivered_at, sink_id, current hop và các bộ đếm. Không đếm một gói nhiều lần.

Packet có packet_id duy nhất, sequence_number theo nguồn, source_id, sink_id, thời điểm tạo/chuyển tiếp/nhận, payload size, current node/next hop, route dự kiến, path thực, status và drop_reason. Thêm TTL nếu sử dụng, cập nhật đúng mỗi hop và log TTL exhaustion riêng.

Một Packet chỉ có một kết quả kết thúc chính; không chuyển gói DROPPED thành DELIVERED. Counter tại sensor, sink, traffic và metrics phải khớp.

### 3.8 Traffic, hàng đợi và thời gian

Mã cũ chỉ khởi chạy sensor có tuyến tại thời điểm ban đầu, khiến nguồn cô lập không sinh gói và PDR có thể bị nâng sai.

Tất cả sensor còn sống sinh gói định kỳ; không có tuyến thì log unreachable. Node chết ngừng tạo gói mới. Lịch traffic của các thuật toán so sánh cùng seed phải thống nhất, nhưng số gói sinh thực tế có thể khác sau khi thời điểm chết khác nhau.

Tạo mô hình hàng đợi, truyền tuần tự/busy radio ở mức trừu tượng đã chọn, queue capacity và queue_drop. Độ trễ gồm các thành phần thực sự mô phỏng. Không cộng delay giả để làm đẹp kết quả và không gọi mô hình tầng PHY/MAC hoàn chỉnh khi chỉ mô phỏng mức mạng.

Tại thời điểm dừng, phân biệt generated, delivered, dropped và in_flight/pending. Nếu drain traffic cuối kỳ, ghi riêng policy và khoảng đo. Không coi pending là loss âm thầm và không loại pending khỏi mẫu số PDR tùy tiện.

### 3.9 Seed và chạy song song

Topology đã dùng NumPy seed, routing cũ dùng random chưa seed. Tách RNG/seed cho topology, traffic, channel loss, attacker và lựa chọn tuyến nếu còn ngẫu nhiên.

So sánh cặp không chỉ dùng chung một seed đầu vào: tránh RNG thay đổi vì thứ tự sự kiện/routing khác. Có thể dùng stream độc lập hoặc draw theo khóa ổn định gồm packet_id, hop/edge và loại sự kiện. Công bố cách ghép mẫu channel loss khi tuyến khác nhau.

Cùng config và seed phải tái lập cả kết quả, không chỉ tọa độ. Chạy serial và multiprocessing cho cùng run phải cho kết quả tương đương theo tolerance xác định. Dùng spawn-safe entry point, không dùng shared mutable RNG.

### 3.10 Output và metadata

Mã cũ ghi results/simulation_log_range_XXXm.csv với mode w, dễ ghi đè giữa seed/thuật toán. Tạo output theo scenario, algorithm, seed, run_id. Parallel worker không dùng chung tên file/log.

Lưu config, tất cả seed, commit, dirty state, config hash, package versions, schema version, thời gian chạy và stop reason. Không đưa timestamp/runtime vào so sánh scientific determinism.

Có tối thiểu config.json, run_manifest.json, nodes.csv, packets.csv, events.csv, metrics.csv/JSON và topology.png. Khi có bảo mật, thêm trust/detection log. Biểu đồ và summary phải truy ngược tới raw data. Giữ dữ liệu chạy cũ để đối chiếu, đánh dấu legacy nếu dùng cấu hình sai; không dùng làm kết quả chính.

## 4 Hoàn thiện phần bắt buộc còn thiếu

Phân loại từng mục thành lỗi hiện có, đã có nhưng thiếu kiểm thử, chưa triển khai. Sau khi sửa phần nền tảng, triển khai phần mềm còn thiếu theo kế hoạch; không thay bằng stub trả số liệu giả.

### 4.1 Metrics và lifetime

Tính từ event/packet log đã xác nhận:
- B_sink(t): số bit hợp lệ tới sink; dữ liệu tại FND/HND/LND.
- FND: sensor đầu tiên chết; HND: ít nhất ceil(N/2) sensor chết; LND: sensor cuối chết.
- Functional death theo tỷ lệ sensor còn sống có tuyến tới sink < 50%; công bố cách tính connectivity vật lý và connectivity theo constraints.
- Offered rate thực tế; throughput và goodput tính đúng cửa sổ, đúng payload/control.
- PDR = delivered_unique / generated × 100%; PLR theo trạng thái mất.
- Energy/bit = năng lượng sensor đã tiêu / số bit nhận hợp lệ.
- Hop thực trung bình và độ trễ đầu cuối trên gói delivered.
- Relay load, Jain fairness = (sum f_i)^2 / (N sum f_i^2), công bố tập node trong mẫu số.
- Route-change, control packet, monitoring/ACK và energy overhead.

Metric chưa đạt mốc chết trong khoảng chạy phải là null/censored, không ghi 0 hoặc gán bằng thời gian kết thúc. Nếu denominator bằng 0, trả giá trị undefined có lý do; không tạo NaN/Infinity không hợp lệ trong JSON. Kiểm thử counter/time-window boundaries và tránh đếm lại dữ liệu cộng dồn giữa các cửa sổ.

### 4.2 Attack và natural loss

Chọn attacker có seed, không chọn sink; ghi actual attacker count và quy tắc làm tròn. Với 450 node và 5%, công bố quy tắc cho 22.5 node; kế hoạch mô tả xấp xỉ 23.

Attacker chỉ bỏ gói quá cảnh đang làm relay, không tự bỏ gói do chính mình tạo theo mô hình này. p_drop = 0 không gây attack drop; p_drop = 1 chỉ dành cho test Black Hole.

Tách natural_link_loss, selective_forwarding, energy_depletion, queue_drop, unreachable và TTL nếu có. Một gói có một nguyên nhân kết thúc chính và node/hop gây mất. Gói đã mất không tiêu năng lượng ở hop tiếp theo.

### 4.3 Detector và S-EMHR

Forwarding ratio FR_i = F_i / max(N_i, 1); ghi N_i, F_i và quan sát đủ điều kiện, không chỉ counter toàn mạng.

EWMA: T_i(r) = beta_trust × T_i(r-1) + (1-beta_trust) × FR_i(r), 0 < beta_trust < 1.

Chỉ quyết định sau n_min quan sát, trust dưới ngưỡng trong K cửa sổ liên tiếp; hiệu chỉnh ngưỡng bằng benign calibration, ví dụ phân vị 5%, và tách calibration seed với evaluation seed.

Có W, initial trust, empty-window policy, K, isolation time, re-evaluation và chính sách reset quan sát rõ ràng. Không dùng attacker ground truth để ra quyết định; ground truth chỉ phục vụ đánh giá. Không coi mọi loss tự nhiên hoặc queue/energy failure là malicious forwarding.

Theo dõi qua cơ chế watchdog/ACK được mô hình hóa và khai báo; nếu dùng quan sát lý tưởng trong simulator, nói rõ giả định, không gọi đó là triển khai phân tán thực. Chi phí giám sát/control phải được đo theo mô hình, không mặc định miễn phí rồi kết luận overhead bằng 0.

S-EMHR loại relay blacklist, tìm tuyến/sink mới, không fallback vào node cách ly. Đo TPR/Recall, FPR, Precision, F1, detection delay, route avoidance và security overhead. Công bố xử lý node chưa đủ quan sát và denominator bằng 0.

### 4.4 Experiment runner và thống kê

Có CLI với --help, cấu hình smoke/pilot/research và chọn routing/scenario/seed/output. main.py và scripts/run_demo.py phải chạy được hoặc chuyển thành wrapper có tài liệu rõ.

Các scenario: benign MHR, benign EMHR, MHR-SF không phòng vệ, SF-2 detection-only, S-EMHR có defense. Multipath/SF-4 chỉ là mở rộng, không bắt buộc trong phạm vi này.

Runner hỗ trợ paired seeds, 30 seed/config chính, lưu run failure không âm thầm bỏ seed, resume/checkpoint không ghi đè và kiểm tra đầy đủ dữ liệu trước thống kê.

Tính sample SD với ddof=1, CI 95% theo Student t. Chọn paired t-test hoặc Wilcoxon theo điều kiện của dữ liệu; công bố assumption, p-value, chênh lệch tuyệt đối/phần trăm và effect size có định nghĩa. Xử lý dữ liệu lifetime censored hợp lý; không coi mốc chưa xảy ra như giá trị quan sát chính xác.

Không buộc EMHR/S-EMHR thắng baseline. Báo cáo trade-off và kết quả bất lợi trung thực.

## 5 Bộ kiểm thử có ý nghĩa

Dùng topology nhỏ với đáp án tính tay, test công thức độc lập và integration test để bắt lỗi thực tế. Không chỉ assert rằng chương trình không crash.

Tối thiểu kiểm tra:
1. 450 sensor, 7 sink, ID duy nhất, tọa độ trong vùng và cùng seed tái lập.
2. Cạnh thật thỏa R; graph đối xứng; cạnh virtual không tính vào path/hop thật.
3. Pilot nhiều seed báo đủ degree, components, isolation, reachability, tỷ lệ seed không đạt.
4. MHR minimum-hop tới nhiều sink; no-route; không đi qua node chết.
5. EMHR lọc pin dưới/bằng/trên ngưỡng; source dưới ngưỡng nhưng đủ TX.
6. Ưu tiên hop trước distance; distance trước energy; deterministic tie cuối.
7. Reroute relay chết/thấp pin; đổi sink; no-route không fallback.
8. ETX nhánh d²/d⁴, ERX, byte→bit, d0 theo hệ số.
9. Sender thiếu TX, receiver thiếu RX, đúng bằng chi phí, không âm pin.
10. Energy ledger khớp mức giảm pin; hop sau gói mất không phát sinh debit.
11. Packet tới sink thực có DELIVERED, timestamp, sink_id, path và counter khớp.
12. Dedup packet; sequence theo nguồn; path không lặp; TTL nếu bật.
13. Sensor sống cô lập vẫn tạo gói NO_ROUTE; node chết không tạo gói.
14. Queue overflow/busy radio/delay; boundary sinh gói và stop time.
15. generated = delivered + dropped + pending tại snapshot, theo định nghĩa nhất quán.
16. Cùng config/seed tái lập toàn bộ kết quả; serial/parallel tương đương.
17. Metric trên log biết trước; cumulative/time-window không đếm trùng; zero-denominator.
18. FND/HND/LND/functional death và các mốc chưa quan sát.
19. Attacker không là sink; p_drop = 0/1; source attacker vẫn gửi dữ liệu của mình.
20. Natural loss và attack drop tách biệt, không đếm hai lần.
21. EWMA công thức; n_min; K; empty-window; blacklist expiry.
22. Calibration benign; detector không truy cập ground truth để quyết định.
23. S-EMHR tránh node blacklist; đổi sink; không còn route hợp lệ.
24. Confusion matrix và detection delay trên dữ liệu biết trước.
25. Output khác seed/algorithm không ghi đè; manifest và schema đủ.
26. CI/statistics với >= 30 mẫu kiểm thử độc lập; lỗi thiếu sample được báo.
27. Demo/CLI chạy từ môi trường sạch; --help; import/entry point trên OS hỗ trợ.
28. Git metadata trên nhánh khác XB, detached HEAD và không có repository.

Bổ sung CI cơ bản chạy trên Windows và Ubuntu với Python version thực sự được dự án hỗ trợ; ít nhất một phiên bản chung đã xác nhận. Chạy unit/integration và smoke nhỏ, không chạy toàn bộ research batch trong mỗi PR. Nếu Actions chưa được chạy trên remote, trạng thái phải là “cấu hình xong, chưa xác nhận lượt chạy”.

Không cần giữ số lượng test cũ. Không xóa hay skip một test chỉ vì nó lộ lỗi.

## 6 Tài liệu Markdown bắt buộc sau khi sửa

Tạo docs/HUONG_DAN_KIEM_TRA_WSN.md sau khi đã triển khai và chạy kiểm tra. Viết tiếng Việt dễ hiểu cho sinh viên năm 3 ngành Mạng máy tính, giải thích lệnh và kết quả cần thấy. Dùng tên file, CLI option và đường dẫn có thật trong bản mã cuối; không viết lệnh tưởng tượng.

Tài liệu phải có:

1. Phạm vi bản sửa, branch/commit hoặc dirty state, ngày kiểm tra và nguồn kế hoạch.
2. Bảng công cụ: Git, Python, venv, NetworkX, SimPy, NumPy, pandas, SciPy, Matplotlib, seaborn nếu dùng, pytest, VS Code. Ghi phần bắt buộc/tùy chọn và vai trò.
3. Các môi trường: Windows PowerShell/CMD, Ubuntu 24.04 Terminal, Ubuntu trong VMware, VS Code local; VS Code Remote SSH tới Ubuntu là cách mở môi trường remote, không phải simulator khác. WSL có thể có hướng dẫn nếu thực sự hỗ trợ. Không tự bổ sung Packet Tracer/GNS3/ns-3/OMNeT++ vào đường chạy chính.
4. Lệnh kiểm tra phiên bản, cài package, tạo venv riêng, pip check, kiểm tra import. Cách chọn đúng Python interpreter trong VS Code và nhận biết terminal đang chạy Windows hay Ubuntu.
5. Lệnh clone/pull bản cần kiểm tra; kiểm tra branch, commit và working tree. Dùng thư mục/placeholder có hướng dẫn thay rõ ràng; không gán đường dẫn máy phát triển thành đường dẫn của mọi người.
6. Quy trình chạy toàn bộ test, test theo module và xuất log. Lệnh theo PowerShell, CMD và Bash phải đúng cú pháp; không trộn shell.
7. Smoke demo trước, mô phỏng một seed tiếp theo, pilot nhiều seed và research batch 30 seed sau cùng. Nêu thời gian mô phỏng so với wall-clock, cách stop/resume và output cần mở.
8. Bảng đối chiếu từng hạng mục kế hoạch với code, test, lệnh chạy, file bằng chứng, tiêu chí đạt và trạng thái.
9. Hướng dẫn kiểm tra topology, MHR, EMHR, energy ledger, Packet, queue, metrics, attack, detector, S-EMHR và thống kê theo các trường hợp mục 5.
10. Cách đọc packets/events/metrics/trust CSV, config, manifest và biểu đồ; đơn vị của từng cột quan trọng.
11. Bảng lỗi thường gặp: command not found, sai Python/venv, ModuleNotFoundError, chưa cài editable package, sai cwd, thiếu config, lỗi API Simulation, sai branch assertion, lỗi matplotlib display, UTF-8 trên Windows, multiprocessing spawn, quyền ghi file.
12. Checklist nghiệm thu và phần chưa được kiểm tra. Ghi riêng “đạt trên Linux”, “đạt trên Windows”, “hướng dẫn nhưng chưa chạy”, “chưa chạy 30 seed/cấu hình chính”. Không khẳng định mọi môi trường đạt nếu chỉ có một môi trường.
13. Link tài liệu chính thức cho Git, Python venv, NetworkX, SimPy, pytest và thư viện thống kê liên quan.

Ví dụ lệnh môi trường có thể dùng làm nền tảng, phải điều chỉnh theo mã cuối và interpreter thực tế:

Windows PowerShell:
~~~powershell
python --version
git --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q *> pytest-result.txt
~~~

Windows CMD:
~~~bat
python --version
git --version
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest -q > pytest-result.txt 2>&1
~~~

Ubuntu Bash:
~~~bash
python3 --version
git --version
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pip check
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q > pytest-result.txt 2>&1
~~~

Nếu Python Launcher dùng py thay python trên Windows, hướng dẫn kiểm tra phiên bản và chọn interpreter phù hợp. Ưu tiên gọi trực tiếp Python trong venv để không cần thay ExecutionPolicy chỉ nhằm activate.

Tạo thêm docs/BAO_CAO_SUA_LOI_WSN.md gồm:
- Bảng issue ID, lỗi trước sửa, nguyên nhân, file/hàm đã sửa và test hồi quy.
- Phân biệt lỗi đã sửa với chức năng mới bổ sung và yêu cầu còn thiếu.
- Lệnh thực sự chạy, exit code, số test pass/fail, môi trường và đường dẫn bằng chứng.
- Quyết định mô hình, giả định, hạn chế và những điều chưa xác nhận.
- Đối chiếu milestones chính đến 15/11/2026 theo file kế hoạch; không dùng lịch Thời gian.docx để tự thay deadline kế hoạch chính.
- Danh sách dataset legacy không dùng để kết luận nghiên cứu.

Cập nhật README và tài liệu kiến trúc/cài đặt để phản ánh mã cuối. Loại các link file:///d:/... khỏi README, thay bằng link tương đối trong repository. Sửa tuyên bố “43 tests pass” hoặc “Windows/Ubuntu chạy 100%” nếu không có bằng chứng hiện tại. Nếu tài liệu lý thuyết không thuộc phạm vi chỉnh sửa, ghi rõ các điểm cần đồng bộ Beta/EWMA và cost/lexicographic thay vì giả vờ đã sửa DOCX.

## 7 Trình tự thực hiện và tiêu chí hoàn thành

1. Kiểm tra mã hiện tại, đối chiếu kế hoạch, tái hiện lỗi; lập bảng requirement → implementation → test.
2. Tích hợp phần còn thiếu của các nhánh trên nhánh sửa local.
3. Sửa cấu hình/API/Packet/energy/routing/traffic/output/seed; chạy regression test thích hợp.
4. Bổ sung metrics, attack, detection, S-EMHR, experiment runner và thống kê bắt buộc theo thứ tự phụ thuộc.
5. Chạy bộ test và smoke/pilot. Có test thống kê trên >= 30 seed nhỏ, nhưng không gọi đó là nghiệm thu research batch 450 sensor cho mỗi cấu hình chính.
6. Chuẩn bị và chạy ma trận thí nghiệm chính nếu môi trường đủ tài nguyên; lưu checkpoint/raw data/log lỗi. Nếu chưa chạy đủ, ghi chính xác cấu hình/seed đã chạy và lệnh để tiếp tục, không bịa số liệu.
7. Viết hai file Markdown sau khi kết quả thực tế đã có; kiểm tra mọi lệnh của môi trường đang dùng. Tài liệu cho OS không có môi trường chạy phải gắn nhãn chưa xác nhận.
8. Kiểm tra git diff --check, các file sửa, test cuối phù hợp, imports và entry point.

Mã nguồn đạt khi các yêu cầu mô hình và hồi quy đã được kiểm tra, không còn lỗi đã xác nhận trong phần sửa. Nghiệm thu toàn bộ nghiên cứu chỉ đạt khi dữ liệu, 30 seed/config chính, thống kê và bằng chứng đều đủ. Phân biệt hai mức hoàn thành này trong kết quả.

Không tự ghi kết quả nghiên cứu, slide hoặc video giả; nhiệm vụ hiện tại là code mô phỏng, kiểm thử, output thật và tài liệu kiểm tra. Không tự đăng GitHub hay merge main; để lại bản sửa và hướng dẫn đưa lên GitHub cho người dùng.

## 8 Nội dung trả lời khi kết thúc

Trả lời ngắn, có bằng chứng:
1. Đã sửa gì và kết quả thay đổi.
2. Test nào thực sự chạy, pass/fail, trên môi trường nào.
3. Đường dẫn docs/HUONG_DAN_KIEM_TRA_WSN.md và docs/BAO_CAO_SUA_LOI_WSN.md.
4. Ba đến năm lệnh đầu tiên để tôi kiểm tra lại bản sửa trên máy.
5. Yêu cầu chưa hoàn thành, lý do và bước tiếp theo cụ thể nếu có.

Bắt đầu bằng kiểm tra repository và chạy test hiện có, rồi thực hiện các thay đổi. Không chỉ trả lại một bản kế hoạch sửa lỗi.

## Nguồn đối chiếu

Kế hoạch1 (1).docx: Mục 2.4, 3.2–3.9, 3.10, 4.3 và lịch triển khai. Bản mô hình tóm tắt trong prompt được đối chiếu cả công thức DOCX ngày 03/10/2026.

Mã nguồn tại mốc review:
- [main/NA](https://github.com/NA-cndc/Wireless_Sensor_Network/tree/5d2287a0b5540fb54e30fb432a90e986b36d35dd)
- [XB](https://github.com/NA-cndc/Wireless_Sensor_Network/tree/fec0b0fa39b7adc4e504c440dc5abe08ecb1290a)
- [So sánh main với XB](https://github.com/NA-cndc/Wireless_Sensor_Network/compare/main...XB)
- [Routing](https://github.com/NA-cndc/Wireless_Sensor_Network/blob/5d2287a0b5540fb54e30fb432a90e986b36d35dd/src/wsn_sim/routing.py)
- [Traffic](https://github.com/NA-cndc/Wireless_Sensor_Network/blob/5d2287a0b5540fb54e30fb432a90e986b36d35dd/src/wsn_sim/traffic.py)
- [Radio energy](https://github.com/NA-cndc/Wireless_Sensor_Network/blob/5d2287a0b5540fb54e30fb432a90e986b36d35dd/src/wsn_sim/energy.py)

Tài liệu kỹ thuật chính thức:
- [Git merge](https://git-scm.com/docs/git-merge)
- [Python venv](https://docs.python.org/3/library/venv.html)
- [NetworkX shortest paths](https://networkx.org/documentation/stable/reference/algorithms/shortest_paths.html)
- [SimPy stable](https://simpy.readthedocs.io/en/stable/)
- [pytest usage](https://docs.pytest.org/en/stable/how-to/usage.html)
- [SciPy statistics](https://docs.scipy.org/doc/scipy/reference/stats.html)

