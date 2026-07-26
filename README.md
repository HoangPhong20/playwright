# Agoda Playwright Crawler

Crawler Python/Playwright để thu thập kết quả khách sạn Agoda theo nhiều
thành phố và ngày check-in. Output chính là JSONL theo ngày, phù hợp cho
phân tích giá, rating, review và số sao.

## Quick Start

Chạy pipeline chính qua Airflow từ thư mục dự án:

```powershell
cd D:\DE\databrick\playwright
docker compose -f airflow/docker-compose.yml build
docker compose -f airflow/docker-compose.yml up -d
```

Mở <http://localhost:8080> và trigger DAG `agoda_daily_crawl`. Cấu hình
crawler và lịch chạy nằm trong root `.env`.

Các default crawler hiện tại:

```text
AGODA_DESTINATIONS=Vung Tau,Da Nang,Nha Trang,Ho Chi Minh
AGODA_MAX_PAGES=5
AGODA_HEADLESS=true
AGODA_WORKERS=2
AGODA_DETAIL_CONCURRENCY=3
AGODA_TOTAL_DETAIL_CONCURRENCY=3
```

`AGODA_MAX_PAGES=5` nghĩa là crawl tối đa 5 result pages cho mỗi city/date job.

## Airflow batch identity

When run through Airflow, the crawler does not create a UUID run ID. Every
invocation must provide `--airflow-dag-id`, `--airflow-run-id`, and
`--airflow-try-number`. Those values produce a deterministic `batch_id`, add
provenance fields to every public JSONL record, and isolate retry output under
`dag_id=<id>/batch_id=<id>/attempt=<number>/`.

For a manual invocation, provide explicit values, for example:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id manual_20260725_001 `
  --airflow-try-number 1 --date 2026-08-15
```

See `docs/DATABRICKS_INGESTION.md` for the manifest and ingestion-ledger
contract used to avoid loading one batch twice.

Each invocation writes to a deterministic Airflow batch directory:

```text
<output-dir>/dag_id=<id>/batch_id=<id>/attempt=<number>/
  run_manifest.json
  agoda_hotels_<check-in>.jsonl
```

`run_manifest.json` stores Airflow run metadata, timestamps, effective
CLI/.env config, Git revision, and per-stay summary. This prevents a retry
from mixing JSONL records with an earlier attempt.

Pagination never uses a constructed page URL. A page is accepted only after
listing content changes (canonical hotel URLs or first hotel identity), not
merely because the browser URL changed. Diagnostics are isolated in
`debug/<batch-id>/<destination>/<check-in>/`.

`--detail-concurrency` is the maximum inside one crawl job.
`--total-detail-concurrency` / `AGODA_TOTAL_DETAIL_CONCURRENCY` is the global
cap across all jobs. The checked-in default is 3, so two outer workers cannot
open six detail browsers at once.

## Setup

Tạo môi trường lần đầu:

```powershell
cd D:\DE\databrick\playwright
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
playwright install
```

Nếu `venv` đã có:

```powershell
cd D:\DE\PlayWright
.\venv\Scripts\Activate.ps1
```

## Common Commands

Smoke test nhanh, 1 city, 1 page, không mở detail:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id smoke_20260726_001 `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" `
  --date 2026-06-10 `
  --max-pages 1 --workers 1 --no-enrich-details
```

Chạy thủ công bốn city, một ngày, dùng default trong `.env`:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id manual_20260726_001 `
  --airflow-try-number 1 --output-dir data/airflow `
  --date 2026-06-10
```

Override city/date khi cần:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id override_20260726_001 `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau,Da Nang,Nha Trang,Ho Chi Minh" `
  --date 2026-06-16
```

Mỗi `airflow_run_id` và `airflow_try_number` phải là mới. Attempt đã có output
không thể dùng lại để tránh trộn dữ liệu.

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id comparison_20260726_001 `
  --airflow-try-number 1 --date 2026-06-10 `
  --output-dir data/airflow
```

## Runtime Tuning

Các giá trị dưới đây là profile tuning tham khảo. Giá trị runtime thực tế lấy
từ root `.env`; nếu không có thì dùng fallback trong `agoda_crawler/config.py`.

```text
AGODA_WORKERS=2
AGODA_DETAIL_CONCURRENCY=3
AGODA_MIN_OPTIONAL_COVERAGE=90
AGODA_DETAIL_TIMEOUT=30000
AGODA_FIELD_RETRY_TIMEOUT=1200
AGODA_FIELD_RETRY_COUNT=2

AGODA_MAX_SCROLL_ROUNDS=80
AGODA_SCROLL_WAIT_MS=1000
AGODA_STABLE_ROUNDS=3
AGODA_LISTING_FULL_SNAPSHOT_INTERVAL=10

AGODA_WAIT_AFTER_SEARCH=1200
AGODA_WAIT_AFTER_NAV=1500
AGODA_CARDS_TIMEOUT=45000
AGODA_CARDS_TIMEOUT_RETRY=20000
AGODA_URL_FALLBACK_CARDS_TIMEOUT=30000
AGODA_BLOCK_RESOURCE_TYPES=image,font,media
AGODA_BLOCK_URL_KEYWORDS=googletagmanager,google-analytics,doubleclick,facebook,hotjar,clarity,taboola
```

Nếu máy hoặc network yếu, hạ detail concurrency trước:

