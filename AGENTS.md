# Repository Guidelines

## Project Overview

This repository is a script-first Python crawler for Agoda hotel search results
using Playwright. The crawler supports batch city/date jobs, parallel workers,
paginated listing collection, and optional hotel detail enrichment.

Keep `main.py` thin. Put behavior in the package modules by concern:
navigation, listing collection, extraction, enrichment, orchestration, and
utilities.

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

- `python -m venv venv`: create local virtual environment.
- `.\venv\Scripts\Activate.ps1`: activate environment.
- `python -m pip install -r requirements-dev.txt`: install development dependencies.
- `playwright install`: install browser binaries.
- `python -m pytest`: run tests.
- `python -B -m pytest -p no:cacheprovider`: run tests without pytest cache.

Manual runtime examples must provide an Airflow-compatible identity:

Use the runtime defaults with an explicit manual batch identity:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id manual_001 `
  --airflow-try-number 1 --date 2026-06-10
```

Fast smoke test:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id smoke_001 `
  --airflow-try-number 1 --destinations "Vung Tau" `
  --date 2026-06-10 `
  --max-pages 1 --workers 1 --no-enrich-details
```

Isolate output for comparison:

```powershell
python main.py --airflow-dag-id adhoc --airflow-run-id comparison_001 `
  --airflow-try-number 1 --date 2026-06-10 `
  --output-dir data/airflow
```

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
- Run `python -m pytest` before handing off code changes.
- For live crawler validation, prefer a bounded smoke command before an all-pages run.

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
