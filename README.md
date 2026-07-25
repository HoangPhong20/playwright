# Agoda Playwright Crawler

Crawler Python/Playwright để thu thập kết quả khách sạn Agoda theo nhiều
thành phố và ngày check-in. Output chính là JSONL theo ngày, phù hợp cho
phân tích giá, rating, review và số sao.

## Quick Start

Chạy bằng PowerShell từ thư mục dự án:

```powershell
cd D:\DE\PlayWright
.\venv\Scripts\Activate.ps1
python main.py --date-start 2026-06-10 --date-end 2026-06-10
```

Command trên dùng các default trong `.env` hiện tại:

```text
AGODA_DESTINATIONS=Vung Tau,Da Nang,Nha Trang
AGODA_MAX_PAGES=10
AGODA_HEADLESS=true
AGODA_ENRICH_DETAILS=true
AGODA_MAX_DETAIL_PAGES=0
AGODA_WORKERS=2
AGODA_DETAIL_CONCURRENCY=3
AGODA_MIN_OPTIONAL_COVERAGE=90
AGODA_OUTPUT_DIR=data/raw
```

`AGODA_MAX_PAGES=10` nghĩa là crawl tối đa 10 result pages cho mỗi city/date job. Detail enrichment đang bật và không giới hạn detail page.

## Run isolation and concurrency

Each invocation now creates a unique directory:

```text
<output-dir>/run_<UTC timestamp>_<id>/
  run_manifest.json
  agoda_hotels_<check-in>.jsonl
```

`run_manifest.json` stores the run ID, timestamps, effective CLI/.env config,
Git revision, and per-stay summary. This prevents a rerun from mixing JSONL
records with an earlier run.

Pagination never uses a constructed page URL. A page is accepted only after
listing content changes (canonical hotel URLs or first hotel identity), not
merely because the browser URL changed. Diagnostics are isolated in
`debug/<run-id>/<destination>/<check-in>/`.

`--detail-concurrency` is the maximum inside one crawl job.
`--total-detail-concurrency` / `AGODA_TOTAL_DETAIL_CONCURRENCY` is the global
cap across all jobs. The checked-in default is 3, so two outer workers cannot
open six detail browsers at once.

## Setup

Tạo môi trường lần đầu:

```powershell
cd D:\DE\PlayWright
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
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
python main.py --destinations "Vung Tau" `
  --date-start 2026-06-10 --date-end 2026-06-10 `
  --max-pages 1 --workers 1 --no-enrich-details
```

Production 3 city, 1 ngày, full pages, full detail:

```powershell
python main.py --date-start 2026-06-10 --date-end 2026-06-10
```

Override city/date khi cần:

```powershell
python main.py --destinations "Vung Tau,Da Nang,Nha Trang" `
  --date-start 2026-06-10 --date-end 2026-06-16
```

Ghi ra thư mục riêng để tránh append vào file cũ:

```powershell
python main.py --date-start 2026-06-10 --date-end 2026-06-10 `
  --output-dir data/raw/run_2026_06_10
```

## Runtime Tuning

Cấu hình mặc định cân bằng runtime và độ phủ dữ liệu:

```text
AGODA_WORKERS=2
AGODA_DETAIL_CONCURRENCY=3
AGODA_MIN_OPTIONAL_COVERAGE=90
AGODA_DETAIL_TIMEOUT=30000
AGODA_FIELD_RETRY_TIMEOUT=1200
AGODA_FIELD_RETRY_COUNT=2

AGODA_MAX_SCROLL_ROUNDS=50
AGODA_SCROLL_WAIT_MS=600
AGODA_STABLE_ROUNDS=3
AGODA_LISTING_FULL_SNAPSHOT_INTERVAL=5

AGODA_WAIT_AFTER_SEARCH=1000
AGODA_WAIT_AFTER_NAV=1000
AGODA_CARDS_TIMEOUT=35000
AGODA_CARDS_TIMEOUT_RETRY=15000
AGODA_URL_FALLBACK_CARDS_TIMEOUT=25000
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
- `--date-start` / `--date-end`: khoảng check-in batch. Mỗi check-in mặc định 1 đêm.
- `--check-in` / `--check-out`: dùng cho một stay cụ thể; khi dùng cặp này, đặt `--date-start= --date-end=`.
- `--max-pages`: số result pages tối đa mỗi city/date job; `0` là tất cả.
- `--workers`: số city/date jobs chạy song song.
- `--enrich-details` / `--no-enrich-details`: bật/tắt mở trang hotel detail.
- `--max-detail-pages`: giới hạn detail page; `0` là không giới hạn.
- `--detail-concurrency`: số detail pages song song trong mỗi job.
- `--output-dir`: thư mục JSONL output.

## Output And Debug

Output JSONL theo ngày:

```text
data/raw/agoda_hotels_YYYY-MM-DD.jsonl
```

Mỗi dòng là một hotel record JSON. File được ghi theo kiểu append, nên chạy lại
cùng ngày/cùng output dir sẽ cộng thêm dữ liệu.

Debug chính nằm trong:

```text
debug/
```

File thường gặp:

- `debug/missing_price_records.json`: record thiếu `price_value`.
- `debug/partial_missing_url_records.json`: record thiếu `hotel_url`.
- `debug/discarded_records.json`: record bị loại vì thiếu `hotel_name`, `hotel_url` hoặc `price_value`.
- `debug/pagination_errors/`: bằng chứng khi pagination duplicate hoặc bất thường.
- `debug/listing_errors/`: snapshot khi listing DOM khó parse.

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
- `agoda_crawler/orchestration.py`: tạo city/date jobs, chạy workers, ghi output và summary.
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
