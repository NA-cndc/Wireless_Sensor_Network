# Cài đặt và kiểm tra trên Ubuntu

## Điều kiện ban đầu

- Đang ở repository `Wireless_Sensor_Network` và branch `XB`.
- Python 3.10 trở lên và `pip` đã được cài.
- Không dùng `sudo pip install` và không nâng cấp Python hệ thống.

Kiểm tra trạng thái trước khi thao tác:

```bash
pwd
git remote -v
git branch --show-current
git status --short --branch
python3 --version
```

## Tạo môi trường ảo

Chỉ chạy lệnh tạo nếu `.venv` chưa tồn tại:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Mỗi terminal mới cần chạy lại lệnh `source`. Có thể xác nhận interpreter đang
được dùng bằng:

```bash
python -c "import sys; print(sys.executable)"
```

Đường dẫn in ra phải trỏ vào `.venv/bin/python` của repository.

## Cài package và dependency

`pyproject.toml` là nguồn khai báo package chính. Cài package editable cùng bộ
test bằng:

```bash
python -m pip install -e ".[dev]"
python -m pip check
python -c "import networkx, simpy, numpy, pandas, matplotlib; print('imports=OK')"
```

Hai file requirements chỉ là entry point tương đương:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

Không cần chạy cả hai cách nếu đã cài `.[dev]`.

## Xác nhận dự án

```bash
python -m pytest -q
python scripts/run_demo.py
ls -lh results/csv
ls -lh results/figures
ls -lh results/run_manifest.json
```

Matplotlib được ép dùng backend `Agg`, vì vậy demo chạy được trên Ubuntu server
không có display. Nếu import thất bại, kiểm tra lại terminal đã kích hoạt đúng
`.venv` và chạy `python -m pip check`; không cài package vào Python hệ thống để
né lỗi.
