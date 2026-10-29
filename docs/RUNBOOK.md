# Runbook crawler local

Chạy lệnh PowerShell từ root repository sau khi hoàn tất phần cài môi trường
trong [README](../README.md). Dùng `py` cho Python local trên Windows.
Vận hành pipeline đầy đủ xem [Airflow README](../airflow/README.md) và
[Databricks README](../databricks/README.md).

## Smoke test listing

Dùng ngày tương lai và run identity mới mỗi lần chạy. Lệnh dưới đây giới hạn
một destination, một worker, một page và tắt detail enrichment:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString('yyyy-MM-dd')
$runId = 'smoke_' + [guid]::NewGuid().ToString('N')
py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" --date $checkIn `
  --max-pages 1 --workers 1 --no-enrich-details
```

Để kiểm tra pagination, tăng `--max-pages` lên `2` và tạo `$runId` mới trước
khi chạy lại. Không dùng full crawl làm lần kiểm tra đầu tiên.

## Crawl có detail

```powershell
$checkIn = (Get-Date).AddDays(21).ToString('yyyy-MM-dd')
$runId = 'detail_' + [guid]::NewGuid().ToString('N')
py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
  --airflow-try-number 1 --output-dir data/airflow `
  --destinations "Vung Tau" --date $checkIn `
  --max-pages 2 --workers 1 --enrich-details `
  --detail-concurrency 3 --total-detail-concurrency 3
```

`--detail-concurrency` áp dụng trong từng job; `--total-detail-concurrency`
giới hạn tổng detail browser workers trên mọi job. Khi không truyền CLI,
chúng lấy từ `AGODA_DETAIL_CONCURRENCY` và `AGODA_TOTAL_DETAIL_CONCURRENCY`.
Các field kích hoạt enrichment được mô tả trong [DATA_QUALITY.md](DATA_QUALITY.md).

## Benchmark detail concurrency

Giữ nguyên destination, ngày, số page, số outer worker và global cap. Mỗi
phép đo có run identity riêng:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString('yyyy-MM-dd')
foreach ($detailConcurrency in 2, 3) {
  $runId = 'compare_detail_' + $detailConcurrency + '_' + [guid]::NewGuid().ToString('N')
  py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
    --airflow-try-number 1 --output-dir data/airflow `
    --destinations "Vung Tau" --date $checkIn `
    --max-pages 2 --workers 1 --enrich-details `
    --detail-concurrency $detailConcurrency --total-detail-concurrency 3
}
```

So sánh `seconds`, `detail_sum`, coverage, số record publishable và pagination
duplicate. Giá và listing của Agoda có thể thay đổi giữa các lần chạy; thời
gian nhanh hơn cần được đánh giá cùng chất lượng dữ liệu.

## Đọc kết quả và debug

Output nằm trong
`data/airflow/dag_id=<id>/batch_id=<id>/attempt=<number>/`.
Mỗi attempt chứa JSONL và `run_manifest.json`; xem layout và lifecycle trong
[ingestion contract](DATABRICKS_INGESTION.md).

| Dấu hiệu trong log | Ý nghĩa |
| --- | --- |
| `pages=2/2 duplicate=0` | Đã thu đủ hai page yêu cầu và không phát hiện page lặp. |
| `page_records` | Unique records của từng page trước khi merge toàn run. |
| `records` | Records publishable sau khi lọc trường bắt buộc. |
| `timing` | `search_sum`, `listing_sum`, `detail_sum` giúp tìm bước tốn thời gian. |
| `VERIFY_COVERAGE_STATUS=success` | Không có record bị loại vì thiếu trường bắt buộc. |
| `VERIFY_OPTIONAL_COVERAGE_STATUS` | Coverage rating/review/star; `warning` không làm job fail. |
| `VERIFY_DISCARDED_RECORDS` | Số record không được ghi vào JSONL public. |

Khi thiếu field hoặc pagination bất thường, xem:

- `debug/<batch-id>/<destination>/<check-in>/`: diagnostics theo job.
- `debug/<batch-id>/summary/<check-in>/`: `missing_price_records.json`,
  `partial_missing_url_records.json`, `discarded_records.json`.

Coverage đạt yêu cầu vẫn cần được đối chiếu với số page và duplicate page.
Ngưỡng coverage và quy tắc loại record nằm trong [DATA_QUALITY.md](DATA_QUALITY.md).
`data/` và `debug/` là artifacts tạm; không dùng trực tiếp làm fixture hoặc commit.

## Kiểm chứng khi sửa code

```powershell
py -m pytest
py -m ruff check .
py -m mypy agoda_crawler
```

Với thay đổi live crawler, chạy smoke test giới hạn ở trên sau các kiểm tra
local. Quy trình thay đổi cấu hình, CLI và contract nằm trong
[AGENTS.md](../AGENTS.md).
