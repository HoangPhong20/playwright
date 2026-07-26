# Runbook

## Chuẩn bị

Chạy lệnh từ root repository:

```powershell
cd D:\DE\databrick\playwright
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
playwright install
```

Mặc định `.env` chạy headless, outer workers là 2 và detail concurrency là 3.

## Run output and detail cap

Each unique `airflow_run_id` and `airflow_try_number` creates one immutable
attempt directory with a `run_manifest.json`. For a 2-worker/3-detail setup,
keep the global cap at 3:

```text
AGODA_TOTAL_DETAIL_CONCURRENCY=3
```

Use `--total-detail-concurrency` only when intentionally overriding that cap.

## Smoke test listing

Lệnh này không crawl detail nên nhanh và phù hợp để kiểm tra selector/pagination:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id smoke_20260815_001 `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date 2026-08-15 `
  --max-pages 2 --no-enrich-details
```

## Crawl có detail

Không thêm `--no-enrich-details` nếu muốn so sánh `detail-concurrency`:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id detail_20260815_001 `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date 2026-08-15 `
  --max-pages 2
```

## Benchmark detail concurrency

Giữ nguyên city/date/max-pages và dùng output directory khác nhau:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id compare_detail_2_20260815 `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date 2026-08-15 `
  --max-pages 2 --detail-concurrency 2

python main.py --airflow-dag-id adhoc --airflow-run-id compare_detail_3_20260815 `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date 2026-08-15 `
  --max-pages 2 --detail-concurrency 3
```

So sánh `seconds=...`, `detail_sum=...`, coverage và số record publishable. Không chọn cấu hình nhanh hơn nếu coverage thấp hơn hoặc có pagination duplicate.

## Đọc kết quả

- `pages=2/2 duplicate=0`: crawl đủ page yêu cầu và không phát hiện page lặp.
- `page_records`: số unique record trong từng page trước khi merge toàn run.
- `records`: số record publishable sau khi lọc thiếu trường bắt buộc.
- `timing`: `search_sum`, `listing_sum`, `detail_sum`; dùng để xác định bottleneck.
- `VERIFY_COVERAGE_STATUS=success`: không có record bị loại vì thiếu `hotel_name`, `hotel_url` hoặc `price_value`.
- `VERIFY_OPTIONAL_COVERAGE_STATUS`: `success` khi coverage của từng field rating/review/star lớn hơn `90%`; `warning` không làm job fail.
- `VERIFY_DISCARDED_RECORDS`: số record không được ghi vào JSONL public.

## Test

```powershell
python -m pytest
```
