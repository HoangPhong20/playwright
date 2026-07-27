# Project context

## Run isolation and concurrency

Each execution writes to
`<output-dir>/dag_id=<id>/batch_id=<id>/attempt=<number>/` with a
`run_manifest.json` containing Airflow run metadata, effective configuration,
Git revision, timestamps, and stay summaries. Each attempt directory is
immutable once it contains output.

`AGODA_DETAIL_CONCURRENCY` limits detail work inside one job.
`AGODA_TOTAL_DETAIL_CONCURRENCY` limits detail browser workers across all
outer workers; the default is 3. Detail records use a shared queue per job,
not static chunks. Pagination accepts a page only when listing content changes,
never from a generated page URL alone.

## Mục tiêu

Đây là Python crawler dùng Playwright Sync API để thu kết quả tìm khách sạn Agoda theo destination và ngày check-in. Mỗi record được ghi JSONL theo ngày check-in, phục vụ phân tích giá, rating, review và sao.

Crawler tương tác với giao diện Agoda qua luồng tìm kiếm trên homepage.

## Luồng xử lý

```text
CLI / .env
  -> jobs: destination x check-in date
  -> outer workers (mỗi worker có Playwright browser riêng)
  -> homepage/search -> listing page
  -> scroll + snapshot + merge/dedupe
  -> verified pagination
  -> optional detail enrichment (detail-concurrency trong từng job)
  -> immutable attempt directory -> JSONL + run_manifest.json
  -> completed_attempt.json -> verify -> upload to Unity Catalog Volume
  -> trigger Databricks Job: Bronze -> Silver -> Gold
```

Airflow là orchestrator giữa crawler và Databricks. Databricks Job là
orchestrator bên trong lớp dữ liệu, nhận một `manifest_path` cụ thể rồi chạy
các notebook phụ thuộc nhau. Job không quét rộng `*.jsonl` trong Volume.

`--workers` chỉ song song hóa các city/date job. Mỗi cặp destination × check-in
tạo một job; với bốn thành phố và một ngày, run hiện tại có bốn job nên
`workers=2` có thể chạy hai job song song. `--detail-concurrency` song song hóa
các trang hotel detail trong từng job; `--total-detail-concurrency` là giới hạn
chung cho tất cả job.

## Bản đồ code

| Khu vực | Trách nhiệm |
|---|---|
| `main.py` | Parse CLI rồi gọi orchestration; không đặt business logic ở đây. |
| `agoda_crawler/config.py` | Đọc `.env`, ưu tiên environment variables và tạo runtime defaults. |
| `jobs.py` | Parse destination/date, tạo job matrix, annotation và output path. |
| `orchestration.py` | Chạy outer workers, tạo output immutable theo Airflow run/attempt, ghi manifest, JSONL, summary và completion pointer. |
| `crawler.py` | Vòng đời một job: search, listing, pagination, enrichment và timing. |
| `navigation/` | Homepage flow, search, URL và xác minh chuyển trang. |
| `listing/` | Scroll, snapshot DOM, merge/dedupe record, pagination state. |
| `extraction/` | Selector và parser của listing/detail fields. |
| `enrichment/` | Chọn record thiếu field và crawl trang detail song song. |
| `utils/` | JSONL, metrics, debug artifacts, logging, network blocking. |
| `tests/` | Unit tests cho parser, config, listing, navigation và helper. |

## Cấu hình đang dùng

`.env` hiện đặt:

```text
AGODA_HEADLESS=true
AGODA_WORKERS=2
AGODA_DETAIL_CONCURRENCY=3
```

Dùng `AGODA_DETAIL_CONCURRENCY` / `--detail-concurrency` cho mỗi job và
`AGODA_TOTAL_DETAIL_CONCURRENCY` / `--total-detail-concurrency` làm giới hạn
chung. Không thêm lại `AGODA_DETAIL_WORKERS` hay `--detail-workers`.

Record public phải có `hotel_name`, `hotel_url` và `price_value`. `rating_text`, `review_count_text`, `star_rating_text` là optional; coverage từng field phải lớn hơn `AGODA_MIN_OPTIONAL_COVERAGE` (mặc định `90`) để không có warning. Các warning này không làm job fail.

CLI có độ ưu tiên cao hơn `.env`; environment variable có độ ưu tiên cao hơn giá trị trong `.env`.

## Lưu ý kỹ thuật

- Network routing mặc định chặn `image,font,media` và các URL tracking để giảm tải browser.
- Listing được merge/dedupe giữa các vòng scroll và giữa pagination. Chênh lệch giữa tổng record từng page với tổng cuối có thể là record trùng giữa page.
- Khi benchmark hoặc rerun thủ công, dùng `airflow_run_id` hoặc
  `airflow_try_number` mới thay vì ghi vào attempt cũ.
