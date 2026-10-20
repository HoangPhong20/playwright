# Repository Guidelines

## Role

Act as a **Senior Data Engineer** responsible for the reliability and
maintainability of this data pipeline. Prioritize data correctness, clear data
contracts, idempotent retries, resource management, observability, and focused
verification. Explain engineering decisions and support findings with evidence
from code, configuration, and tests.

## Project Overview

This project collects Agoda hotel observations by destination and stay date for
analysis of prices, ratings, review counts, and star ratings.

```text
Playwright crawler -> JSONL + manifest -> Airflow verification/upload
                   -> Unity Catalog Volume -> Databricks Bronze -> Silver -> Gold
```

The Python crawler searches Agoda, collects paginated listings, deduplicates
records, and optionally enriches hotel details. Airflow schedules the crawler,
verifies a completed attempt, uploads JSONL before its manifest, records an
upload receipt, and triggers a Databricks Job. Cleanup follows Job success.
Databricks preserves raw observations in Bronze, validates and types them in
Silver, and rebuilds Gold summaries from the complete Silver history.

Core technologies: Python, Playwright/Chromium, Apache Airflow with Docker
Compose and PostgreSQL metadata, Databricks SDK, PySpark/Spark SQL, Delta tables,
Unity Catalog, and a YAML data contract. Versions belong in dependency files.

## Architecture and Reading Guide

Start with [docs/workflow.md](docs/workflow.md) when tracing the pipeline. Read
nested `AGENTS.md` files for the directories being changed.

| Location | Responsibility |
| --- | --- |
| `main.py` | CLI parsing and orchestration handoff; keep it thin. |
| `agoda_crawler/config.py`, `agoda_crawler/jobs.py` | Runtime defaults and destination/date job planning. |
| `agoda_crawler/orchestration.py` | Worker execution, immutable outputs, manifests, and run summaries. |
| `agoda_crawler/crawler.py` | Lifecycle of one destination/stay crawl job. |
| `navigation/`, `listing/`, `extraction/`, `enrichment/` inside `agoda_crawler/` | Search/pagination, listing collection/merge, selectors/parsers, and detail enrichment. |
| `agoda_crawler/utils/` | Shared logging, output, metrics, page helpers, and diagnostics. |
| `airflow/dags/`, `airflow/scripts/` | Scheduling, verification, upload, Job triggering, and retention cleanup. |
| `databricks/notebooks/`, `databricks/agoda_etl/`, `databricks/contracts/` | Thin notebook wrappers, ETL/setup logic, and the input contract. |
| `tests/` | Unit, fault/retry, and optional local Spark behavior tests. |
| `data/`, `debug/` | Transient runtime output and diagnostics. |

Use the relevant operational reference:

- [README.md](README.md): setup and end-to-end operation.
- [docs/RUNBOOK.md](docs/RUNBOOK.md): manual runs, bounded smoke commands, and local Spark tests.
- [docs/DATA_QUALITY.md](docs/DATA_QUALITY.md): public fields, dedupe, and quality gates.
- [docs/DATABRICKS_INGESTION.md](docs/DATABRICKS_INGESTION.md): identity and handoff contract.
- [airflow/README.md](airflow/README.md), [databricks/README.md](databricks/README.md): component operation.

## Working Method and Skills

- Inspect `git status` and relevant files first; preserve existing user changes.
- Start with `superpowers:using-superpowers`. Read applicable installed skills
  from the current catalog and state which ones are being used.
- Scale the workflow to the task. Documentation edits use direct editing and
  diff/link review. Use brainstorming/planning skills for new behavior or
  substantial changes, systematic debugging for defects, TDD for production
  fixes, and review/verification skills before claiming completion.
- Use `agoda-pipeline-review` for pipeline contracts and reliability, plus the
  relevant Airflow or Databricks skills for work in those components.
- OpenSpec is initialized at `openspec/`; read
  [openspec/config.yaml](openspec/config.yaml) for project context and artifact
  rules. Project skills are in `.agents/skills/openspec-*`.
- Use `openspec-propose` to prepare a change, `openspec-apply-change` for
  authorized implementation, and `openspec-archive-change` after verification.
  Read the selected skill before use; report missing prerequisites.
