from argparse import ArgumentParser
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import shutil
import zipfile
import pandas as pd

from study import DEFAULT_PROJECT, PROFILE, load_project, read_json, verify_short_plan
from charts_vi import ORDER, SHORT, LABELS, PLACEMENTS, METRICS, PERFORMANCE, draw_all, is_center
from tables import export_csv, enrich, extend_aggregates, extend_comparisons, formatted, formatted_p


def table_md(records):
    if not records:
        return "Không có quan sát xác định."
    keys = list(records[0])
    return "| " + " | ".join(keys) + " |\n| " + " | ".join("---" for _ in keys) + " |\n" + "\n".join("| " + " | ".join(str(row.get(key, "NA")).replace("|", "/").replace("\n", " ") for key in keys) + " |" for row in records)


def write_report(plan, rows, aggregates, completeness, comparisons, lifetime_table, figures, directory, batch):
    center = {row["scenario"]: row["case_id"] for row in rows if is_center(row)}
    def metric(scenario, name):
        return next(row for row in aggregates if row["case_id"] == center[scenario] and row["metric"] == name)
    def val(scenario, name, factor=1, digits=3):
        value = metric(scenario, name)["mean"]
        return formatted(value * factor if value is not None else None, digits)
    def rel(a, b, name):
        first, second = metric(a, name)["mean"], metric(b, name)["mean"]
        return formatted((first / second - 1) * 100 if first is not None and second else None)
    def fate(scenario, field):
        group = [row[field] for row in rows if row["scenario"] == scenario and is_center(row)]
        return formatted(sum(group) / len(group) * 100, 4)

    design = [{"Kịch bản": SHORT[row["scenario"]], "Attacker (%)": formatted(row["rho"] * 100, 0), "P_drop": formatted(row["p_drop"]), "Vị trí": PLACEMENTS[row["placement"]], "Hoàn tất": f"{row['completed']}/{row['expected']}", "Lỗi": row["failed"]} for row in completeness]
    center_table = []
    for scenario in ORDER:
        center_table.append({"Kịch bản": SHORT[scenario], "PDR (%)": val(scenario, "pdr", 100), "Throughput (kbit/s)": val(scenario, "throughput_bps", .001), "Goodput (kbit/s)": val(scenario, "goodput_bps", .001), "µJ/bit": val(scenario, "energy_per_payload_bit_j", 1e6), "Trễ (ms)": val(scenario, "mean_latency_s", 1000), "Hop": val(scenario, "mean_actual_hops"), "Payload (Mbit)": val(scenario, "received_payload_bits", 1e-6), "Sensor sống": val(scenario, "alive_sensors", 1, 2), "Năng lượng còn (J)": val(scenario, "remaining_energy_j", 1, 2)})
    lifetime_view = [{"Case ID": row["case_id"], "Mốc": row["milestone"], "n_observed/n_runs": f"{row['n_observed']}/{row['n_runs']}", "Censored": row["censored"], "Thời điểm TB khi đạt (s)": formatted(row["conditional_time_mean_s"], 3), "Payload TB khi đạt (Mbit)": formatted(row["conditional_payload_mean_bits"] * 1e-6 if row["conditional_payload_mean_bits"] is not None else None, 3)} for row in lifetime_table]
    for scenario, table_row in zip(ORDER, center_table):
        table_row["Sống và nối vật lý tới sink"] = val(scenario, "physical_reachable_alive", 1, 2)
        table_row["Sống và có tuyến hợp lệ"] = val(scenario, "routing_reachable_alive", 1, 2)
    detector_view = []
    for scenario in ("SF2", "SF3"):
        detector_view.append({"Kịch bản": SHORT[scenario], **{name: val(scenario, name, 100 if name in ("tpr", "fpr", "precision", "f1", "coverage") else 1) for name in ("TP", "FP", "TN", "FN", "tpr", "fpr", "precision", "f1", "coverage", "detection_capped_delay_s", "isolation_capped_delay_s", "detector_isolation_events", "unique_isolated_by_cutoff")}, "Tránh relay": "Bật" if scenario == "SF3" else "Tắt"})
    paired = []
    for comparison in comparisons:
        if comparison["first"] == "SF3" and comparison["second"] in ("EMHR_SF", "MHR_SF", "SF2") and comparison["rho"] == .05 and comparison["p_drop"] == .5 and comparison["placement"] == "random" and comparison["metric"] in PERFORMANCE:
            name = comparison["metric"]
            factor = METRICS[name][2]
            paired.append({"Cặp (A − B)": f"S-EMHR − {SHORT[comparison['second']]}", "Chỉ số": METRICS[name][1], "n cặp": comparison["n_matched"], "Chênh lệch": formatted(comparison["mean_difference_first_minus_second"] * factor, 4), "CI95 thấp": formatted(comparison["difference_ci95_low"] * factor, 4), "CI95 cao": formatted(comparison["difference_ci95_high"] * factor, 4), "Thay đổi (%)": formatted(comparison["percent_change_vs_second"]), "p t/Holm": formatted_p(comparison["paired_t_p_holm"]), "p Wilcoxon/Holm": formatted_p(comparison["wilcoxon_p_holm"])})
    sensitivity = []
    for case in plan["cases"]:
        if case["scenario"] != "SF3":
            continue
        a = next(row for row in aggregates if row["case_id"] == case["case_id"] and row["metric"] == "pdr")
        b = next(row for row in aggregates if row["scenario"] == "EMHR_SF" and row["rho"] == case["rho"] and row["p_drop"] == case["p_drop"] and row["placement"] == case["placement"] and row["metric"] == "pdr")
        sensitivity.append({"Attacker (%)": formatted(case["rho"] * 100, 0), "P_drop": formatted(case["p_drop"]), "Vị trí": PLACEMENTS[case["placement"]], "PDR EMHR-SF (%)": formatted(b["mean"] * 100, 3), "PDR S-EMHR (%)": formatted(a["mean"] * 100, 3), "Chênh lệch (điểm %)": formatted((a["mean"] - b["mean"]) * 100, 3)})

    discussion = [
        f"MHR không tấn công đạt PDR {val('MHR','pdr',100)}%, năng lượng/bit {val('MHR','energy_per_payload_bit_j',1e6)} µJ/bit và {val('MHR','alive_sensors',1,2)} sensor còn sống. EMHR tương ứng {val('EMHR','pdr',100)}%, {val('EMHR','energy_per_payload_bit_j',1e6)} µJ/bit và {val('EMHR','alive_sensors',1,2)} sensor. MHR dùng tuyến hop tối thiểu trên graph vật lý; EMHR xét ngưỡng năng lượng relay. Số liệu cho thấy đánh đổi giữa duy trì relay, dữ liệu nhận và chi phí radio; không suy rộng ưu thế của MHR/SF-2 ra các mức độ nhạy chưa chạy.",
        f"Selective Forwarding làm PDR của MHR-SF còn {val('MHR_SF','pdr',100)}% và EMHR-SF còn {val('EMHR_SF','pdr',100)}%. S-EMHR đạt {val('SF3','pdr',100)}%, thay đổi goodput {rel('SF3','EMHR_SF','goodput_bps')}% so với EMHR-SF và {rel('SF3','MHR_SF','goodput_bps')}% so với MHR-SF. Đây là các giá trị trung bình tại cấu hình trung tâm; bảng cặp giữ CI95 và p đã hiệu chỉnh để đánh giá độ chắc chắn.",
        f"S-EMHR có năng lượng/bit {val('SF3','energy_per_payload_bit_j',1e6)} µJ/bit, trễ {val('SF3','mean_latency_s',1000)} ms và {val('SF3','mean_actual_hops')} hop; EMHR-SF tương ứng {val('EMHR_SF','energy_per_payload_bit_j',1e6)} µJ/bit, {val('EMHR_SF','mean_latency_s',1000)} ms và {val('EMHR_SF','mean_actual_hops')} hop. Tránh relay bị cách ly có thể thay đổi độ dài tuyến và số nguồn còn đường đi. Delay/hop chỉ mô tả gói đã đến sink, nên phải đọc cùng PDR, mất gói và reachability; tiết kiệm năng lượng nhờ bỏ gói sớm không tự chứng minh hiệu quả giao dữ liệu.",
        f"SF-2 chỉ phát hiện đạt PDR {val('SF2','pdr',100)}%, S-EMHR đạt {val('SF3','pdr',100)}%. TPR của hai phương án là {val('SF2','tpr',100)}% và {val('SF3','tpr',100)}%; FPR {val('SF2','fpr',100)}% và {val('SF3','fpr',100)}%; precision {val('SF2','precision',100)}% và {val('SF3','precision',100)}%; coverage {val('SF2','coverage',100)}% và {val('SF3','coverage',100)}%. Giữ cả báo nhầm, bỏ sót và attacker chưa đủ cơ hội chuyển tiếp. Bộ detector đã khóa từ benign calibration hữu hạn; không coi đó là bảo đảm FPR ở mọi horizon và không tinh chỉnh lại bằng 30 seed evaluation.",
        "Các bảng độ nhạy giữ tất cả sáu treatment tấn công đã đo. Thiết kế thay đổi một yếu tố mỗi lần chưa ước lượng tương tác giữa tỷ lệ attacker, P_drop và vị trí; không nối kết quả để khẳng định toàn bộ tích Descartes. Near-sink chọn theo khoảng cách Euclid đến sink gần nhất, phá hòa bằng ID sensor, độc lập với kết quả định tuyến.",
    ]
    discussion.insert(1, f"Ở nhóm không tấn công, EMHR thay đổi goodput {rel('EMHR','MHR','goodput_bps')}% và năng lượng/bit {rel('EMHR','MHR','energy_per_payload_bit_j')}% so với MHR. Đọc PDR cùng lượng gói sinh: sensor chết làm giảm số gói sinh của MHR, nên PDR cao hơn riêng lẻ chưa đồng nghĩa nhận nhiều payload hơn. Khả năng giữ sensor sống và năng lượng/bit là ưu điểm quan sát được của EMHR trong cửa sổ này; ngưỡng relay cũng có thể làm một số nguồn còn pin mất tuyến hợp lệ.")
    discussion.insert(4, "SF-2 quan sát thụ động và không tránh relay, nên các chỉ số giao dữ liệu/radio trùng EMHR-SF khi dùng cùng seed. Sự trùng nhau này phù hợp mô hình chưa thu chi phí giám sát; không có nghĩa detector ngoài thực tế không tiêu tốn tài nguyên.")
    discussion.append(f"Tại 10.000 s, số sensor sống còn tuyến hợp lệ trung bình là {val('MHR','routing_reachable_alive',1,2)} với MHR, {val('EMHR','routing_reachable_alive',1,2)} với EMHR, {val('EMHR_SF','routing_reachable_alive',1,2)} với EMHR-SF và {val('SF3','routing_reachable_alive',1,2)} với S-EMHR. Bảng trung tâm đặt số sensor còn sống cạnh số nối vật lý và số có tuyến hợp lệ để phân biệt còn pin với duy trì khả năng truyền đến sink.")
    milestone_totals = {name: sum(row["n_observed"] for row in lifetime_table if row["milestone"] == name) for name in ("HND", "LND")}
    discussion.append(f"Trong toàn bộ 480 lượt mới, HND được quan sát ở {milestone_totals['HND']}/480 lượt, LND ở {milestone_totals['LND']}/480 lượt. Các mốc còn lại giữ NA/censored trong bảng. Bảng FND và hai đường số sensor sống/năng lượng cho phép đánh giá suy giảm ngắn hạn; không biến 10.000 s thành tuổi thọ thực của các seed chưa đạt mốc.")
    discussion.append(f"Ở SF-2, detector tạo trung bình {val('SF2','detector_isolation_events',1,2)} đề xuất cách ly nhưng chế độ tránh relay tắt. S-EMHR có {val('SF3','detector_isolation_events',1,2)} đề xuất và bật ràng buộc tránh relay. Số quyết định tìm lại tuyến có nguyên nhân chính là an ninh lấy trực tiếp từ log: {val('SF2','security_reroute_decision_count',1,2)} với SF-2 và {val('SF3','security_reroute_decision_count',1,2)} với S-EMHR. Số đề xuất có thể lặp lại trên cùng node, gồm cả báo nhầm; không phải số attacker duy nhất hoặc số lần đổi tuyến thực sự. Nhóm không bật detector không xuất hiện ở ô đề xuất cách ly, nhưng số đếm 0 vẫn giữ trong CSV.")
    discussion.append("PDR toàn kỳ có thể chịu ảnh hưởng mạnh của relay dưới ngưỡng và nguồn còn sống nhưng mất tuyến. Vì vậy tăng xác suất bỏ gói không bắt buộc làm mọi chỉ số trung bình toàn kỳ biến thiên đơn điệu. Đọc các đường độ nhạy cùng tỷ lệ unreachable, selective_forwarding, số sensor còn tuyến và đường năng lượng; không đổi horizon hoặc loại seed chỉ để S-EMHR có kết quả tốt hơn.")
    discussion.append(f"Ở cấu hình trung tâm, phần gói sinh ra bị Selective Forwarding là {fate('EMHR_SF','selective_forwarding_fraction')}% với EMHR-SF và {fate('SF3','selective_forwarding_fraction')}% với S-EMHR. Phần gói không có tuyến tương ứng {fate('EMHR_SF','unreachable_fraction')}% và {fate('SF3','unreachable_fraction')}%. Giảm mất gói do tấn công đi kèm thay đổi mất gói do không có tuyến; TPR cao hơn không tự bảo đảm PDR/goodput hoặc tuổi thọ cao hơn. Bảng trạng thái gói giữ cả hai nguyên nhân và các chi phí radio đã đo.")
    methods = [
        f"Hoàn tất {len(rows)}/480 lượt hợp lệ, 16 cấu hình × 30 seed (51001–51030), 0 lượt lỗi/còn thiếu. Mỗi seed tạo topology độc lập; cùng seed giữa các treatment giữ topology và các stream ngoại sinh. Không loại seed vì kết quả bất lợi. Đơn vị thống kê là lượt/seed, không phải node, gói hoặc cửa sổ. Profile chính thức: {PROFILE}; job scope EVALUATION_FIXED_HORIZON_10000S, config_profile CUSTOM, không dùng nhãn PILOT/TEST_ONLY cho evaluation.",
        "Mỗi lượt quan sát t ∈ [0,10.000] giây, tối đa 1000 round, sinh gói mỗi 10 giây từ t=10 đến t=10.000. Xử lý toàn bộ sự kiện tại t=10.000 theo thứ tự hàng đợi SimPy, chốt detector tại thời điểm này, không chạy xả sau mốc. Gói đã sinh nhưng chưa có sự kiện kết thúc giữ pending_in_flight. PDR dùng toàn bộ gói sinh trong khoảng đo, bao gồm gói đang truyền ở mẫu số. Quy tắc cutoff được kiểm tra bằng ca một sensor: 1.000 gói sinh, 999 gói đến và 1 gói đang truyền.",
        "Giữ 450 sensor, 7 sink, vùng 3.000 × 3.000 m, E0=5 J, Eth=1 J, R=300 m, wire=payload=128 byte, chu kỳ 10 s, p_channel=0,01. Detector giữ beta=0,8; cửa sổ 40 s; timeout 0,02 s; minObs=2; tau=0,95; K=1; trust ban đầu=1; cách ly 60 s. Bán kính kế thừa quyết định pilot trước đó. Không sửa lõi, lock hoặc tham số để làm đẹp kết quả.",
        "Throughput = wire bit nhận duy nhất tại sink / 10.000 s; goodput = payload bit nhận / 10.000 s. Vì wire=payload, hai giá trị bằng nhau trong mô hình này. Năng lượng/bit = năng lượng sensor tiêu hao từ t=0 đến t=10.000 / payload bit nhận thành công. Delay và hop lấy đúng gói hoàn tất trước hoặc tại cutoff, không lấy giá trị cuối của lượt 100.000 s rồi đổi nhãn. Các trạng thái TP/FP/TN/FN, coverage, cảnh báo và cách ly đều chốt tại t=10.000.",
        "Mean và độ lệch chuẩn mẫu (ddof=1) tính trên seed có chỉ số xác định; CI95 = mean ± t(0,975,n−1)×std/√n. CSV giữ n_expected/n_used/n_missing và NA cho mẫu số 0. So sánh cặp trên matched seeds, xác minh pairing hash/topology/attacker IDs, dùng paired t và Wilcoxon-Pratt, hiệu chỉnh Holm trên toàn họ chỉ số/cặp đã khai báo. CI95 của chênh lệch cặp giữ trong CSV; không thay CI bằng error bar trong ảnh. CI tỷ lệ là khoảng t cho mean theo seed và có thể vượt [0,1]; không cắt để che biến thiên.",
        "Độ trễ phát hiện/cách ly thực theo attacker giữ NA nếu chưa thấy sự kiện. Chỉ số capped delay lấy min(delay,10.000) và dùng 10.000 cho attacker bị kiểm duyệt, rồi trung bình trong mỗi seed và qua 30 seed. Giá trị giới hạn không phải thời gian phát hiện thực của attacker chưa bị phát hiện. TPR/FPR tính trên toàn bộ sensor, coverage mô tả tập có đủ quan sát, không loại attacker không quan sát để tăng TPR.",
        "FND là sensor đầu tiên chết; HND là ít nhất 225/450 sensor chết; LND là toàn bộ 450 sensor chết. Mốc không xảy ra giữ time_s/payload=NA và censored=true, không gán 0 hoặc coi 10.000 s là thời điểm chết thật. Thời gian giới hạn là min(T,10.000 s). Payload trước mốc chỉ trung bình trong các lượt đạt mốc, không dùng để xếp hạng nhóm có mức kiểm duyệt khác nhau. Mốc mất chức năng theo physical/routing reachability là chỉ số khác với HND/LND.",
        "Hai ô payload trước HND/LND cũ không đủ quan sát để so sánh. Bộ hình chính đã thay bằng payload đến sink, sensor sống và năng lượng còn lại tại 10.000 s. Bảng dưới giữ n_observed/n_runs cho mọi mốc và mọi cấu hình. Cấu hình/phương pháp nằm trong báo cáo và metadata; ảnh chỉ giữ tiêu đề, trục/đơn vị, legend và số phía trên cột.",
        "Phạm vi 10.000 s được chọn theo yêu cầu người dùng sau khi đã xem checkpoint dài hạn, không phải đăng ký trước khi xem dữ liệu dài hạn. Toàn bộ 480 lượt này được chạy mới trong profile ngắn; không trộn mean hay delay/hop từ kết quả dài hạn. Báo cáo và dữ liệu 100.000 s cũ giữ riêng, không ghi đè.",
    ]
    limits = ["Quan sát 10.000 giây phản ánh hiệu năng ngắn hạn. Khi HND/LND chưa xảy ra, dữ liệu này không xác định hoặc chứng minh đầy đủ tuổi thọ dài hạn.", "Mô hình radio hiện tính năng lượng TX/RX, chưa có tiêu hao idle, MAC, ACK, hàng đợi, retransmission và chi phí giám sát/điều khiển. Các chi phí này giữ NA; không thể suy ra tổng chi phí triển khai thực hoặc mặc định S-EMHR rẻ hơn mọi mặt.", "Sensor còn sống nhưng mất kết nối vẫn có thể tồn tại lâu vì chưa có idle. Do đó còn pin, còn sống, còn đường đi và khả năng giao dữ liệu là các đại lượng khác nhau.", "Detector dùng quan sát lý tưởng từ SimPy, chưa mô phỏng overhearing/ACK thực. Cần kiểm chứng thêm với chi phí giao thức và horizon dài hơn để kết luận về triển khai."]
    stats_view = []
    for row in aggregates:
        if row["metric"] in METRICS:
            title, unit, factor = METRICS[row["metric"]]
        else:
            title, unit, factor = row["metric"], "đơn vị gốc trong CSV", 1
        stats_view.append({"Case ID": row["case_id"], "Chỉ số": title, "Đơn vị": unit, "n hợp lệ": row["n_used"], "n thiếu/NA": row["n_missing"], "Mean": formatted(row["mean"] * factor if row["mean"] is not None else None, 5), "Std mẫu": formatted(row["sample_std_ddof1"] * factor if row["sample_std_ddof1"] is not None else None, 5), "CI95 thấp": formatted(row["ci95_low"] * factor if row["ci95_low"] is not None else None, 5), "CI95 cao": formatted(row["ci95_high"] * factor if row["ci95_high"] is not None else None, 5)})
    sections = [("Phương pháp và quy tắc chốt dữ liệu", methods), ("Nhận xét ưu điểm và hạn chế", discussion), ("Giới hạn diễn giải", limits)]
    methods.insert(3, "Các mức attacker 2%, 5%, 10% là tỷ lệ yêu cầu; làm tròn nửa lên trên 450 sensor thành 9, 23, 45 attacker. Mức 5% thực tế là 23/450 ≈ 5,111%. Tập attacker không gồm sink; số lượng và tỷ lệ thực nằm trong manifest/CSV. Giữ cùng tập ID giữa các thuật toán trong cùng treatment; vị trí khác nhau thay tập ID theo quy tắc nhưng giữ topology và số lượng.")
    methods.append("Số quyết định tìm lại tuyến có nguyên nhân chính security chỉ đếm việc sửa một tuyến đã gán. Tuyến được chọn mới ngay khi sinh gói có thể tránh node cách ly mà không tạo sự kiện reroute. Vì vậy số đếm security bằng 0 không tự chứng minh S-EMHR không tránh relay hoặc không có chi phí bảo vệ; trạng thái bật/tắt tránh relay và các chi phí chưa mô phỏng được công bố riêng.")
    methods.append("Tỷ lệ 100% ở ô quan sát FND nghĩa là 30/30 lượt đã có ít nhất một sensor chết, không phải toàn bộ 450 sensor đã chết.")
    methods.append("Chuỗi thời gian được ghi mỗi 100 s để giảm chi phí lưu và tổng hợp; chu kỳ sinh gói vẫn là 10 s và mốc chết vẫn được ghi theo đúng sự kiện. Các chỗ còn ghi 1.000 s trong mẫu yêu cầu được thống nhất thành 10.000 s theo các mục cấu hình/nghiệm thu mới. Kế hoạch gốc có giới hạn 100.000 s; báo cáo hiện tại là phạm vi 10.000 s điều chỉnh theo yêu cầu, không tuyên bố thay thế đầy đủ nghiên cứu dài hạn. Bộ 1.000 s và 100.000 s cũ đều được bảo toàn.")
    visibility = [{"Hình": figure["figure"], "Số cột có số đo": len(figure["bars"]), "Cột dương": sum(bar["data_state"] == "positive" for bar in figure["bars"]), "Số 0 có điểm đánh dấu": sum(bar["data_state"] == "zero" and bar["zero_marker_shown"] for bar in figure["bars"]), "Cột thiếu dữ liệu": 0} for figure in figures if figure["bars"]]
    methods.append("Đã kiểm tra mọi cột từ CSV đến ảnh. Mean bằng 0 giữ chiều cao 0, có vòng tròn tại đường gốc và nhãn số để phân biệt với thiếu dữ liệu. Mean không xác định trong các hình chính làm xuất báo cáo dừng để kiểm tra; không điền số giả. Các mốc HND/LND thiếu quan sát chỉ ở bảng kiểm duyệt, không tạo ô hình trống. Bảng kiểm tra hiển thị và bar_visibility_audit.csv ghi trạng thái từng cột. Nhóm không bật detector không được vẽ trong ô chỉ dành cho detector; đây là chọn đúng phạm vi chỉ số, không phải bỏ dữ liệu bất lợi.")
    methods.append("Đồ thị độ nhạy dùng trục tung theo khoảng số liệu để nhìn rõ các mức đã đo, với nhãn mean tại từng điểm. Trục cột vẫn bắt đầu từ 0. Độ dốc nhìn thấy không tự chứng minh ý nghĩa thống kê; phải đọc cùng độ lớn chênh lệch, CI95 và so sánh cặp.")
    methods.append("Protocol hiệu lực ghi rõ quy tắc cutoff 10.000 s. Bản đăng ký gốc được giữ nguyên hash; một chuỗi mô tả còn sót 1.000 trong mẫu được đính chính riêng ở protocol_effective.json. Không đổi cấu hình chạy, kết quả, run ID hoặc completion hash vì chỉnh mô tả này.")
    methods.append("relay_security_per_seed.csv lưu bộ đếm nhận/chuyển tiếp/timeout/pending, trust và cờ nghi ngờ/cách ly của từng relay tại cutoff. Tỷ số F/N trong CSV này được ghi rõ là tỷ số tích lũy để đối chiếu, không phải forwarding ratio từng cửa sổ đã dùng cập nhật EWMA. Batch dùng full_trace=false để tiết kiệm tài nguyên; không tuyên bố đã lưu lại đầy đủ log từng gói hoặc lịch sử từng cửa sổ. Các bài kiểm tra module và demo chi tiết được giữ riêng trong dự án.")
    tables = [("Hiệu năng cấu hình trung tâm", center_table), ("Bảo mật cấu hình trung tâm", detector_view), ("So sánh cặp tại cấu hình trung tâm", paired), ("Độ nhạy của PDR", sensitivity), ("Kiểm tra hiển thị cột", visibility), ("Ma trận và số seed", design), ("Mốc chết và mất chức năng: quan sát/kiểm duyệt", lifetime_view), ("Thống kê đầy đủ: mean/std/CI95 theo seed", stats_view)]
    md = "# Hiệu năng và bảo mật WSN trong 10.000 giây\n\n**480/480 lượt; 16 cấu hình × 30 seed; lỗi=0; còn thiếu=0.**\n\n"
    links = '[Dữ liệu từng seed](runs.csv) · [CSV bảo mật](security_runs.csv) · [Trạng thái từng relay](relay_security_per_seed.csv) · [Kiểm tra cột](bar_visibility_audit.csv) · [Mean/std/CI95](aggregate.csv) · [So sánh cặp](paired_comparisons.csv) · [Kiểm chứng](verification.json) · [Bộ dữ liệu ZIP](du_lieu_10000s.zip)'
    md += links + "\n\n"
    for title, paragraphs in sections:
        md += "## " + title + "\n\n" + "\n\n".join(paragraphs) + "\n\n"
    for title, data in tables:
        md += "## " + title + "\n\n" + table_md(data) + "\n\n"
    md += "## Bộ biểu đồ\n\n"
    for figure in figures:
        md += f"![{figure['figure']}](bieu_do/{figure['figure']})\n\n[SVG](bieu_do/{figure['vector']}) · [CSV nguồn](bieu_do/{figure['data_csv']})\n\n"
    md += f"## Nguồn và tái tạo\n\nModel SHA256: `{plan['source_fingerprint']['sha256']}`. Plan hash: `{plan['plan_hash']}`. Batch gốc: `{batch}`. [Cấu hình](experiment_10000s.json), [plan](plan.json), [protocol hiệu lực](protocol_effective.json) · [protocol gốc](protocol.json), [provenance](analysis_provenance.json), [manifest nguồn](input_manifest.json), [hướng dẫn tái tạo](TAI_TAO.md).\n"
    (directory / "BAO_CAO_10000S.md").write_text(md, encoding="utf-8")
    css = '<style>body{font:16px/1.65 system-ui,sans-serif;color:#203448;background:#f1f5f8;margin:0}main{max-width:1450px;margin:auto;padding:28px}section,header{background:white;padding:24px;margin-bottom:20px;border-radius:10px}h1,h2{line-height:1.3}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:8px;border-bottom:1px solid #dce4ec;text-align:left}th{background:#eaf1f6;position:sticky;top:0}img{width:100%;height:auto}a{color:#17639d}.scroll{overflow:auto}code{overflow-wrap:anywhere}.badge{background:#d9f2e8;padding:8px 12px;border-radius:5px}details{margin:20px 0}</style>'
    document = '<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>WSN — báo cáo 10.000 giây</title>' + css + '<main><header><h1>Hiệu năng và bảo mật WSN trong 10.000 giây</h1><p class="badge">480/480 lượt · 16 cấu hình × 30 seed · lỗi=0 · còn thiếu=0</p><p><a href="BAO_CAO_10000S.md">Báo cáo Markdown</a> · <a href="runs.csv">Dữ liệu từng seed</a> · <a href="security_runs.csv">Bảo mật</a> · <a href="aggregate.csv">Mean/std/CI95</a> · <a href="paired_comparisons.csv">So sánh cặp</a> · <a href="verification.json">Kiểm chứng</a> · <a href="du_lieu_10000s.zip">ZIP đầy đủ</a> · <a href="TAI_TAO.md">Tái tạo</a></p></header>'
    for title, paragraphs in sections:
        document += f'<section><h2>{html.escape(title)}</h2>' + ''.join(f'<p>{html.escape(text)}</p>' for text in paragraphs) + '</section>'
    for title, data in tables:
        body = f'<div class="scroll">{pd.DataFrame(data).to_html(index=False, border=0, escape=True)}</div>'
        document += '<section>' + (f'<details><summary>{html.escape(title)}</summary>{body}</details>' if len(data) > 40 else f'<h2>{html.escape(title)}</h2>{body}') + '</section>'
    for figure in figures:
        document += f'<section><img src="bieu_do/{figure["figure"]}" alt="{html.escape(figure["figure"])}" loading="lazy"><p><a href="bieu_do/{figure["vector"]}">SVG</a> · <a href="bieu_do/{figure["data_csv"]}">CSV nguồn</a></p></section>'
    document += f'<section><h2>Nguồn và tái tạo</h2><p>Model SHA256: <code>{plan["source_fingerprint"]["sha256"]}</code></p><p><a href="analysis_provenance.json">Provenance</a> · <a href="input_manifest.json">Manifest đầu vào</a> · <a href="plan.json">Plan</a> · <a href="protocol_effective.json">Protocol hiệu lực</a> · <a href="protocol.json">Protocol gốc</a></p></section></main></html>'
    document = document.replace('<a href="security_runs.csv">Bảo mật</a>', '<a href="security_runs.csv">Bảo mật</a> · <a href="relay_security_per_seed.csv">Trạng thái relay</a> · <a href="bar_visibility_audit.csv">Kiểm tra từng cột</a>')
    (directory / "BAO_CAO.html").write_text(document, encoding="utf-8")


