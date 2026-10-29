# Kiến trúc pipeline Agoda

Pipeline thu thập kết quả tìm khách sạn Agoda theo destination và ngày check-in,
điều phối bằng Airflow, rồi xử lý trên Databricks Unity Catalog.

## Luồng dữ liệu

```text
Airflow DAG
  -> crawler: destination x check-in date
     -> homepage/search -> listing
     -> scroll + snapshot + merge/dedupe -> verified pagination
     -> optional detail enrichment
     -> JSONL + run_manifest.json -> completed_attempt.json
  -> verify_output -> upload_to_uc_volume
  -> trigger_databricks_job(manifest_path)
     -> Bronze -> Silver history -> Gold aggregates
  -> cleanup_local_output
```

Airflow điều phối crawl, kiểm tra output, upload và chờ một Databricks Job.
Databricks Job điều phối ba notebook phụ thuộc nhau; mọi task dùng cùng một
`manifest_path`. Loader chỉ đọc file được manifest khai báo.

Crawler cũng chạy độc lập qua CLI. Chế độ này ghi output local với identity
Airflow được truyền rõ ràng; lệnh CLI không tự upload hay trigger Databricks.

## Ranh giới module

Các đường dẫn crawler dưới đây tương đối với `agoda_crawler/`.

| Khu vực | Trách nhiệm |
| --- | --- |
| [main.py](../main.py) | Parse CLI và handoff; giữ entry point mỏng. |
| [config.py](../agoda_crawler/config.py) | Đọc `.env`, environment và định nghĩa fallback. |
| [jobs.py](../agoda_crawler/jobs.py) | Parse destination/date và tạo job matrix. |
| [orchestration.py](../agoda_crawler/orchestration.py) | Chạy outer workers, ghi JSONL, manifest, summary và completion pointer. |
| [run_context.py](../agoda_crawler/run_context.py), [run_manifest.py](../agoda_crawler/run_manifest.py) | Identity, attempt path và manifest lifecycle. |
| [crawler.py](../agoda_crawler/crawler.py) | Vòng đời một job: search, listing, pagination, enrichment và timing. |
| [navigation/](../agoda_crawler/navigation/) | Homepage/search, URL và xác minh chuyển trang. |
| [listing/](../agoda_crawler/listing/) | Scroll, snapshot DOM, merge/dedupe và pagination state. |
| [extraction/](../agoda_crawler/extraction/) | Selectors và field parsers. |
| [enrichment/](../agoda_crawler/enrichment/) | Chọn record cần bổ sung và chạy detail workers. |
| [utils/](../agoda_crawler/utils/) | Logging, metrics, JSONL, debug artifacts và page helpers. |
| [airflow/](../airflow/) | DAG, xác minh output, upload, trigger Job và retention local. |
| [databricks/](../databricks/) | Setup Unity Catalog, Bronze ingestion, Silver history và Gold aggregates. |
| [tests/](../tests/) | Test crawler và contract giữa các thành phần. |

## Mô hình thực thi crawler

- Mỗi cặp destination × check-in tạo một job. `--workers` giới hạn số job
  chạy đồng thời; mỗi outer worker có Playwright browser riêng.
- Listing được merge giữa các vòng scroll và giữa các trang. Pagination chỉ
  chấp nhận trang mới khi có bằng chứng nội dung listing thay đổi.
- Detail enrichment dùng shared queue trong từng job.
  `--detail-concurrency` giới hạn detail workers của một job;
  `--total-detail-concurrency` giới hạn tổng detail browser workers trên các job.
- JSONL được ghi sau khi job hoàn tất detail enrichment. Mỗi attempt có output
  riêng và không được ghi đè khi chạy lại.
- Thứ tự ưu tiên cấu hình: CLI > environment > root `.env` > fallback trong
  `config.py`. Network routing chặn tài nguyên không thiết yếu và phải giữ
  khả năng cấu hình để thích ứng với thay đổi của website.

## Tài liệu liên quan

- [Runbook crawler](RUNBOOK.md): lệnh chạy, benchmark và debug.
- [Data quality](DATA_QUALITY.md): schema JSONL, dedupe và quality gates.
- [Ingestion contract](DATABRICKS_INGESTION.md): layout attempt, manifest,
  upload receipt và idempotency.
- [AGENTS.md](../AGENTS.md): quy tắc thay đổi và kiểm chứng code.
