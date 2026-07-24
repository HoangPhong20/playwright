# Project context

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
  -> filter publishable records -> append JSONL + summary/debug artifacts
```

`--workers` chỉ song song hóa các city/date job. Một run chỉ có một destination và một ngày chỉ tạo một job, nên giá trị hiệu dụng của `--workers` khi đó là 1. `--detail-concurrency` mới song song hóa các trang hotel detail trong job đó.

## Bản đồ code

| Khu vực | Trách nhiệm |
|---|---|
| `main.py` | Parse CLI rồi gọi orchestration; không đặt business logic ở đây. |
| `agoda_crawler/config.py` | Đọc `.env`, ưu tiên environment variables và tạo runtime defaults. |
| `jobs.py` | Parse destination/date, tạo job matrix, annotation và output path. |
| `orchestration.py` | Chạy outer workers, lọc record thiếu field bắt buộc, ghi JSONL, in summary và cảnh báo coverage. |
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

Chỉ dùng `AGODA_DETAIL_CONCURRENCY` và CLI `--detail-concurrency`. Không thêm lại `AGODA_DETAIL_WORKERS` hay `--detail-workers`.

Record public phải có `hotel_name`, `hotel_url` và `price_value`. `rating_text`, `review_count_text`, `star_rating_text` là optional; coverage từng field phải lớn hơn `AGODA_MIN_OPTIONAL_COVERAGE` (mặc định `90`) để không có warning. Các warning này không làm job fail.

CLI có độ ưu tiên cao hơn `.env`; environment variable có độ ưu tiên cao hơn giá trị trong `.env`.

## Lưu ý kỹ thuật

- Network routing mặc định chặn `image,font,media` và các URL tracking để giảm tải browser.
- Listing được merge/dedupe giữa các vòng scroll và giữa pagination. Chênh lệch giữa tổng record từng page với tổng cuối có thể là record trùng giữa page.
- Output JSONL là append-only. Dùng `--output-dir` riêng khi benchmark hoặc rerun để không trộn dữ liệu giữa các lần chạy.
