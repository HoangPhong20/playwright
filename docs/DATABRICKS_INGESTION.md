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

The manifest is the hand-off contract. A Databricks loader must read only the
JSONL files declared by a manifest whose `status` is `complete`; it must never
discover files through a broad `*.jsonl` pattern.

## Databricks loader status

This repository currently uploads verified JSONL files and the manifest to a
Unity Catalog Volume. The Delta loader and ingestion ledger below are the
required next Databricks step; they are not executed by the Airflow DAG yet.

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
Airflow run can legitimately crawl the same hotel and date again. Any Silver
table should apply its own business key, such as `hotel_url`, `check_in`, and
`check_out`, with `crawled_at` determining the newest observation.

## Loader sequence

1. Select one expected `batch_id` and `attempt`.
2. Read `run_manifest.json`; stop unless its status is `complete`.
3. Read only the manifest's declared output paths.
4. Add the JSONL provenance columns already supplied by the crawler.
5. Write to Bronze and transactionally mark the ledger row as `loaded`.

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
```

`DATABRICKS_TOKEN` is used only by the Airflow container and must never be
committed. A future production deployment can replace it with OAuth service
principal credentials without changing the batch layout or manifest contract.
