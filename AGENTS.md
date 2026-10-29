# Repository Guidelines

## Project Overview

This repository is a script-first Python crawler for Agoda hotel search results
using Playwright. The crawler supports batch city/date jobs, parallel workers,
paginated listing collection, and optional hotel detail enrichment.

Keep `main.py` thin. Put behavior in the package modules by concern:
navigation, listing collection, extraction, enrichment, orchestration, and
utilities.

## Workflow And Skill Selection

Choose the workflow from the task's scope. Use the current session's skill
catalog and read the relevant `SKILL.md` before applying it; installed skills
and plugin availability can differ between machines and sessions.

| Task | Workflow |
| --- | --- |
| Clear, small fix, documentation edit, or routine configuration change | Make the smallest complete change and run the relevant checks. Use focused skills without creating a formal proposal solely for bookkeeping. |
| Unclear requirements or competing approaches | Use `superpowers:brainstorming`; use `openspec-explore` when exploring an OpenSpec change. Inspect existing code and context before asking questions. |
| New feature or substantial change across crawler, Airflow, or Databricks contracts | Use `openspec-propose` to record scope, specs, design when needed, and tasks. Present the artifacts for review; start `openspec-apply-change` on the user's subsequent implementation request. |
| Work on an existing OpenSpec change | Read its current artifacts and select the matching skill: `openspec-update-change`, `openspec-apply-change`, `openspec-sync-specs`, or `openspec-archive-change`. Sync and archive when requested. |
| Bug, failing test, or unexpected runtime behavior | Use `superpowers:systematic-debugging` and the relevant domain skill; establish the cause before changing code. |
| Implementation and completion checks | Use applicable Superpowers testing/review skills and `superpowers:verification-before-completion`. Match checks to the change and report actual results and remaining limits. |
| Review of agent workflow, repeated work, or conflicting instructions | Use Better Harness when explicitly requested and available. Follow its own invocation and evidence-scope requirements. |

- Apply `ponytail` to coding tasks: reuse existing helpers, keep changes focused,
  and preserve validation and error handling.
- Use `context-mode` for log analysis, large files, structured data, and test
  output. Return the findings needed for the task rather than raw output.
- Use `agoda-pipeline-review` for crawler and pipeline contract work. Read
  Airflow, Databricks, or dbt domain skills when the task involves those systems;
  select only the relevant skills from the catalog.
- For an OpenSpec change, keep its planning artifacts under `openspec/` as the
  single maintained spec and task list. Superpowers should use that existing
  plan; do not create a duplicate under `docs/superpowers/` or repeat already
  resolved design questions. Read runtime context from `openspec/config.yaml`.
- Announce the chosen workflow briefly when starting substantial work. Ask
  about material ambiguity; settle routine implementation details within the
  user's authorized scope.
- Use subagents only when the user requests them or an applicable skill
  explicitly calls for delegation. Keep routine edits in the current session.
- Keep skill implementation details in their own `SKILL.md`; this section
  defines repository routing and does not replace skill instructions.

## Project Structure

- `main.py`: CLI argument parsing and handoff to orchestration.
- `agoda_crawler/config.py`: `.env` and environment-backed runtime defaults.
- `agoda_crawler/orchestration.py`: job planning, worker execution, immutable attempt output, manifest lifecycle, JSONL writing, and run summaries.
- `agoda_crawler/jobs.py`: destination/date parsing and job matrix helpers.
- `agoda_crawler/crawler.py`: one crawl job lifecycle, from search through pagination and detail enrichment.
- `agoda_crawler/navigation/`: Agoda homepage/search flow, URL derivation, pagination navigation.
- `agoda_crawler/listing/`: listing DOM snapshots, scroll flow, record merge/dedupe, pagination state.
- `agoda_crawler/extraction/`: listing selectors and field parsers.
- `agoda_crawler/enrichment/`: hotel detail page enrichment and detail concurrency.
- `agoda_crawler/utils/`: logging, JSONL helpers, metrics, debug artifacts, page helpers.
- `tests/`: pytest tests.
- `data/`: transient JSONL crawl output.
- `debug/`: transient diagnostics for missing fields, listing issues, and pagination anomalies.

## Development Commands

Use PowerShell from the repository root.

