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

No Databricks connection, credential, or upload code is stored in this
repository yet.
