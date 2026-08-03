# Airflow Guidelines

## Scope

This directory orchestrates the crawler and the Databricks Job. Keep the DAG
thin: its responsibilities are scheduling, run identity, task dependencies,
and handing an immutable crawler attempt to downstream scripts. Crawler logic
belongs in `agoda_crawler/`; Databricks transformations belong in
`databricks/agoda_etl/`.

## Preserve The Pipeline Contract

The supported task order is:

```text
crawl_agoda -> verify_output -> upload_to_uc_volume -> trigger_databricks_job -> cleanup_local_output
```

- Do not change `dag_id`, schedule, timezone, retries, task order, or task
  names unless the user explicitly requests it.
- Do not replace the run-specific `manifest_path` hand-off with discovery by
  wildcard, latest file, or directory scan.
- `upload_to_uc_volume` must upload the verified attempt and write its receipt.
  `trigger_databricks_job` must derive the remote manifest path from that
  receipt and wait for the corresponding Databricks run to finish.
- Preserve the idempotency token behavior when triggering Databricks. Retrying
  a failed Airflow task must not create an unintended independent batch.
- Keep local attempt output immutable. Comparison runs require a new Airflow
  run identity or attempt number.

## Configuration And Security

- Runtime settings come from the root `.env`; never add credentials, tokens,
  passwords, cookies, or workspace URLs with secrets to source control or logs.
- Do not modify the Unity Catalog Volume path, Databricks Job ID, or production
  connection behavior without explicit confirmation.
- Keep cleanup downstream of a successful Databricks Job. Do not widen its
  filesystem deletion scope.

## Validation

- For DAG changes, update the focused tests under `tests/test_airflow_*.py`.
- Prefer source-level/unit tests for DAGs over requiring a local Airflow server.
- Before a live run, use a new manual DAG run and inspect the manifest,
  `upload_receipt.json`, and Databricks run result; do not clear/retry an old
  task solely to create a comparison run.
- Docker commands in `airflow/README.md` execute inside containers, where
  `python` is correct. Windows host commands should follow the root guidance
  and use `py`.