- `py -m venv venv`: create local virtual environment on Windows.
- `.\venv\Scripts\Activate.ps1`: activate environment.
- `py -m pip install -r requirements-dev.txt`: install development dependencies.
- `py -m playwright install`: install browser binaries.
- `py -m pytest`: run tests.
- `py -B -m pytest -p no:cacheprovider`: run tests without pytest cache.
- `py -m ruff check .`: run lint checks.
- `py -m mypy agoda_crawler`: run the initial type-checking boundary.

Airflow supplies `dag.dag_id`, `run_id`, and `ti.try_number` to the crawler.
New DAG runs have their own run identity; retries use a separate attempt number.

For manual CLI runs, smoke tests, and benchmarks, use the commands in
[docs/RUNBOOK.md](docs/RUNBOOK.md). They select a future check-in date and a
fresh manual run ID. Keep runnable crawler examples there as the single source
of truth; every manual run must supply an Airflow-compatible identity.

## Local Runtime Profile

The local root `.env` currently uses headless mode with four destinations, five
pages, two outer workers, and total detail concurrency 3:

- `AGODA_DESTINATIONS=Vung Tau,Da Nang,Nha Trang,Ho Chi Minh`
- `AGODA_MAX_PAGES=5`
- `AGODA_HEADLESS=true`
- `AGODA_WORKERS=2`
- `AGODA_DETAIL_CONCURRENCY=3`
- `AGODA_TOTAL_DETAIL_CONCURRENCY=3`

Listing collection merges records during each scroll round. JSONL output is
still written after the job completes detail enrichment.
Network routing blocks non-essential resources per context; keep it configurable
because site resource-loading behavior can change over time.

## Run isolation and concurrency

Runtime output is scoped to
`<output-dir>/dag_id=<id>/batch_id=<id>/attempt=<number>/` and includes
`run_manifest.json`. Pagination diagnostics are under
`debug/<batch-id>/<destination>/<check-in>/`; do not reintroduce global
page-number-only debug filenames. `AGODA_DETAIL_CONCURRENCY` is per job, while
`AGODA_TOTAL_DETAIL_CONCURRENCY` caps all concurrently open detail browsers.
The ignored `.env` is runtime configuration; code fallbacks belong in
`agoda_crawler/config.py`.

## Coding Style

- Follow PEP 8, 4-space indentation, and type hints for public functions.
- Use `snake_case` for functions, variables, modules, and files.
- Use `UPPER_SNAKE_CASE` for constants.
- Keep functions small and single-purpose.
- Prefer existing local helpers over new abstractions.
- Preserve short operational log messages with useful context.
- Avoid adding business logic to `main.py`.

## Testing Guidance

- Add or update focused pytest coverage for parser, selector, listing, pagination, enrichment, and config changes.
- For Playwright-heavy behavior, isolate pure helpers where possible and use small fakes in tests.
- Run `py -m pytest` before handing off code changes.
- For live crawler validation, prefer a bounded smoke command before an all-pages run.

## Documentation And Change Workflow

- Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the module being
  changed. Use [docs/README.md](docs/README.md) to find the relevant runbook or
  contract. This file also contains the rules for Airflow and Databricks below.
- Keep selectors in `extraction/selectors.py`, pure parsers in
  `extraction/parsers.py`, and dedupe identity in `listing/records.py`.
  Pagination must verify the new listing state before merging records.
- Use `detail_concurrency` and the separate total concurrency cap; do not
  reintroduce `detail_workers` or equivalent configuration aliases without a
  clear deprecation plan.
- When changing configuration or CLI, update `main.py`, environment handling
  and fallbacks in `agoda_crawler/config.py`, parser/config tests in
  `tests/test_main.py`, and the relevant documentation together.
- When changing output, manifest, or batch identity, check `run_context.py`,
  `run_manifest.py`, `airflow/scripts/`, and the Databricks consumer against
  [docs/DATABRICKS_INGESTION.md](docs/DATABRICKS_INGESTION.md).
- For live crawler changes, check pages collected, duplicate pages,
  publishable records, required-field coverage, and timing in a bounded smoke
  run. See [docs/RUNBOOK.md](docs/RUNBOOK.md).
- Keep root `README.md` as the project entry point and root `AGENTS.md` as
  repository-wide instructions. Component setup stays in component READMEs;
  shared technical documentation stays in `docs/` without duplicate guides.

## Airflow Rules

These rules apply to `airflow/`.

