# Agoda Playwright Crawler

Crawler Python/Playwright để thu thập kết quả khách sạn Agoda theo nhiều
thành phố và ngày check-in. Output chính là JSONL theo ngày, phù hợp cho
phân tích giá, rating, review, vị trí, ảnh và dữ liệu detail.

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
AGODA_MAX_PAGES=0
AGODA_HEADLESS=true
AGODA_ENRICH_DETAILS=true
AGODA_MAX_DETAIL_PAGES=0
AGODA_WORKERS=3
AGODA_DETAIL_CONCURRENCY=3
AGODA_OUTPUT_DIR=data/raw
```

`AGODA_MAX_PAGES=0` nghĩa là crawl đến khi pagination dừng. Detail enrichment đang bật và không giới hạn detail page.

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

Cấu hình mặc định đang ưu tiên full detail trước, tốc độ sau:

```text
AGODA_WORKERS=3
AGODA_DETAIL_CONCURRENCY=3
AGODA_DETAIL_TIMEOUT=30000
AGODA_FIELD_RETRY_TIMEOUT=1200
AGODA_FIELD_RETRY_COUNT=2

AGODA_MAX_SCROLL_ROUNDS=50
AGODA_SCROLL_WAIT_MS=600
AGODA_SCROLL_PAUSE=600
AGODA_PAGE_SCROLL_ROUNDS=40
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
AGODA_DETAIL_WORKERS=2
AGODA_SCROLL_WAIT_MS=800
AGODA_SCROLL_PAUSE=800
```

Crawler thu listing record ngay trong từng vòng scroll, nên scroll tới đâu thì
dữ liệu trong page crawl được merge tới đó. JSONL cuối vẫn được ghi sau khi job
hoàn tất detail enrichment.
Trong lúc scroll, crawler dùng snapshot nhẹ cho các vòng poll và chỉ chạy
snapshot đầy đủ định kỳ/cuối page để giảm số lần quét DOM/HTML lớn.

Network route blocking mặc định chặn image/font/media request và một số tracking
URL. Crawler vẫn đọc `image_url` từ DOM attributes; nếu coverage ảnh giảm trên
site live, bỏ `image` khỏi `AGODA_BLOCK_RESOURCE_TYPES`.

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
- `debug/pagination_errors/`: bằng chứng khi pagination duplicate hoặc bất thường.
- `debug/listing_errors/`: snapshot khi listing DOM khó parse.

## Verify Runs

Khi crawl xong, kiểm tra log:

- `Run: destinations=... stays=... jobs=... pages=all`
- `Concurrency: workers=3 detail=3`
- `Page N done: records=... new=... total=... time=...`
- `Detail: enriching ... records with 3 workers`
- `Timing total: search=... listing=... detail=... total=... bottleneck=...`
- `Network: blocking types=font,image,media keywords=7`
- `VERIFY_COVERAGE_STATUS=success`

Nếu nhiều page liên tiếp `new=0` hoặc `duplicate`, dữ liệu có thể đã bão hòa hoặc Agoda đang trả page lặp.
Run full detail không giới hạn sẽ fail process nếu còn thiếu `price_value`.
Run smoke/partial có `--max-detail-pages > 0` chỉ cảnh báo coverage.

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
- Với `workers=3` và `detail-concurrency=3`, runtime có thể mở khoảng 9
  detail pages song song; nên dùng máy RAM 8 GB tối thiểu, 16 GB tốt hơn.
