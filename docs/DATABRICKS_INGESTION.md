# Databricks ingestion contract

Airflow is the only source of crawler batch identity. A crawler run writes its
files under this layout:

```text
data/airflow/dag_id=<encoded-dag-id>/
  batch_id=<encoded-dag-id-and-airflow-run-id>/
    attempt=<task-try-number>/
      run_manifest.json
      agoda_hotels_YYYY-MM-DD.jsonl
```

The manifest is the hand-off contract and the only source of Airflow batch
metadata. JSONL contains crawler business fields only. A Databricks loader must
read only the JSONL files declared by a manifest whose `status` is `complete`;
it must never discover files through a broad `*.jsonl` pattern.

## Databricks loader status

This repository uploads verified JSONL files and the manifest to a Unity
Catalog Volume. The source-format Databricks notebooks in `databricks/` now
implement the Bronze loader, ingestion ledger, Silver history transform, and
Gold aggregates. They receive one `manifest_path` parameter for each batch.

Before the daily Job is used, run `setup_uc_objects_wrapper` once. That setup
creates the schemas and Delta tables. Daily tasks do not execute DDL and fail
with a clear error if setup has not been completed.

## Orchestration responsibility

Create one Databricks Job/Workflow with dependent tasks:

```text
ingest_bronze_wrapper -> transform_silver_wrapper -> build_gold_wrapper
```

Each task receives the same `manifest_path` and a `project_root` that points to
the Workspace folder containing `agoda_etl`. Airflow remains responsible for
crawling, validating output and uploading to the Volume; after upload it should
trigger this one Databricks Job and wait for its terminal status. Airflow should
not invoke the Bronze, Silver and Gold notebooks separately.

The Airflow DAG triggers this Job after the Volume upload succeeds and waits for
its terminal status. It passes the exact remote `run_manifest.json` path from
the local upload receipt; it never discovers a batch through a Volume listing.

## Required control table

Create a Delta ingestion ledger with at least these columns:

| Column | Purpose |
| --- | --- |
| `batch_id` | Idempotency key for one Airflow DAG run. |
| `file_path` | JSONL file declared by the manifest. |
| `status` | `loading`, `loaded`, or `failed`. |
| `loaded_at` | Timestamp of the successful load. |
| `target_table` | Delta table that received the file. |

The unique technical identity is `(batch_id, file_path)`. Before loading a
file, the Databricks job checks the ledger. If that identity is already
`loaded`, it skips the file. After a successful Bronze write, it records
`loaded`. A failed attempt records `failed` and may be retried.

`airflow_run_id` is audit metadata, not a business de-duplication key. A new
Airflow run can legitimately crawl the same hotel and date again. The current
Silver table is history, so it retains every successful observation and exposes
`check_in_date` derived from the crawler's `check_in`. A future latest-state
table can deduplicate by `hotel_url` and `check_in_date`, ordered by
`crawled_at`.

## Loader sequence

1. Receive one expected `manifest_path` from the Databricks Job parameter.
2. Read `run_manifest.json`; stop unless its status is `complete`.
3. Read only the manifest's declared output paths.
4. Add Airflow provenance columns from the validated manifest.
5. Read JSONL lines permissively, preserve each original line in
   `raw_record_json`, remove duplicate exact-record IDs within the file, then
   write to Bronze. Business-format validation is performed in Silver.
6. Mark the ledger row as `loaded` only after the Bronze write succeeds.

## Airflow upload to a Unity Catalog Volume

After `verify_output`, the DAG uploads the verified batch to:

```text
/Volumes/agoda/raw/crawler/
  dag_id=<encoded-dag-id>/
    batch_id=<encoded-batch-id>/
      attempt=<crawler-try-number>/
        agoda_hotels_YYYY-MM-DD.jsonl
        run_manifest.json
```

The JSONL files are uploaded first and `run_manifest.json` is uploaded last.
Its presence with `status: complete` is therefore the ready signal for a
Databricks loader. The uploader writes `upload_receipt.json` only to the local
attempt directory; it is used to safely retain local backups for 14 days.

Configure these values in the ignored root `.env` file:

```dotenv
DATABRICKS_HOST=https://<workspace-url>
DATABRICKS_TOKEN=<personal-access-token>
DATABRICKS_UC_VOLUME_PATH=/Volumes/agoda/raw/crawler
DATABRICKS_JOB_ID=<existing-databricks-job-id>
DATABRICKS_JOB_TIMEOUT_SECONDS=3600
```

`DATABRICKS_TOKEN` is used only by the Airflow container and must never be
committed. A future production deployment can replace it with OAuth service
principal credentials without changing the batch layout or manifest contract.

The Databricks Job must define `manifest_path` as a job-level parameter. Airflow
overrides that parameter for each run, while `project_root` remains the Job's
static parameter.