def write_reproduction(directory, batch, root, published_directory=None):
    command_report = published_directory or directory
    text = f'''# Tái tạo nghiên cứu 10.000 giây

Giữ Python và các phiên bản trong manifest. Dự án mô phỏng: `{root}`. Lõi và detector phải khớp source_snapshot.zip/frozen lock trước khi chạy.

```powershell
Set-Location '{root}'
& '.\\.venv\\Scripts\\python.exe' -B -X utf8 analysis\\security_10000s\\study.py dry-run --project .
& '.\\.venv\\Scripts\\python.exe' -B -X utf8 -m pytest -q -p no:cacheprovider analysis\\security_10000s\\test_profile.py
& '.\\.venv\\Scripts\\python.exe' -B -X utf8 analysis\\security_10000s\\study.py run --project . --output results\\security_10000s --workers 10
```

Lệnh run tạo batch mới 480 lượt, không ghi đè dữ liệu. Dùng đường dẫn batch vừa in cho report. Với batch hiện tại:

```powershell
& '.\\.venv\\Scripts\\python.exe' -B -X utf8 analysis\\security_10000s\\study.py status --project . --batch '{batch}'
& '.\\.venv\\Scripts\\python.exe' -B -X utf8 analysis\\security_10000s\\study.py resume --project . --batch '{batch}' --workers 10
& '.\\.venv\\Scripts\\python.exe' -B -X utf8 analysis\\security_10000s\\report_vi.py '{batch}' --project . --output results\\security_10000s_reports --pack-data
& '.\\.venv\\Scripts\\python.exe' -B -X utf8 analysis\\security_10000s\\verify_report.py '{batch}' '{command_report}' --project .
```

Resume chỉ bỏ qua lượt COMPLETE có hash hợp lệ. Không chạy unit test đồng thời với batch. Muốn chỉ vẽ lại, gọi report trên batch hoàn tất; không cần chạy lại 480 lượt. Bộ ZIP chứa raw/<run_id>/, báo cáo, CSV, ảnh, script phân tích và source_snapshot.zip. Đường dẫn tuyệt đối trong checkpoint/manifest giữ làm bằng chứng nơi đo gốc; portable_run_index.json ánh xạ từng run_id tới raw trong ZIP. Không sửa hash/lock để chuyển thư mục hoặc đổi profile. Kiểm tra hash bằng package_inventory.json. verification.json bên trong ZIP ghi pha kiểm tra trước khi đóng ZIP; verification.json bên cạnh ZIP ghi thêm kết quả kiểm tra gói và SHA256 của chính ZIP để tránh vòng lặp tự băm.

Các mốc chết NA/censored giữ nguyên; CI95 nằm trong bảng/CSV. Ảnh không có error bar, phụ đề cấu hình hoặc ghi chú cuối hình. Các kết quả dài hạn giữ riêng trong results/requested và results/requested_reports.
'''
    (directory / "TAI_TAO.md").write_text(text, encoding="utf-8")