- Keep the DAG thin: scheduling, run identity, dependencies, and handing an
  immutable crawler attempt to downstream scripts. Crawler logic belongs in
  `agoda_crawler/`; transformations belong in `databricks/agoda_etl/`.
- Preserve the task order:
  `crawl_agoda -> verify_output -> upload_to_uc_volume -> trigger_databricks_job -> cleanup_local_output`.
  Do not change `dag_id`, schedule, timezone, retries, task order, or task names
  unless explicitly requested.
- Upload the verified attempt and write `upload_receipt.json`. Derive the
  remote `manifest_path` from that receipt and wait for the corresponding
  Databricks run to finish. Never discover batches by wildcard, latest file,
  or directory scan.
- Preserve Databricks trigger idempotency tokens. A task retry must not create
  an unintended independent batch. For comparisons, use a new manual DAG run;
  do not clear/retry an old task solely to create a comparison run.
- Runtime settings come from the root `.env`. Do not modify the Unity Catalog
  Volume path, Databricks Job ID, or production connection behavior without
  explicit confirmation.
- Keep cleanup downstream of a successful Databricks Job. Do not widen its
  filesystem deletion scope.
- Update focused tests under `tests/test_airflow_*.py` for DAG changes. Prefer
  source-level/unit tests over requiring a running Airflow server.
- For live validation, inspect the manifest, upload receipt, and Databricks
  run result. Use `py` on the Windows host; `python` remains correct inside
  the Airflow containers. See [airflow/README.md](airflow/README.md).

## Databricks Rules

These rules apply to `databricks/`.

- Notebook wrappers only collect widget parameters and call `agoda_etl`.
  Put business and transformation logic in `databricks/agoda_etl/`.
- Preserve the layer order:
  `Unity Catalog Volume manifest -> Bronze -> Silver -> Gold`.
  Start from one explicit, complete `manifest_path`; never scan the Volume
  with wildcards or infer a latest JSONL file.
- Preserve Bronze and Silver idempotency by `record_id`. Gold rebuilds from
  the complete Silver history; do not restrict it to the newest batch unless
  explicitly asked to change the analytics contract.
- Keep batch metadata in the manifest. Public crawler JSONL contains business
  fields; ingestion applies Airflow/run metadata. The required-field and
  optional-coverage rules in Output And Debug Policy also apply here.
- Do not create, drop, rename, or alter Unity Catalog schemas/tables, change
  catalog names, or run workspace DDL unless explicitly requested. Do not
  weaken permission assumptions or embed credentials or production paths in
  source code.
- Preserve the three wrapper notebook names and their `project_root` and
  `manifest_path` parameters unless the user asks for a migration plan.
- Keep code importable after upload to a Workspace folder; avoid local-only
  path assumptions and do not commit `__pycache__` or `.pyc` files.
- Add focused tests for schema, record IDs, malformed manifest/JSONL handling,
  and idempotency when these contracts change. Keep pure transformations
  testable without a live workspace.
- For live validation, use a known complete manifest in a development
  workspace and verify Bronze, Silver, and all Gold tables before touching a
  production Job.
- Consult [databricks/README.md](databricks/README.md) and
  [docs/DATABRICKS_INGESTION.md](docs/DATABRICKS_INGESTION.md) before changing
  ingestion behavior; preserve the documented manifest contract.

## Output And Debug Policy

- Each `airflow_run_id` and `airflow_try_number` defines an immutable output
  attempt. Use a new identity when comparing runs.
- Treat `data/` and `debug/` as transient runtime artifacts.
- Do not commit credentials, cookies, personally identifiable scrape output, or large binary diagnostics.
- Debug files under `debug/<batch-id>/summary/<check-in>/` such as
  `missing_price_records.json`, `partial_missing_url_records.json`, and
  `discarded_records.json`, plus destination diagnostics under
  `debug/<batch-id>/<destination>/<check-in>/`, are for investigation, not
  stable fixtures unless explicitly curated.
- Public JSONL requires `hotel_name`, `hotel_url`, and `price_value`. Missing optional rating/review/star fields are retained; their coverage is warning-only when it does not exceed the configured threshold.

## Commit And PR Notes

- Use concise imperative commit subjects, for example `Improve listing scroll timing`.
- Keep commits scoped to one concern.
- PR descriptions should include purpose, behavior changes, verification
  commands, and sample output paths when relevant.
- Include screenshots only when UI/debug rendering behavior changed.
