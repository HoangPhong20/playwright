# Databricks Agoda ETL

Thư mục này được upload nguyên vẹn vào Databricks Workspace. `agoda_etl/` là
Python package chứa logic ETL; các file trong `notebooks/` chỉ nhận parameter
và gọi package.

## Upload và setup một lần

1. Upload thư mục `databricks/` vào một Workspace folder, ví dụ
   `/Workspace/Shared/agoda-etl`.
2. Chạy notebook `notebooks/setup_uc_objects_wrapper` một lần với parameter:

   ```text
   project_root=/Workspace/Shared/agoda-etl
   ```

   Notebook này tạo các schema `agoda.raw`, `agoda.silver`, `agoda.gold` và
   toàn bộ Delta tables cần thiết. Identity chạy setup cần quyền tạo schema và
   bảng. Không đưa `__pycache__/` hoặc file `.pyc` lên Workspace.

## Daily Databricks Job

Tạo một Job gồm ba Notebook tasks theo dependency:

```text
ingest_bronze_wrapper -> transform_silver_wrapper -> build_gold_wrapper
```

Chọn notebook dưới Workspace folder đã upload:

```text
notebooks/ingest_bronze_wrapper
notebooks/transform_silver_wrapper
notebooks/build_gold_wrapper
```

Mỗi task dùng cùng hai key-value parameters:

```text
project_root=/Workspace/Shared/agoda-etl
manifest_path=/Volumes/agoda/raw/crawler/dag_id=<id>/batch_id=<id>/attempt=<n>/run_manifest.json
```

`manifest_path` phải là manifest `complete` do Airflow upload cuối cùng. Pipeline
chỉ đọc JSONL được liệt kê trong manifest, không quét Volume bằng wildcard.

JSONL chỉ chứa dữ liệu crawl nghiệp vụ. `batch_id` và các metadata Airflow chỉ
có trong manifest; Bronze thêm chúng đúng một lần khi ghi vào Delta.

## Bảng Unity Catalog

- `agoda.raw.agoda_hotels_bronze`: dữ liệu JSONL nguồn, metadata Airflow và
  `record_id`.
- `agoda.raw.agoda_ingestion_ledger`: trạng thái từng JSONL; file đã `loaded`
  sẽ không được Bronze nạp lại.
- `agoda.silver.agoda_hotels_history`: history chuẩn hoá; `date` lấy từ
  `check_in`.
- `agoda.gold.*`: bốn bảng tổng hợp theo `date` và `destination`.

Bronze và Silver idempotent theo `record_id`. Gold đọc toàn bộ Silver history
và ghi lại bốn bảng tổng hợp, nên các ngày cũ và dữ liệu batch mới luôn nhất
quán.

## Quyền cần có

- Identity chạy setup: `USE CATALOG`, `USE SCHEMA`, `CREATE SCHEMA`,
  `CREATE TABLE`, `MODIFY` trên các schema `agoda.*`.
- Identity chạy Job hằng ngày: `READ_VOLUME` trên
  `/Volumes/agoda/raw/crawler`, `SELECT` Bronze/Silver và `MODIFY` các bảng
  Bronze, ledger, Silver, Gold.
