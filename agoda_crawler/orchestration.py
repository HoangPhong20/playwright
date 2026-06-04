"""CLI orchestration for batch Agoda crawls."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List

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
from agoda_crawler.utils.logging import log, log_prefix
from agoda_crawler.utils.run_output import (
    has_missing_price,
    is_publishable_record,
    print_verification_summary,
    project_output_record,
    summarize,
    write_crawl_results,
    write_latest_outputs,
)
from agoda_crawler.utils import append_jsonl, as_json


DEFAULT_DESTINATION = "Vung Tau"
DEFAULT_DESTINATIONS = "Vung Tau,Da Nang,Nha Trang"
DEFAULT_DATE_START = "2026-06-01"
DEFAULT_DATE_END = "2026-06-30"
DEFAULT_MAX_PAGES = 0
DEFAULT_WORKERS = 3
DEFAULT_DETAIL_WORKERS = 2
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
    "location_text",
    "image_url",
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
) -> List[CrawlJobResult]:
    results: List[CrawlJobResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        try:
            for job in jobs:
                with log_prefix(_job_log_prefix(job)):
                    log("Job started")
                    records = crawl_agoda_search_with_browser(
                        browser,
                        start_url=args.start_url or "",
                        max_pages=max(0, args.max_pages),
                        headless=args.headless,
                        use_homepage_flow=args.use_homepage_flow,
                        destination=job.destination,
                        check_in=job.check_in,
                        check_out=job.check_out,
                        adults=args.adults,
                        rooms=args.rooms,
                        children=args.children,
                        locale=args.locale,
                        enrich_details=args.enrich_details,
                        max_detail_pages=args.max_detail_pages,
                        detail_workers=max(1, args.detail_concurrency),
                        enrich_missing_only=args.enrich_missing_only,
                        detail_timeout=args.detail_timeout,
                        field_retry_timeout=max(0, args.field_retry_timeout),
                        field_retry_count=max(0, args.field_retry_count),
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
                    if args.print_records:
                        print(as_json(project_output_record(annotated)))
                    if write_output:
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
) -> List[CrawlJobResult]:
    if worker_count == 1:
        results = run_crawl_job_batch(jobs, args, write_output=False)
    else:
        results = []
        batches = chunk_jobs(jobs, worker_count)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(run_crawl_job_batch, batch, args, False)
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
    jobs = build_crawl_jobs(args, destinations, stays)
    max_worker_count = max(1, min(args.workers, len(destinations)))

    print(
        "Run: "
        f"destinations={len(destinations)} stays={len(stays)} jobs={len(jobs)} "
        f"pages={args.max_pages if args.max_pages > 0 else 'all'} headless={args.headless}"
    )
    print(
        "Concurrency: "
        f"workers={max_worker_count} detail={max(1, args.detail_concurrency)}"
    )
    print(
        "Loading: "
        f"scroll_rounds={args.max_scroll_rounds} stable={args.stable_rounds} "
        f"wait_ms={args.scroll_wait_ms} detail_timeout={args.detail_timeout} "
        f"field_retry={args.field_retry_timeout}msx{args.field_retry_count}"
    )
    print(
        "Output: "
        f"dir={args.output_dir} enrich={args.enrich_details} "
        f"missing_only={args.enrich_missing_only} detail_fields={args.detail_fields}"
    )
    print()

    coverage_failed = False
    for check_in, check_out in stays:
        stay_started_at = datetime.now()
        stay_jobs = jobs_for_stay(jobs, check_in)
        worker_count = max(1, min(args.workers, len(stay_jobs)))
        output_path = output_path_for_stay(args, check_in, len(stays))
        print(
            f"\nStay {check_in} -> {check_out}: "
            f"jobs={len(stay_jobs)} workers={worker_count} output={output_path}"
        )

        stay_results = run_crawl_jobs_for_stay(stay_jobs, args, worker_count)
        stay_records = [
            record
            for result in stay_results
            for record in result.records
        ]
        write_latest_outputs(stay_records)
        public_records = [record for record in stay_records if is_publishable_record(record)]

        print(f"\nStay {check_in} -> {check_out} complete")
        if len(public_records) != len(stay_records):
            print(
                "Filtered incomplete records: "
                f"{len(stay_records) - len(public_records)} debug-only, "
                f"{len(public_records)} publishable"
            )
        summarize(public_records)
        elapsed_seconds = int((datetime.now() - stay_started_at).total_seconds())
        print_verification_summary(public_records, elapsed_seconds)
        if has_missing_price(public_records):
            if should_fail_on_missing_price(args):
                coverage_failed = True
            else:
                print(
                    "Coverage warning: missing price records present, "
                    "but this run is partial/no-detail so the process will not fail."
                )
        print(f"Saved JSONL: {output_path}\n")

    if coverage_failed:
        raise SystemExit("Coverage failed: at least one hotel is missing price_value. See debug/missing_price_records.json")


def _job_log_prefix(job: CrawlJob) -> str:
    return f"{job.destination} {job.check_in}"


def should_fail_on_missing_price(args) -> bool:
    return bool(args.enrich_details and max(0, args.max_detail_pages) <= 0)
