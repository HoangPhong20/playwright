# Databricks ETL Guidelines

## Scope

This directory contains the Databricks side of the Agoda pipeline. Notebook
wrappers only collect widget parameters and call the `agoda_etl` package; put
business and transformation logic in that package, not in notebooks.

The supported layer order is:

```text
Unity Catalog Volume manifest -> Bronze -> Silver -> Gold
```

## Preserve The Data Contract

- A run starts from one explicit, complete `manifest_path`. Do not scan the
  Unity Catalog Volume with wildcards or infer a "latest" JSONL file.
- Bronze and Silver are idempotent by `record_id`; preserve this property when
  changing merge keys, schemas, or ingestion logic.
- Gold is rebuilt from the complete Silver history. Do not make it depend only
  on the newest batch unless explicitly asked to change the analytics contract.
- Keep batch metadata in the manifest contract. Public crawler JSONL contains
  business fields, while Airflow/run metadata is applied by the ingestion flow.
- Required public record fields are `hotel_name`, `hotel_url`, and
  `price_value`. Treat optional-field coverage as warning-only according to the
  documented configuration unless the user changes that policy.

## Change Safety

- Do not create, drop, rename, or alter Unity Catalog schemas/tables, change
  catalog names, or run DDL against a workspace unless explicitly requested.
- Do not weaken permission assumptions or embed Databricks tokens, hostnames
  containing credentials, or production paths in source code.
- Preserve the three wrapper notebook names and their `project_root` and
  `manifest_path` parameters unless the user asks for a migration plan.
- Keep code importable after upload to a Databricks Workspace folder; avoid
  local-only path assumptions and do not commit `__pycache__` or `.pyc` files.

## Validation

- Add focused tests for schema, record IDs, malformed manifest/JSONL handling,
  and idempotency whenever these contracts change.
- Keep pure transformation logic testable without a live Databricks workspace.
- For a live validation, use a known complete manifest in a development
  workspace and verify Bronze, Silver, and all Gold tables before touching a
  production Job.
- Consult `databricks/README.md` and `docs/DATABRICKS_INGESTION.md` before
  changing ingestion behavior; the documented manifest contract is authoritative.
