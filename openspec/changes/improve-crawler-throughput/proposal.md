# Proposal

## Why

Crawler cần tăng số bản ghi public hợp lệ/phút trên profile 4 thành phố × 5 trang mà vẫn chứng minh đã thu đủ listing. Mốc lịch sử do người dùng cung cấp là 2.722 giây và 42,2 bản ghi/phút ngày 19/10/2026; cần baseline mới vì code hiện còn trộn embedded-only candidates vào listing, đọc lại toàn bộ detail fields và tạo HTML preview cho mọi card.

## What Changes

- Thêm metrics listing/detail ở cấp page/job/batch, giữ số liệu của cả ứng viên bị discard và các lần pagination thử lại; không thay schema JSONL public.
- Trước baseline, giới hạn embedded vào identity đã quan sát từ hotel cards trong cùng trang; bảo vệ partial/full merge, phân biệt `propertyId` và chặn đường fallback đưa ứng viên ngoài listing trở lại.
- Phân biệt dừng trang do đã ổn định/hết vùng cuộn với hết budget; truyền `incomplete` lên job và ngăn completion pointer. Pagination phải có identity mới cùng ít nhất hai tín hiệu hiện có.
- Sau baseline, chỉ extract/retry detail fields còn thiếu, fallback theo kết quả parse từng field và đọc body tối đa một lần mỗi extraction.
- Giảm HTML preview/payload lặp nhưng giữ nguyên bằng chứng lọc carousel/filter, full snapshot interval, merge trong lúc cuộn và cấu hình chờ.
- Đo ABBA với detail concurrency 3/2/2/3, workers=2, tổng detail cap=3; xác nhận bằng hai lượt full candidate trên cùng profile và ngày lưu trú.
- Chỉ chấp nhận cải thiện khi median throughput tăng và cả hai lượt full candidate cao hơn median hai baseline; không đặt mức tăng phần trăm tối thiểu. Discard ≤10% là tiêu chí benchmark, không thêm quality gate pipeline.

## Capabilities

### New Capabilities

- `crawler-throughput`: quy tắc membership, completeness, extraction có chọn field, metrics và phép benchmark tái lập cho crawler local. Đây là lần đầu ghi capability vào OpenSpec; nhiều contract được kế thừa từ code hiện có.

### Modified Capabilities

Không có capability hiện hữu trong `openspec/specs/` tại thời điểm lập plan.

## Impact

- Code dự kiến: `agoda_crawler/listing/{collection,page_crawl,pagination,records}.py`, `extraction/{fields,selectors}.py`, `enrichment/detail.py`, `crawler.py`, `jobs.py`, `orchestration.py`, `utils/{crawl_metrics,run_output,debug_artifacts}.py`; `main.py`/`config.py` chỉ nếu có thay đổi mặc định được benchmark xác nhận.
- Tests: listing, page crawl, pagination, extraction/detail resources, orchestration/output và compatibility manifest hiện có. Tài liệu vận hành: `docs/RUNBOOK.md`, `docs/DATA_QUALITY.md`, README khi cần mô tả profile.
- API nội bộ `extract_detail_fields(page, *, fields=None)` mở rộng tương thích caller cũ; `fields=()` không đọc DOM. Metrics/stop reason cấp page là trường bổ sung trong manifest, không thay job success reasons hoặc nới validator.
- Không đổi CLI identity, JSONL business fields, giá VND, optional coverage warning, semaphore/global cap, browser reuse, upload hay ETL. Airflow/Databricks chỉ được kiểm tra contract bằng test local; không sửa hoặc chạy live components đó.
- Không thêm dependency runtime. Hoãn dedupe index, async/pool mới, đổi nhãn detail success, thêm enrichment fields và mục tiêu cứu đủ tám record thiếu giá lịch sử.
- Bước hiện tại chỉ tạo artifacts; không sửa code sản phẩm, commit, benchmark hoặc chạy crawler. Triển khai và live validation thuộc bước apply được yêu cầu sau.