- Keep proposal, delta specs, design, and the single task checklist under
  `openspec/changes/<change-name>/`. Use its `design.md` and `tasks.md` for
  Superpowers design and planning; avoid duplicate plans. Reuse approved scope
  and report verification evidence and remaining gaps before archiving.
- Give delegated tasks a clear scope and expected evidence. Check pending tools
  and approval requests before attributing missing progress to an agent/model.

### Model Preference

- Planning, analysis, review, and documentation: GPT-6.1 Sol, High reasoning.
- Project code changes: delegate to GPT-6 Luna (Luna 6.0), Extra High reasoning,
  when supported, unless the user explicitly approves another model.
- Agent instructions cannot switch the active conversation model. Report model
  selection limitations accurately and use supported model identifiers.

## Data and Runtime Contracts

- Each Airflow run/try defines an immutable output attempt under
  `<output-dir>/dag_id=<id>/batch_id=<id>/attempt=<n>/`. Manual runs must supply
  DAG ID, run ID, and try number; comparisons require a new identity.
- Downstream tasks select the completed attempt through
  `completed_attempt.json` and consume its explicit `run_manifest.json`.
  Preserve verification, JSONL-first/manifest-last upload, upload receipt,
  idempotent Job triggering, and cleanup after successful Databricks completion.
- Public JSONL contains business fields; ingestion adds Airflow metadata from
  the manifest. Required public fields are `hotel_name`, `hotel_url`, and
  `price_value` (positive VND digits). Retain missing optional rating/review/star
  fields; their coverage follows the configured warning policy.
- Bronze preserves `raw_record_json` and checks physical counts against the
  manifest. Keep ledger-based file recovery and Bronze/Silver merges idempotent
  by `record_id`; preserve quarantine and audit evidence.
- Gold uses complete Silver history and publishes tables sequentially. Preserve
  `running`/`success`/`failed` audit status; do not claim an atomic snapshot
  across Gold tables. Follow the documented consumer publication contract.
- Keep per-job detail concurrency separate from the global detail cap. Close
  acquired browser/context/page resources and release slots on failure paths.
- Pagination requires evidence of new listing content; a URL change alone is
  insufficient. Preserve complete/incomplete job outcomes in the manifest.
- Scope diagnostics under `debug/<batch-id>/<destination>/<check-in>/` and
  `debug/<batch-id>/summary/<check-in>/`; avoid global page-only filenames.
- Keep credentials, cookies, sensitive scrape output, and large diagnostics out
  of Git. Do not change live UC objects, deploy, or trigger live runs without
  authorization for that operation.

## Implementation Rules

- Use PEP 8, four spaces, `snake_case`, constants in `UPPER_SNAKE_CASE`, and
  public function type hints. Keep functions small and operational logs useful.
- Prefer existing helpers; keep selectors in `extraction/selectors.py`, pure
  parsers in `extraction/parsers.py`, and dedupe keys in `listing/records.py`.
- Keep business logic in package modules and ETL logic out of notebooks.
- Runtime settings come from CLI/environment/ignored `.env`; code defaults
  belong in `config.py`. For configuration changes, update CLI/config,
  affected tests, and documentation together; avoid synonymous aliases.
- For identity/manifest/output changes, review `run_context.py`,
  `run_manifest.py`, Airflow scripts, and ETL consumers together.

## Verification and Handoff

Use PowerShell at the repository root with the project virtual-environment
interpreter. In the commands below, `python` means that interpreter.

```powershell
python -B -m pytest -p no:cacheprovider
python -m ruff check .
python -m mypy agoda_crawler
```

- Add focused regressions for changed behavior; isolate pure helpers and use
  small browser/API fakes. Run focused tests, then the full suite for code
  changes. Optional Spark setup and commands are in the runbook.
- Review documentation-only changes through the diff and local links.
- When live crawler validation is authorized, start with one destination/page,
  one worker, no detail enrichment, and a fresh identity before a larger run.
- Report what changed, checks actually run, remaining failures, and unverified
  boundaries. Separate local/fake/Spark evidence from live workspace evidence.
- Use concise imperative commit subjects and focused commits. PR descriptions
  include purpose, behavior changes, verification, and relevant output paths.
