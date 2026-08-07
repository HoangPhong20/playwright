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

## Data contract and quality controls

`contracts/agoda_hotel.yaml` is the versioned input contract for crawler JSONL.
Its current version is `1.1.0` and declares `validation_layer: silver`.

Bronze reads JSONL permissively. It accepts unknown fields, missing fields, and
source scalar-type changes, preserving every valid JSON object verbatim in
`raw_record_json`. Only malformed JSON lines are written to
`agoda.raw.agoda_hotel_quarantine` at this boundary, with
`quarantine_layer = bronze`. Before ingesting each JSONL file, Bronze verifies
that its physical line count exactly matches the file's `publishable_records`
value in the manifest.

Silver enforces the YAML contract: required fields, URL, positive price,
timestamps, check-in/check-out dates, rating, review count, star rating, and
the cross-field check-out-after-check-in rule. Invalid rows remain in Bronze and
are written to quarantine with `quarantine_layer = silver`; valid rows continue
to Silver. Silver fails after quarantine only when invalid records exceed 10% of
input or 200 records. `agoda.raw.agoda_pipeline_audit` records Bronze, Silver,
and Gold counts and terminal status for every batch.

Malformed non-blank values for the optional `rating_text`, `review_count_text`,
and `star_rating_text` fields are normalized to zero before Silver validation;
missing optional values remain null.

Install `PyYAML==6.0.2` on the Databricks cluster or attach it as a job library
before running the updated notebooks.

JSONL chỉ chứa dữ liệu crawl nghiệp vụ. `batch_id` và các metadata Airflow chỉ
có trong manifest; Bronze thêm chúng đúng một lần khi ghi vào Delta.

## Bảng Unity Catalog

- `agoda.raw.agoda_hotels_bronze`: dữ liệu JSONL nguồn, metadata Airflow và
  `record_id`.
- `agoda.raw.agoda_ingestion_ledger`: trạng thái từng JSONL; file đã `loaded`
  sẽ không được Bronze nạp lại.
- `agoda.silver.agoda_hotels_history`: history chuẩn hoá; `check_in_date` lấy từ
  `check_in`.
- `agoda.gold.*`: bốn bảng tổng hợp theo `check_in_date` và `destination`.

### Migration for existing tables

After uploading this version, run `notebooks/setup_uc_objects_wrapper` once.
It renames the existing Silver and Gold `date` columns to `check_in_date` when
needed, adds `raw_record_json` to the Bronze table, and adds
`quarantine_layer` to the quarantine table. The next Gold task rebuilds each
summary table with the new schema. For legacy Delta tables, setup automatically
enables name-based column mapping before the rename.

Older Silver tables can also retain a `record_hash` column from a previous
schema. Drop it before the next daily Job because the current pipeline uses
`record_id` as the idempotency key:

```sql
ALTER TABLE agoda.silver.agoda_hotels_history DROP COLUMN record_hash;
```

Bronze và Silver idempotent theo `record_id`. Gold đọc toàn bộ Silver history
và ghi lại bốn bảng tổng hợp, nên các ngày cũ và dữ liệu batch mới luôn nhất
quán.

## Quyền cần có

- Identity chạy setup: `USE CATALOG`, `USE SCHEMA`, `CREATE SCHEMA`,
  `CREATE TABLE`, `MODIFY` trên các schema `agoda.*`.
- Identity chạy Job hằng ngày: `READ_VOLUME` trên
  `/Volumes/agoda/raw/crawler`, `SELECT` Bronze/Silver và `MODIFY` các bảng
  Bronze, ledger, Silver, Gold.