def pack_dataset(directory, batch, records):
    from wsn_sim.experiment_execution import file_hash
    index = [{"run_id": record["job"]["run_id"], "case_id": record["job"]["case"]["case_id"], "seed": record["job"]["seed"], "archive_directory": "raw/" + record["job"]["run_id"], "original_directory": str(record["directory"])} for record in records]
    (directory / "portable_run_index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    files = []
    for path in directory.rglob("*"):
        if path.is_file() and path.name not in {"du_lieu_10000s.zip", "package_inventory.json"}:
            files.append((path, "report/" + path.relative_to(directory).as_posix()))
    for record in records:
        for path in record["directory"].iterdir():
            if path.is_file():
                files.append((path, "raw/" + record["job"]["run_id"] + "/" + path.name))
    for name in ("plan.json", "checkpoint.json", "protocol.json", "protocol_effective.json", "user_request_original.txt", "experiment_10000s.json", "source_snapshot.zip", "reuse_manifest.json"):
        if not (batch / name).exists():
            continue
        files.append((batch / name, "batch/" + name))
    for path in Path(__file__).parent.glob("*"):
        if path.is_file() and path.suffix in (".py", ".md"):
            files.append((path, "analysis/security_10000s/" + path.name))
    inventory = [{"path": name, "sha256": file_hash(path), "size": path.stat().st_size} for path, name in files]
    inventory_path = directory / "package_inventory.json"
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(directory / "du_lieu_10000s.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            archive.write(path, name)
        archive.write(inventory_path, "package_inventory.json")


def build_tables_and_figures(plan, checkpoint, records, directory):
    from wsn_sim.experiment_tables import make_tables
    rows, aggregates, completeness, comparisons = make_tables(plan, checkpoint, records, directory)
    lifetimes, sources = enrich(rows, records, directory)
    lifetime_table = extend_aggregates(plan, rows, aggregates, lifetimes, directory)
    comparisons = extend_comparisons(plan, rows, comparisons, directory)
    security_keys = ["case_id", "scenario", "rho", "p_drop", "placement", "seed", "run_id", "evaluation_time_s", "actual_attacker_count", "TP", "FP", "TN", "FN", "tpr", "fpr", "precision", "f1", "coverage", "detection_capped_delay_s", "isolation_capped_delay_s", "detection_event_coverage", "isolation_event_coverage", "isolation_events", "na_reasons"]
    security_keys.extend(["detector_enabled", "routing_avoidance_enabled", "detector_isolation_events", "security_reroute_decision_count", "unique_suspected_by_cutoff", "unique_isolated_by_cutoff"])
    export_csv([{key: row[key] for key in security_keys} for row in rows], directory / "security_runs.csv")
    export_csv([{key: value for key, value in row.items() if key not in set(security_keys) - {"case_id", "scenario", "rho", "p_drop", "placement", "seed", "run_id"}} for row in rows], directory / "performance_runs.csv")
    figures = draw_all(plan, rows, aggregates, records, directory / "bieu_do")
    return rows, aggregates, completeness, comparisons, lifetime_table, figures


def render_report(root, batch, output, pack=False, test_results=None, published_output_root=None):
    from wsn_sim.experiment_tables import collect_batch
    from wsn_sim.experiment_execution import file_hash
    from wsn_sim.storage import create_run_directory
    plan, checkpoint, records = collect_batch(batch, root)
    verify_short_plan(plan, root)
    if len(records) != 480 or checkpoint["status"] != "COMPLETE":
        raise ValueError("full report requires all 480 valid short runs")
    directory = create_run_directory(output.resolve(), "bao_cao_10000s")
    if test_results is not None:
        shutil.copy2(test_results, directory / "test_results.xml")
    rows, aggregates, completeness, comparisons, lifetime_table, figures = build_tables_and_figures(plan, checkpoint, records, directory)
    for name in ("plan.json", "protocol.json", "protocol_effective.json", "experiment_10000s.json"):
        shutil.copy2(batch / name, directory / name)
    provenance = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "project": str(root), "batch": str(batch), "profile": PROFILE, "plan_hash": plan["plan_hash"], "model_source_sha256": plan["source_fingerprint"]["sha256"], "analysis_files": {path.name: file_hash(path) for path in Path(__file__).parent.glob("*.py")}, "completed": len(records), "failed": 0, "pending": 0, "new_short_runs": 480, "reused_long_metrics": 0, "horizon_s": 10000, "max_rounds": 1000, "freeze": plan["freeze"]}
    (directory / "analysis_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    write_report(plan, rows, aggregates, completeness, comparisons, lifetime_table, figures, directory, batch)
    write_reproduction(directory, batch, root, published_output_root / directory.name if published_output_root else None)
    from verify_report import verify_report
    qa = verify_report(root, batch, directory, check_package=False)
    (directory / "verification_checks.json").write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    (directory / "verification.json").write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    if pack:
        pack_dataset(directory, batch, records)
    qa = verify_report(root, batch, directory, check_package=pack)
    (directory / "verification.json").write_text(json.dumps(qa, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_directory": str(directory), "completed": 480, "figures": len(figures), "verification": qa["status"]}, ensure_ascii=False, indent=2), flush=True)
    return directory


def main():
    parser = ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pack-data", action="store_true")
    parser.add_argument("--test-results", type=Path)
    parser.add_argument("--published-output-root", type=Path)
    args = parser.parse_args()
    root = load_project(args.project)
    render_report(root, args.batch.resolve(), args.output, args.pack_data, args.test_results, args.published_output_root)


if __name__ == "__main__":
    main()
