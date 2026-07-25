"""CLI orchestration for batch Agoda crawls."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import subprocess
import threading
from pathlib import Path
from typing import Dict, List, Optional

from playwright.sync_api import sync_playwright

from agoda_crawler.crawler import crawl_agoda_search_with_browser
from agoda_crawler.jobs import (
    CrawlJob,
    CrawlJobResult,
    annotate_record,
    build_crawl_jobs,
    chunk_jobs,
    iter_stays,
    jobs_for_stay,
    ordered_results,
    output_path_for_stay,
    parse_date,
    parse_destinations,
)
from agoda_crawler.run_context import RunContext, run_context_from_args
from agoda_crawler.utils.debug_artifacts import debug_run_context
from agoda_crawler.utils.logging import log, log_prefix
from agoda_crawler.utils.run_output import (
    is_publishable_record,
    print_verification_summary,
    project_output_record,
    summarize,
    write_crawl_results,
    write_latest_outputs,
)
from agoda_crawler.utils import append_jsonl, as_json


DEFAULT_DESTINATION = "Vung Tau"
DEFAULT_DESTINATIONS = "Vung Tau,Da Nang,Nha Trang,Ho Chi Minh"
DEFAULT_DATE_START = "2026-06-01"
DEFAULT_DATE_END = "2026-06-30"
DEFAULT_MAX_PAGES = 5
DEFAULT_WORKERS = 3
DEFAULT_DETAIL_CONCURRENCY = 2
DEFAULT_TOTAL_DETAIL_CONCURRENCY = 3
DEFAULT_DETAIL_TIMEOUT = 30_000
DEFAULT_FIELD_RETRY_TIMEOUT = 1_500
DEFAULT_FIELD_RETRY_COUNT = 2
DEFAULT_MAX_SCROLL_ROUNDS = 80
DEFAULT_STABLE_ROUNDS = 3
DEFAULT_SCROLL_WAIT_MS = 1_000
DEFAULT_DETAIL_FIELDS = "price_value,rating_text,review_count_text"
ALLOWED_DETAIL_FIELDS = {
    "price_value",
    "rating_text",
    "review_count_text",
    "star_rating_text",
}


def parse_detail_fields(value: str) -> tuple[str, ...]:
    fields = tuple(part.strip() for part in value.split(",") if part.strip())
    invalid = [field for field in fields if field not in ALLOWED_DETAIL_FIELDS]
    if invalid:
        raise ValueError(f"Unsupported detail fields: {', '.join(invalid)}")
    return fields or ("price_value",)


def run_crawl_job_batch(
    jobs: List[CrawlJob],
    args,
    write_output: bool = True,
    run_context: Optional[RunContext] = None,
    detail_worker_semaphore: Optional[threading.BoundedSemaphore] = None,
) -> List[CrawlJobResult]:
    if run_context is None:
        raise ValueError("run_context is required")
    results: List[CrawlJobResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        try:
            for job in jobs:
                with log_prefix(_job_log_prefix(job)), debug_run_context(
                    run_context.path_batch_id,
                    job.destination,
                    job.check_in,
                ):
                    log("Job started")
                    records = crawl_agoda_search_with_browser(
                        browser,
                        max_pages=max(0, args.max_pages),
                        headless=args.headless,
                        destination=job.destination,
                        check_in=job.check_in,
                        check_out=job.check_out,
                        adults=args.adults,
                        rooms=args.rooms,
                        children=args.children,
                        locale=args.locale,
                        enrich_details=args.enrich_details,
                        max_detail_pages=args.max_detail_pages,
                        detail_concurrency=max(1, args.detail_concurrency),
                        enrich_missing_only=args.enrich_missing_only,
                        detail_timeout=args.detail_timeout,
                        field_retry_timeout=max(0, args.field_retry_timeout),
                        field_retry_count=max(0, args.field_retry_count),
                        detail_worker_semaphore=detail_worker_semaphore,
                        detail_fields=parse_detail_fields(args.detail_fields),
                        max_scroll_rounds=max(1, args.max_scroll_rounds),
                        stable_rounds=max(1, args.stable_rounds),
                        scroll_wait_ms=max(0, args.scroll_wait_ms),
                    )

                annotated_records: List[Dict] = []
                for item in records:
                    annotated = annotate_record(
                        item,
                        job.destination,
                        job.check_in,
                        job.check_out,
                    )
                    annotated.update(run_context.record_metadata())
                    if args.print_records:
                        print(as_json(project_output_record(annotated)))
                    if write_output and is_publishable_record(annotated):
                        append_jsonl(job.output_path, project_output_record(annotated))
                    annotated_records.append(annotated)
                results.append(CrawlJobResult(job=job, records=annotated_records))
        finally:
            browser.close()
    return results


def run_crawl_jobs_for_stay(
    jobs: List[CrawlJob],
    args,
    worker_count: int,
    run_context: RunContext,
    detail_worker_semaphore: threading.BoundedSemaphore,
) -> List[CrawlJobResult]:
    if worker_count == 1:
        results = run_crawl_job_batch(
            jobs,
            args,
            write_output=False,
            run_context=run_context,
            detail_worker_semaphore=detail_worker_semaphore,
        )
    else:
        results = []
        batches = chunk_jobs(jobs, worker_count)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(
                    run_crawl_job_batch,
                    batch,
                    args,
                    False,
                    run_context,
                    detail_worker_semaphore,
                )
                for batch in batches
            ]
            for future in as_completed(futures):
                results.extend(future.result())

    results = ordered_results(jobs, results)
    write_crawl_results(results)
    return results


def run_from_args(args) -> None:
    destinations = parse_destinations(args.destinations, args.destination)
    stays = iter_stays(args)
    run_context = run_context_from_args(args)
    run_output_dir = run_context.output_directory(args.output_dir)
    run_output_dir.mkdir(parents=True, exist_ok=True)
    jobs = build_crawl_jobs(args, destinations, stays, output_dir=run_output_dir)
    manifest_path = run_output_dir / "run_manifest.json"
    manifest = _new_run_manifest(run_context, args, destinations, stays)
    _write_run_manifest(manifest_path, manifest)
    detail_worker_semaphore = threading.BoundedSemaphore(
        max(1, args.total_detail_concurrency)
    )
    max_worker_count = max(1, min(args.workers, len(destinations)))

    print(
        "Run: "
        f"destinations={len(destinations)} stays={len(stays)} jobs={len(jobs)} "
        f"pages={args.max_pages if args.max_pages > 0 else 'all'} headless={args.headless}"
    )
    print(
        "Concurrency: "
        f"workers={max_worker_count} detail_per_job={max(1, args.detail_concurrency)} "
        f"detail_total={max(1, args.total_detail_concurrency)}"
    )
    print(
        "Loading: "
        f"scroll_rounds={args.max_scroll_rounds} stable={args.stable_rounds} "
        f"wait_ms={args.scroll_wait_ms} detail_timeout={args.detail_timeout} "
        f"field_retry={args.field_retry_timeout}msx{args.field_retry_count}"
    )
    print(
        "Output: "
        f"batch_id={run_context.batch_id} attempt={run_context.airflow_try_number} "
        f"dir={run_output_dir} enrich={args.enrich_details} "
        f"missing_only={args.enrich_missing_only} detail_fields={args.detail_fields}"
    )
    print()

    for check_in, check_out in stays:
        stay_started_at = datetime.now()
        stay_jobs = jobs_for_stay(jobs, check_in)
        worker_count = max(1, min(args.workers, len(stay_jobs)))
        output_path = stay_jobs[0].output_path
        print(
            f"\nStay {check_in} -> {check_out}: "
            f"jobs={len(stay_jobs)} workers={worker_count} output={output_path}"
        )

        stay_results = run_crawl_jobs_for_stay(
            stay_jobs,
            args,
            worker_count,
            run_context,
            detail_worker_semaphore,
        )
        stay_records = [
            record
            for result in stay_results
            for record in result.records
        ]
        write_latest_outputs(
            stay_records,
            debug_dir=Path("debug") / run_context.path_batch_id / "summary" / check_in,
        )
        public_records = [record for record in stay_records if is_publishable_record(record)]
        discarded_records = [record for record in stay_records if not is_publishable_record(record)]

        print(f"\nStay {check_in} -> {check_out} complete")
        if len(public_records) != len(stay_records):
            print(
                "Discarded incomplete records: "
                f"{len(stay_records) - len(public_records)} debug-only, "
                f"{len(public_records)} publishable"
            )
        summarize(public_records)
        elapsed_seconds = int((datetime.now() - stay_started_at).total_seconds())
        print_verification_summary(public_records, elapsed_seconds, discarded_records)
        print(f"Saved JSONL: {output_path}\n")
        manifest["stays"].append(
            {
                "check_in": check_in,
                "check_out": check_out,
                "output_path": str(output_path),
                "records": len(stay_records),
                "publishable_records": len(public_records),
                "discarded_records": len(discarded_records),
                "elapsed_seconds": elapsed_seconds,
            }
        )
        _write_run_manifest(manifest_path, manifest)

    manifest["status"] = "complete"
    manifest["finished_at"] = _utc_now()
    _write_run_manifest(manifest_path, manifest)


def _job_log_prefix(job: CrawlJob) -> str:
    return f"{job.destination} {job.check_in}"


def _new_run_manifest(
    run_context: RunContext,
    args,
    destinations: List[str],
    stays: List[tuple[str, str]],
) -> Dict:
    return {
        "run_id": run_context.airflow_run_id,
        "batch_id": run_context.batch_id,
        "airflow_dag_id": run_context.airflow_dag_id,
        "airflow_run_id": run_context.airflow_run_id,
        "airflow_try_number": run_context.airflow_try_number,
        "status": "running",
        "started_at": _utc_now(),
        "git_revision": _git_revision(),
        "config": vars(args),
        "destinations": destinations,
        "planned_stays": [
            {"check_in": check_in, "check_out": check_out}
            for check_in, check_out in stays
        ],
        "stays": [],
    }


def _write_run_manifest(path: Path, manifest: Dict) -> None:
    path.write_text(as_json(manifest), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_revision() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None