```text
AGODA_DETAIL_CONCURRENCY=2
AGODA_SCROLL_WAIT_MS=800
AGODA_STABLE_ROUNDS=3
```

Crawler thu listing record ngay trong từng vòng scroll, nên scroll tới đâu thì
dữ liệu trong page crawl được merge tới đó. JSONL cuối vẫn được ghi sau khi job
hoàn tất detail enrichment.
Trong lúc scroll, crawler dùng snapshot nhẹ cho các vòng poll và chỉ chạy
snapshot đầy đủ định kỳ/cuối page để giảm số lần quét DOM/HTML lớn.

Network route blocking mặc định chặn image/font/media request và một số tracking
URL để giảm tải cho browser.

## Important Arguments

- `--destinations`: danh sách thành phố, phân tách bằng dấu phẩy.
- `--date`: ngày check-in duy nhất. Check-out luôn tự động là ngày kế tiếp.
- `--max-pages`: số result pages tối đa mỗi city/date job; `0` là tất cả.
- `--workers`: số city/date jobs chạy song song.
- `--enrich-details` / `--no-enrich-details`: bật/tắt mở trang hotel detail.
- `--max-detail-pages`: giới hạn detail page; `0` là không giới hạn.
- `--detail-concurrency`: số detail pages song song trong mỗi job.
- `--output-dir`: thư mục JSONL output.

## Output And Debug

Output JSONL theo ngày:

```text
data/airflow/dag_id=<dag-id>/batch_id=<batch-id>/attempt=<try>/
  agoda_hotels_YYYY-MM-DD.jsonl
  run_manifest.json
```

Mỗi dòng là một hotel record JSON có thêm provenance Airflow: `batch_id`,
`airflow_dag_id`, `airflow_run_id`, và `airflow_try_number`.

Debug của một batch nằm trong:

```text
debug/<encoded-batch-id>/<destination>/<check-in>/
debug/<encoded-batch-id>/summary/<check-in>/
```

File thường gặp:

- `summary/<check-in>/missing_price_records.json`: record thiếu `price_value`.
- `summary/<check-in>/partial_missing_url_records.json`: record thiếu `hotel_url`.
- `summary/<check-in>/discarded_records.json`: record bị loại vì thiếu `hotel_name`, `hotel_url` hoặc `price_value`.
- `<destination>/<check-in>/pagination_errors/`: bằng chứng khi pagination duplicate hoặc bất thường.
- `<destination>/<check-in>/listing_errors/`: snapshot khi listing DOM khó parse.

## Verify Runs

Khi crawl xong, kiểm tra log:

- `Run: destinations=... stays=... jobs=... pages=all`
- `Concurrency: workers=2 detail=3`
- `Page N done: records=... new=... total=... time=...`
- `Detail: enriching ... records with 3 workers`
- `Timing total: search=... listing=... detail=... total=... bottleneck=...`
- `Network: blocking types=font,image,media keywords=7`
- `VERIFY_OPTIONAL_COVERAGE_STATUS=success` hoặc `warning`
- `VERIFY_DISCARDED_RECORDS=...`

Nếu nhiều page liên tiếp `new=0` hoặc `duplicate`, dữ liệu có thể đã bão hòa hoặc Agoda đang trả page lặp.
Record thiếu `hotel_name`, `hotel_url` hoặc `price_value` sẽ bị loại khỏi JSONL public và lưu để debug, nhưng không làm process fail. `rating_text`, `review_count_text` và `star_rating_text` vẫn được ghi khi thiếu; mỗi field cảnh báo nếu coverage không vượt `90%`.

## Tests

Chạy toàn bộ test:

```powershell
python -m pytest
```

Chạy không tạo pytest cache:

```powershell
python -B -m pytest -p no:cacheprovider
```

## Project Layout

- `main.py`: CLI entrypoint, parse args và gọi orchestration.
- `agoda_crawler/config.py`: đọc `.env`, biến môi trường, timeout và runtime defaults.
- `agoda_crawler/orchestration.py`: tạo city/date jobs, chạy workers, ghi output immutable, manifest và summary.
- `agoda_crawler/jobs.py`: parse destinations/date range và tạo job matrix.
- `agoda_crawler/crawler.py`: điều phối một crawl job end-to-end.
- `agoda_crawler/navigation/`: homepage/search URL flow và pagination navigation.
- `agoda_crawler/listing/`: scroll listing, collect snapshot, dedupe/merge record, pagination state.
- `agoda_crawler/extraction/`: selector/parser cho listing fields.
- `agoda_crawler/enrichment/`: mở hotel detail page để bổ sung field thiếu.
- `agoda_crawler/utils/`: logging, JSONL, debug artifacts, metrics và page helpers.
- `tests/`: pytest suite cho parser, config, listing collection, crawler helpers và navigation.
- `data/`: crawl output, transient.
- `debug/`: diagnostics, transient.

## Operational Notes

- Không commit credentials, cookies, PII hoặc crawl output lớn.
- `data/` và `debug/` là transient; dùng `--output-dir` riêng cho run cần so sánh.
- Full detail tốn thời gian vì mỗi hotel có thể cần mở detail page.
- Với `workers=2` và `detail-concurrency=3`, runtime có thể mở khoảng 6
  detail pages song song; nên dùng máy RAM 8 GB tối thiểu, 16 GB tốt hơn.
