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
- `agoda_crawler/orchestration.py`: job planning, worker execution, JSONL writing, run summaries.
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
- `python -m pip install -r requirements.txt`: install dependencies.
- `playwright install`: install browser binaries.
- `python -m pytest`: run tests.
- `python -B -m pytest -p no:cacheprovider`: run tests without pytest cache.

Runtime examples:

Use the runtime defaults for 3 cities, all pages, full detail:

```powershell
python main.py --date-start 2026-06-10 --date-end 2026-06-10
```

Fast smoke test:

```powershell
python main.py --destinations "Vung Tau" `
  --date-start 2026-06-10 --date-end 2026-06-10 `
  --max-pages 1 --workers 1 --no-enrich-details
```

Isolate output for comparison:

```powershell
python main.py --date-start 2026-06-10 --date-end 2026-06-10 `
  --output-dir data/raw/run_2026_06_10
```

## Current Runtime Defaults

The checked-in `.env` uses headless mode with 2 outer workers and detail concurrency 3:

- `AGODA_DESTINATIONS=Vung Tau,Da Nang,Nha Trang`
- `AGODA_MAX_PAGES=0`
- `AGODA_HEADLESS=true`
- `AGODA_ENRICH_DETAILS=true`
- `AGODA_MAX_DETAIL_PAGES=0`
- `AGODA_WORKERS=2`
- `AGODA_DETAIL_CONCURRENCY=3`
- `AGODA_MIN_OPTIONAL_COVERAGE=90`
- `AGODA_OUTPUT_DIR=data/raw`
- `AGODA_BLOCK_RESOURCE_TYPES=image,font,media`
- `AGODA_BLOCK_URL_KEYWORDS=googletagmanager,google-analytics,doubleclick,facebook,hotjar,clarity,taboola`
- `AGODA_LISTING_FULL_SNAPSHOT_INTERVAL=5`

Listing collection merges records during each scroll round. JSONL output is
still written after the job completes detail enrichment.
Network routing blocks non-essential resources per context; keep it configurable
because site resource-loading behavior can change over time.

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

- Output JSONL is append-only by default. Use a unique `--output-dir` when comparing runs.
- Treat `data/` and `debug/` as transient runtime artifacts.
- Do not commit credentials, cookies, personally identifiable scrape output, or large binary diagnostics.
- Debug files such as `debug/missing_price_records.json`,
  `debug/partial_missing_url_records.json`, `debug/discarded_records.json`, `debug/pagination_errors/`, and
  `debug/listing_errors/` are for investigation, not stable fixtures unless
  explicitly curated.
- Public JSONL requires `hotel_name`, `hotel_url`, and `price_value`. Missing optional rating/review/star fields are retained; their coverage is warning-only when it does not exceed the configured threshold.

## Commit And PR Notes

- Use concise imperative commit subjects, for example `Improve listing scroll timing`.
- Keep commits scoped to one concern.
- PR descriptions should include purpose, behavior changes, verification
  commands, and sample output paths when relevant.
- Include screenshots only when UI/debug rendering behavior changed.
