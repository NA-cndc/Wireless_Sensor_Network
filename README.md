# Mô phỏng mạng cảm biến không dây WSN

Profile chính chạy tối đa **10.000 giây**, tương ứng 1.000 round ở chu kỳ 10 giây. Mô phỏng dừng sớm tại LND nếu tất cả cảm biến đã chết. Cấu hình chính dùng 450 cảm biến danh định. Topology rút 400–500 cảm biến theo seed và đặt 7 sink cố định trong vùng 3.000 × 3.000 m. E0 = 5 J, Eth = 1 J, gói 128 byte. Bán kính chính của mô phỏng bảo mật là 300 m.

CSV định kỳ giữ mẫu đầu tiên có 0 sensor sống hoặc 0 sensor sống nối vật lý tới sink, kể cả tại t=0. Manifest ghi seed topology, số sensor thực, hash topology và `log_end_s`. Chỉ số cuối lượt dùng `elapsed_s` ở nền hoặc `actual_duration_s` ở batch bảo mật.

```text
src/wsn_sim/             Lõi bảo mật, topology và provenance dùng chung
analysis/foundation/    Runner và thuật toán nền
analysis/security_10000s/  Điều phối và báo cáo profile bảo mật 10.000 s
configs/                 Profile bảo mật và khóa hiệu chỉnh theo phiên bản
tests/                   Kiểm thử lõi và các đường chạy
data/, results/          Dữ liệu công bố và đầu ra
```

## Cài đặt và kiểm thử trên Windows

Các lệnh dưới đây dùng Python 3.12.10. Thư mục clone có thể chứa dấu cách.

```powershell
git clone https://github.com/NA-cndc/Wireless_Sensor_Network.git 'WSN 10000s'
Set-Location -LiteralPath 'WSN 10000s'
py -3.12 -m venv .venv
$py = (Resolve-Path '.\.venv\Scripts\python.exe').Path
& $py -m pip install -r analysis/requirements-10000s.txt
& $py -m pip install --no-deps -e .
& $py -m pytest -q tests test_env.py analysis/security_10000s/test_profile.py --basetemp results/pytest
```

## Chạy profile chính

CLI chính là `python -m analysis.wsn`, đọc cấu hình kế thừa từ `configs/default.json`. Các entry point `main.py` và `wsn-sim` dùng profile lịch sử `configs/plan.json`. Lệnh dưới đây chạy ba ca kiểm thử ghép cặp với seed 51001 và profile 10.000 giây. SF3 dùng detector `TEST_ONLY`, tỷ lệ attacker 5%, xác suất bỏ gói 0,5 và vị trí ngẫu nhiên.

```powershell
foreach ($case in @('MHR', 'EMHR', 'SF3')) {
    & $py analysis/security_10000s/study.py sample --test-only --scenario $case --output "results/check/$case"
    if ($LASTEXITCODE -ne 0) { throw "Mô phỏng lỗi với $case" }
}
```

Smoke test CLI bên dưới chỉ chạy 30 giây. Demo topology chỉ chạy 10 giây. Để chạy đủ bảy kịch bản nền và vẽ hình, bỏ `--plots-only` khỏi lệnh dựng hình ở mục tiếp theo.

```powershell
& $py -m analysis.wsn --algorithm S_EMHR --detector-config configs/detector_test_only.json --attacker-ratio 0.05 --p-drop 0.5 --duration 30
& $py -m analysis.foundation.demo
```

## Dựng lại bảng và hình từ dữ liệu công bố

Git tải cả dữ liệu nền lẫn gói bảo mật. Lệnh tái tạo bảo mật kiểm SHA-256 của ZIP, từng tệp trong gói, fingerprint nguồn, detector và các tệp đầu ra của từng lượt trước khi tính lại bảng và vẽ hình.

```powershell
Get-FileHash -Algorithm SHA256 data/security_10000s.zip
& $py analysis/run_foundation_study.py --report-only --output results/rebuilt-foundation
& $py analysis/run_analysis.py --plots-only --input results/csv --source-index results/figures/sources.json --output results/rebuilt-figures
& $py analysis/security_10000s/reproduce.py --output results/rebuilt-security
```

SHA-256 của `data/security_10000s.zip` là `55be594df949a03501e1063acbcbd21d9d1ba7757be441aef01c711e335a476b`. Gói có chỉ mục tương đối `report/portable_run_index.json`, dữ liệu tại `raw/<run_id>/` và mã nguồn nguyên gốc tại `batch/source_snapshot.zip`. Dùng `Expand-Archive -LiteralPath data/security_10000s.zip -DestinationPath results/security-package` nếu muốn mở gói thủ công. Giữ các thư mục xuất ở trên là đường dẫn mới khi chạy lại.

Bộ kiểm toán detector gồm 223 lượt chạy và bản khóa nguồn gốc trong [results/security_audit/archive](results/security_audit/archive/). Hai lệnh dưới đây kiểm chứng dữ liệu lưu trữ và dựng lại báo cáo vào `results/security_audit/`.

```powershell
& $py analysis/security_audit/verify_results.py
& $py analysis/security_audit/build_report.py
```

## Chạy lại ma trận 10.000 giây

Kết quả chạy với topology NA gồm [hình nền](results/published-10000s-na/foundation/figures/), [so sánh nền trên 30 seed](results/published-10000s-na/foundation/study/na-so-sanh-30-seed.png) và [10 biểu đồ bảo mật](results/published-10000s-na/security/figures/). Bảng tổng hợp, CSV của từng biểu đồ và kết quả xác minh 480 lượt nằm trong [thư mục bảo mật](results/published-10000s-na/security/).

Dùng khóa `configs/detector_na.json` cho mã và profile NA ở bản này. Nếu thay đổi phiên bản nguồn hoặc cấu hình hiệu chỉnh, chạy lại protocol stage78 và lưu khóa ở đường dẫn mới.

```powershell
& $py analysis/security_10000s/study.py dry-run --detector-config configs/detector_na.json
```

```powershell
New-Item -ItemType Directory -Force results/calibration | Out-Null
& $py scripts/run_calibration.py --config configs/default.json --protocol configs/calibration_stage78_protocol.json --output results/calibration --freeze results/calibration/detector_na.json
& $py analysis/security_10000s/study.py dry-run --detector-config results/calibration/detector_na.json
```

```powershell
& $py analysis/run_analysis.py --output results/new-foundation-figures
& $py analysis/run_foundation_study.py --workers 6 --output results/new-foundation-study
& $py analysis/security_10000s/study.py run --detector-config configs/detector_na.json --workers 6 --output results/new-security-study
```

Ghi lại thư mục `batch_directory` do lệnh cuối in ra để dùng với `study.py resume --batch <thư-mục>` hoặc `report_vi.py <thư-mục> --output results/new-security-report`. Các lệnh chọn dữ liệu theo cấu hình, seed, phiên bản nguồn và hash. Khi so hai bộ ba ca đại diện, dùng `python analysis/compare_10000s.py <kết-quả-A> <kết-quả-B>`.

Xem [đối chiếu kế hoạch và dữ liệu](docs/kiem-chung-10000s.md) và [nghiệm thu mô phỏng nền](docs/foundation_acceptance_10000s.md).
