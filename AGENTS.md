# Repository Guidelines

## Project Overview

This repository is a script-first Python crawler for Agoda hotel search results
using Playwright. The crawler supports batch city/date jobs, parallel workers,
paginated listing collection, and optional hotel detail enrichment.

Keep `main.py` thin. Put behavior in the package modules by concern:
navigation, listing collection, extraction, enrichment, orchestration, and
utilities.

## Agent Skills Workflow

Use OpenSpec to record requirements and change plans, and Superpowers to guide
design, debugging, implementation, and review. Follow system and developer
instructions first, then the user's instructions and these repository rules,
then the applicable skill instructions.

### Skill discovery and scope

- Start with `superpowers:using-superpowers`. Read each applicable `SKILL.md`
  before acting; announce the skills being used and their purpose.
- Discover skills from the current session's catalog and configured skill
  directories. Use the installed instructions rather than remembered commands
  or machine-specific plugin cache paths.
- Inspect `git status` and the relevant files before editing. Preserve existing
  user changes and keep the work within the requested scope.
- Check that this project has an initialized OpenSpec root before creating
  change artifacts. A globally installed CLI does not initialize this repo.
  If a required skill or project setup is missing, report the missing
  prerequisite and follow the skill's fallback or setup guidance.
- Scale the workflow to the task. Documentation-only edits use direct editing
  and diff review. For product changes, follow the applicable design, planning,
  implementation, and verification skills.

### Choosing the workflow

| Task | Required workflow |
| --- | --- |
| Unclear goal or competing approaches | Use `openspec-explore` to investigate and `superpowers:brainstorming` when designing new behavior. |
| Feature or behavior change | Use `superpowers:brainstorming` for the appropriate design path; use `openspec-propose` when recording a change proposal. |
| Architectural change or implementation plan | Use `superpowers:writing-plans` after the required design review. Record executable tasks in the OpenSpec change when it owns the work. |
| Implementing an OpenSpec change | Use `openspec-apply-change` to track task completion and the applicable Superpowers execution skill to implement the plan. |
| Bug, regression, or failing test | Use `superpowers:systematic-debugging` before proposing a fix; establish the cause and a reproducible failure. |
| Production code change | Use `superpowers:test-driven-development`: observe the relevant test fail, make the smallest change, then verify it passes. |
| Reviewing implementation | Use `superpowers:requesting-code-review`; use `superpowers:receiving-code-review` before acting on review feedback. |
| Completion or success claim | Use `superpowers:verification-before-completion` and report the commands actually run and their results. |

Load domain skills when the task calls for them: `agoda-pipeline-review` for
crawler and pipeline issues, the appropriate Airflow skills for DAG work, and
the appropriate Databricks skills for ingestion or platform work.

### Coordinating OpenSpec and Superpowers

- For an OpenSpec change, keep the requirements, design, and task checklist
  under `openspec/changes/<change-name>/`. Read existing artifacts and progress
  before continuing work.
- Use the change's `design.md` and `tasks.md` as the project-specific locations
  for Superpowers design and plan artifacts. Preserve the structure and detail
  required by those skills; link supporting documents when needed.
- Maintain one authoritative task checklist. Update it as work completes and
  keep any execution ledger linked to that plan. Avoid independent copies in
  `docs/superpowers/` that can drift from the OpenSpec change.
- Follow the selected skills' review and approval gates. Reuse an existing
  approval for the same artifact and scope; raise material scope changes with
  the user before implementing them.
- Choose inline execution or subagent execution according to the selected
  skill, the user's instructions, and available tools. Preserve existing work
  when an execution skill requires an isolated workspace.
- If `openspec-verify-change` is available, use it to check implementation
  against the change artifacts. It complements the project's runtime checks.
  Archive through `openspec-archive-change` after verification and the required
  workflow approvals.
- Include changed behavior, verification evidence, and remaining gaps in the
  handoff. For documentation-only edits, report the diff review; code changes
  must also follow the Testing Guidance below.

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

Manual runtime examples must provide an Airflow-compatible identity:

Use the runtime defaults with an explicit manual batch identity:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString("yyyy-MM-dd")
$runId = "manual_$(Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')"
py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
  --airflow-try-number 1 --date $checkIn
```

Fast smoke test:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString("yyyy-MM-dd")
$runId = "manual_$(Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')"
py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
  --airflow-try-number 1 --destinations "Vung Tau" `
  --date $checkIn `
  --max-pages 1 --workers 1 --no-enrich-details
```

Isolate output for comparison:

```powershell
$checkIn = (Get-Date).AddDays(21).ToString("yyyy-MM-dd")
$runId = "manual_$(Get-Date -Format 'yyyyMMdd_HHmmss_fffffff')"
py main.py --airflow-dag-id adhoc --airflow-run-id $runId `
  --airflow-try-number 1 --date $checkIn `
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
- Run `py -m pytest` before handing off code changes.
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
