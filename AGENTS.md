# Repository Guidelines

## Project Overview

This repository is a script-first Python crawler for Agoda hotel search results
using Playwright. It supports batch city/date jobs, parallel crawl workers,
paginated listing collection, JSONL output, and optional detail enrichment.

Keep `main.py` thin. CLI parsing belongs there; crawler behavior belongs in the
package modules by concern: navigation, listing collection, extraction,
enrichment, orchestration, and utilities.

The crawler is direct-search-only. It no longer opens the Agoda homepage or
drives homepage UI controls. Destinations must resolve through `AGODA_CITY_IDS`.

## Current Architecture

- `main.py`: CLI argument parsing and handoff to orchestration.
- `agoda_crawler/config.py`: `.env` and environment-backed runtime defaults.
- `agoda_crawler/orchestration.py`: job planning, worker execution, JSONL writing, run summaries.
- `agoda_crawler/jobs.py`: destination/date parsing and job matrix helpers.
- `agoda_crawler/crawler.py`: one crawl job lifecycle from direct search through pagination and detail enrichment.
- `agoda_crawler/navigation/`: direct Agoda search URL construction, result validation, and pagination navigation.
- `agoda_crawler/listing/`: listing DOM snapshots, scroll flow, record merge/dedupe, pagination state.
- `agoda_crawler/extraction/`: selectors, text parsers, card extraction, detail field extraction.
- `agoda_crawler/enrichment/`: hotel detail page enrichment and detail concurrency.
- `agoda_crawler/utils/`: logging, JSONL helpers, metrics, debug artifacts, page helpers.
- `tests/`: pytest coverage.
- `data/`: transient JSONL crawl output.
- `debug/`: transient diagnostics and runtime artifacts.

## Runtime Defaults / Important Config

The checked-in `.env` is tuned for direct search, strong listing coverage, and
bounded detail enrichment.

Important defaults:

- `AGODA_DESTINATIONS=Vung Tau,Da Nang,Nha Trang`
- `AGODA_CITY_IDS=Vung Tau:17190,Da Nang:16440,Nha Trang:2679,...`
- `AGODA_MAX_PAGES=10` means crawl at most 10 result pages per city/date job.
- `AGODA_HEADLESS=true`
- `AGODA_WORKERS=3`
- `AGODA_DETAIL_CONCURRENCY=2`
- `AGODA_ENRICH_DETAILS=true`
- `AGODA_DETAIL_FIELDS=price_value,rating_text`
- `AGODA_OUTPUT_DIR=data/raw`
- `AGODA_MAX_SCROLL_ROUNDS=60`
- `AGODA_STABLE_ROUNDS=2`
- `AGODA_LISTING_FAST_WAIT_MS=200`
- `AGODA_LISTING_STALL_WAIT_MS=600`
- `AGODA_LISTING_FULL_SNAPSHOT_INTERVAL=15`
- `AGODA_MAX_LISTING_PAGE_SECONDS=110`

When adding a new city, add its Agoda city id to `AGODA_CITY_IDS`. Do not
reintroduce homepage search as a fallback.

Public JSONL fields are:

- `hotel_name`
- `hotel_url`
- `price_value`
- `rating_text`
- `review_count_text`
- `image_url`
- `crawled_at`
- `destination`
- `check_in`
- `check_out`
- `crawl_status`
- `error_reason`
- `run_id`

Critical fields are `hotel_name`, `hotel_url`, `price_value`, and
`rating_text`. Optional fields should keep strong coverage:
`review_count_text` and `image_url`.
`crawl_status` is `success` for records with all critical fields, `partial`
when useful fields exist but critical fields are missing, and `failed` for
severe item/page failures. `error_reason` explains partial/failed records.
Default raw output path is
`data/raw/source=agoda/check_in=<check_in>/run_id=<run_id>/hotels.jsonl`.
Default debug output path is
`data/debug/source=agoda/check_in=<check_in>/run_id=<run_id>/`.

## Development Commands

Use PowerShell from the repository root.

- `python -m venv venv`: create local virtual environment.
- `.\venv\Scripts\Activate.ps1`: activate environment.
- `python -m pip install -r requirements.txt`: install dependencies.
- `playwright install`: install browser binaries.
- `python -m pytest`: run tests.
- `python -B -m pytest -p no:cacheprovider`: run tests without pytest cache.

Runtime examples:

```powershell
python main.py --date-start 2026-06-10 --date-end 2026-06-10
```

```powershell
python main.py --destinations "Da Nang" `
  --date-start 2026-06-10 --date-end 2026-06-10 `
  --max-pages 1 --workers 1 --no-enrich-details `
  --output-dir data/raw/smoke_da_nang
```

Use unique `--output-dir` values when comparing runs.

## Coding Style

- Follow PEP 8, 4-space indentation, and type hints for public functions.
- Use `snake_case` for functions, variables, modules, and files.
- Use `UPPER_SNAKE_CASE` for constants.
- Keep functions small and single-purpose.
- Prefer existing local helpers over new abstractions.
- Preserve concise operational logs with useful job/page context.
- Use `rg` for code search.
- Do not add business logic to `main.py`.

## Testing Guidance

- Run `python -m pytest` after code changes.
- Add focused pytest coverage for parser, config, listing, pagination,
  navigation, enrichment, and output behavior changes.
- For Playwright-heavy behavior, isolate pure helpers where possible and use
  small fake page/locator objects in tests.
- For live validation, run a bounded smoke crawl before any all-pages run.
- Keep tests aligned with the current direct-search-only contract.

## Crawler Behavior Rules

- Search must use direct Agoda search URLs built from `AGODA_CITY_IDS`.
- Unknown destinations should fail clearly until their city id is configured.
- Listing collection should prioritize record count and critical field coverage.
- Detail enrichment should focus on `price_value` and `rating_text`.
- `review_count_text` and `image_url` are useful optional fields and should not
  be casually degraded.
- JSONL output should include only public fields and job metadata.
- Partial records may be published to raw JSONL with `crawl_status=partial`
  and `error_reason`; debug-only records should remain diagnostic artifacts.

## Output & Debug Policy

- `data/` is runtime output. Treat it as transient.
- `debug/` is runtime diagnostics. Treat it as transient.
- Do not commit credentials, cookies, personally identifiable scrape output, or
  large generated diagnostics.
- Output JSONL is append-oriented by default; use isolated output directories
  for comparisons.
- Debug files are investigation aids, not stable fixtures unless explicitly
  curated.

## Performance Notes

- Listing is the primary bottleneck. Do not reduce runtime by blindly cutting
  scroll rounds if it loses records.
- Prefer adaptive wait, lighter snapshots, better stop criteria, and direct URL
  search before reducing coverage.
- Detail time should remain small because detail fields are limited to
  `price_value` and `rating_text`.
- Measure changes with a small smoke crawl such as one city, one page, and
  `--no-enrich-details`.
- Compare both timing and coverage. A faster run that loses critical fields is
  not an improvement.

## What Not To Reintroduce

- Do not reintroduce Agoda homepage UI flow.
- Do not reintroduce `star_rating_text`.
- Do not reintroduce `AGODA_DETAIL_WORKERS`; use `AGODA_DETAIL_CONCURRENCY`.
- Do not add duplicate config aliases for the same behavior.
- Do not add `--nights` or other removed CLI aliases without a clear migration
  reason and tests.
- Do not restore city landing URL derivation as an automatic fallback.
