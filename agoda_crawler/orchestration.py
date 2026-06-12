"""CLI orchestration for batch Agoda crawls."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from queue import Empty, Queue
from typing import Dict, List

from playwright.sync_api import sync_playwright

from agoda_crawler.crawler import crawl_agoda_search_with_browser
from agoda_crawler.jobs import (
    CrawlJob,
    CrawlJobResult,
    annotate_record,
    build_crawl_jobs,
    debug_output_path_for_stay,
    ensure_run_id,
    iter_stays,
    jobs_for_stay,
    ordered_results,
    output_path_for_stay,
    parse_date,
    parse_destinations,
)
from agoda_crawler.utils.debug_artifacts import debug_output_context
from agoda_crawler.utils.logging import log, log_prefix
from agoda_crawler.utils.run_output import (
    CrawlResultWriter,
    has_missing_price,
    is_incremental_publishable_record,
    is_output_record,
    print_verification_summary,
    project_output_record,
    summarize,
    write_crawl_result,
    write_latest_outputs,
)
from agoda_crawler.utils import as_json


DEFAULT_DESTINATION = "Vung Tau"
DEFAULT_DESTINATIONS = "Vung Tau,Da Nang,Nha Trang"
DEFAULT_DATE_START = "2026-06-01"
DEFAULT_DATE_END = "2026-06-30"
DEFAULT_MAX_PAGES = 10
DEFAULT_WORKERS = 3
DEFAULT_DETAIL_CONCURRENCY = 2
DEFAULT_DETAIL_TIMEOUT = 30_000
DEFAULT_FIELD_RETRY_TIMEOUT = 1_500
DEFAULT_FIELD_RETRY_COUNT = 2
DEFAULT_MAX_SCROLL_ROUNDS = 80
DEFAULT_STABLE_ROUNDS = 3
DEFAULT_SCROLL_WAIT_MS = 1_000
DEFAULT_DETAIL_FIELDS = "price_value,rating_text"
ALLOWED_DETAIL_FIELDS = {
    "price_value",
    "rating_text",
    "review_count_text",
    "image_url",
}


def parse_detail_fields(value: str) -> tuple[str, ...]:
    fields = tuple(part.strip() for part in value.split(",") if part.strip())
    invalid = [field for field in fields if field not in ALLOWED_DETAIL_FIELDS]
    if invalid:
        raise ValueError(f"Unsupported detail fields: {', '.join(invalid)}")
    return fields or ("price_value",)


def actual_worker_count(requested_workers: int, job_count: int) -> int:
    if job_count <= 0:
        return 0
    return max(1, min(max(1, requested_workers), job_count))


def normalized_detail_concurrency(args) -> int:
    return max(1, args.detail_concurrency)


def estimated_detail_pressure(worker_count: int, detail_concurrency: int, enrich_details: bool) -> int:
    if not enrich_details:
        return 0
    return max(0, worker_count) * max(1, detail_concurrency)


def run_crawl_job_with_browser(
    browser,
    job: CrawlJob,
    args,
    record_writer: CrawlResultWriter | None = None,
) -> CrawlJobResult:
    def publish_listing_records(records: List[Dict]) -> None:
        if record_writer is None:
            return
        record_writer.write_records(
            annotate_record(
                item,
                job.destination,
                job.check_in,
                job.check_out,
                run_id=ensure_run_id(args),
            )
            for item in records
            if is_incremental_publishable_record(item)
        )

    with log_prefix(_job_log_prefix(job)), debug_output_context(
        debug_output_path_for_stay(args, job.check_in)
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
            detail_workers=normalized_detail_concurrency(args),
            enrich_missing_only=args.enrich_missing_only,
            detail_timeout=args.detail_timeout,
            field_retry_timeout=max(0, args.field_retry_timeout),
            field_retry_count=max(0, args.field_retry_count),
            detail_fields=parse_detail_fields(args.detail_fields),
            max_scroll_rounds=max(1, args.max_scroll_rounds),
            stable_rounds=max(1, args.stable_rounds),
            scroll_wait_ms=max(0, args.scroll_wait_ms),
            on_listing_records=publish_listing_records if record_writer else None,
        )

    annotated_records: List[Dict] = []
    for item in records:
        annotated = annotate_record(
            item,
            job.destination,
            job.check_in,
            job.check_out,
            run_id=ensure_run_id(args),
        )
        if args.print_records and is_output_record(annotated):
            print(as_json(project_output_record(annotated)))
        annotated_records.append(annotated)
    public_records = [record for record in annotated_records if is_output_record(record)]
    return CrawlJobResult(
        job=job,
        records=public_records,
        debug_records=annotated_records,
    )


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
                record_writer = CrawlResultWriter(job.output_path) if write_output else None
                result = run_crawl_job_with_browser(browser, job, args, record_writer)
                if write_output:
                    write_crawl_result(result, record_writer)
                results.append(result)
        finally:
            browser.close()
    return results


def run_crawl_job_worker(
    job_queue: Queue,
    args,
    write_output: bool,
) -> List[CrawlJobResult]:
    results: List[CrawlJobResult] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        try:
            while True:
                try:
                    job = job_queue.get_nowait()
                except Empty:
                    break
                try:
                    record_writer = CrawlResultWriter(job.output_path) if write_output else None
                    result = run_crawl_job_with_browser(browser, job, args, record_writer)
                    if write_output:
                        write_crawl_result(result, record_writer)
                    results.append(result)
                finally:
                    job_queue.task_done()
        finally:
            browser.close()
    return results


def run_crawl_jobs(
    jobs: List[CrawlJob],
    args,
    worker_count: int,
    write_output: bool = True,
) -> List[CrawlJobResult]:
    if not jobs:
        return []
    worker_count = actual_worker_count(worker_count, len(jobs))
    if worker_count <= 1:
        return ordered_results(jobs, run_crawl_job_batch(jobs, args, write_output))

    results: List[CrawlJobResult] = []
    job_queue: Queue = Queue()
    for job in jobs:
        job_queue.put(job)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(run_crawl_job_worker, job_queue, args, write_output)
            for _ in range(worker_count)
        ]
        for future in as_completed(futures):
            results.extend(future.result())

    return ordered_results(jobs, results)


def run_crawl_jobs_for_stay(
    jobs: List[CrawlJob],
    args,
    worker_count: int,
) -> List[CrawlJobResult]:
    return run_crawl_jobs(jobs, args, worker_count, write_output=True)


def run_from_args(args) -> None:
    run_id = ensure_run_id(args)
    destinations = parse_destinations(args.destinations, args.destination)
    stays = iter_stays(args)
    jobs = build_crawl_jobs(args, destinations, stays)
    worker_count = actual_worker_count(args.workers, len(jobs))
    detail_concurrency = normalized_detail_concurrency(args)
    detail_pressure = estimated_detail_pressure(
        worker_count,
        detail_concurrency,
        args.enrich_details,
    )

    print(
        "Run: "
        f"destinations={len(destinations)} stays={len(stays)} jobs={len(jobs)} "
        f"pages={args.max_pages if args.max_pages > 0 else 'all'} headless={args.headless}"
    )
    print(
        "Concurrency: "
        f"requested_workers={args.workers} actual_workers={worker_count} "
        f"detail_concurrency={detail_concurrency} "
        f"detail_pressure={detail_pressure} scheduling=global"
    )
    print(
        "Loading: "
        f"scroll_rounds={args.max_scroll_rounds} stable={args.stable_rounds} "
        f"wait_ms={args.scroll_wait_ms} detail_timeout={args.detail_timeout} "
        f"field_retry={args.field_retry_timeout}msx{args.field_retry_count}"
    )
    print(
        "Output: "
        f"dir={args.output_dir} run_id={run_id} enrich={args.enrich_details} "
        f"missing_only={args.enrich_missing_only} detail_fields={args.detail_fields}"
    )
    print()

    run_started_at = datetime.now()
    results = run_crawl_jobs(jobs, args, worker_count, write_output=True)
    run_completed_at = datetime.now()
    results_by_stay: Dict[str, List[CrawlJobResult]] = defaultdict(list)
    for result in results:
        results_by_stay[result.job.check_in].append(result)

    for check_in, check_out in stays:
        output_path = output_path_for_stay(args, check_in, len(stays))
        print(
            f"\nStay {check_in} -> {check_out}: "
            f"jobs={len(jobs_for_stay(jobs, check_in))} output={output_path}"
        )

        stay_results = results_by_stay.get(check_in, [])
        stay_records = [
            record
            for result in stay_results
            for record in result.records
        ]
        debug_records = [
            record
            for result in stay_results
            for record in (result.debug_records or result.records)
        ]
        write_latest_outputs(debug_records, debug_output_path_for_stay(args, check_in))

        print(f"\nStay {check_in} -> {check_out} complete")
        if len(debug_records) != len(stay_records):
            print(
                "Output coverage: "
                f"{len(stay_records)}/{len(debug_records)} publishable, "
                f"{len(debug_records) - len(stay_records)} debug-only"
            )
        summarize(stay_records)
        elapsed_seconds = int((run_completed_at - run_started_at).total_seconds())
        print_verification_summary(stay_records, elapsed_seconds)
        if has_missing_price(stay_records):
            print(
                "Coverage warning: missing price records present; "
                "only records with required fields are published."
            )
        print(f"Saved JSONL: {output_path}\n")


def _job_log_prefix(job: CrawlJob) -> str:
    return f"{job.destination} {job.check_in}"


def should_fail_on_missing_price(args) -> bool:
    return False
