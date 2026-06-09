"""Hotel detail page enrichment for Agoda crawl records."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Page, sync_playwright

from agoda_crawler.config import (
    DETAIL_PROGRESS_INTERVAL,
    DETAIL_TIMEOUT,
    FIELD_RETRY_COUNT,
    FIELD_RETRY_TIMEOUT,
)
from agoda_crawler.extraction import extract_detail_fields
from agoda_crawler.utils.logging import current_log_prefix, log, log_ignored_error, log_prefix
from agoda_crawler.utils.page_helpers import handle_cookie_popup
from agoda_crawler.utils.resource_blocking import apply_resource_blocking
from agoda_crawler.extraction.selectors import FIELD_SELECTORS


DETAIL_ENRICH_FIELDS = (
    "price_value",
    "rating_text",
    "review_count_text",
    "image_url",
)
DEFAULT_DETAIL_ENRICH_FIELDS = ("price_value", "rating_text", "review_count_text")

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def enrich_records_from_details(
    context: BrowserContext,
    records: List[Dict],
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
    children: int,
    max_detail_pages: int,
    detail_workers: int = 1,
    headless: bool = True,
    locale: str = "vi-vn",
    enrich_missing_only: bool = True,
    detail_timeout: int = DETAIL_TIMEOUT,
    detail_fields: tuple[str, ...] = DEFAULT_DETAIL_ENRICH_FIELDS,
    field_retry_timeout: int = FIELD_RETRY_TIMEOUT,
    field_retry_count: int = FIELD_RETRY_COUNT,
) -> None:
    limit = None if max_detail_pages <= 0 else max_detail_pages
    candidates = sorted(
        (
            record
            for record in records
            if needs_detail_enrichment(record, enrich_missing_only, detail_fields)
        ),
        key=lambda record: detail_enrichment_sort_key(record, detail_fields),
    )
    if limit is not None:
        candidates = candidates[:limit]

    if not candidates:
        for record in records:
            record.setdefault("enrich_status", "skipped")
            record.setdefault("enrich_error", None)
        return

    candidate_ids = {id(record) for record in candidates}
    for record in records:
        if id(record) not in candidate_ids:
            record["enrich_status"] = "skipped"
            record["enrich_error"] = None

    worker_count = max(1, min(detail_workers, len(candidates)))
    if worker_count == 1:
        enrich_records_from_details_serial(
            context,
            candidates,
            check_in=check_in,
            check_out=check_out,
            adults=adults,
            rooms=rooms,
            children=children,
            total_label=str(len(candidates)),
            detail_timeout=detail_timeout,
            detail_fields=detail_fields,
            field_retry_timeout=field_retry_timeout,
            field_retry_count=field_retry_count,
        )
        return

    total_label = str(len(candidates))
    log(
        f"Detail: enriching {len(candidates)} records with {worker_count} workers "
        "(isolated browser/context per worker)"
    )
    enrich_records_from_details_parallel(
        candidates,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        rooms=rooms,
        children=children,
        total_label=total_label,
        detail_workers=worker_count,
        headless=headless,
        locale=locale,
        detail_timeout=detail_timeout,
        parent_log_prefix=current_log_prefix(),
        detail_fields=detail_fields,
        field_retry_timeout=field_retry_timeout,
        field_retry_count=field_retry_count,
    )


def enrich_records_from_details_parallel(
    candidates: List[Dict],
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
    children: int,
    total_label: str,
    detail_workers: int,
    headless: bool,
    locale: str,
    detail_timeout: int,
    parent_log_prefix: str,
    detail_fields: tuple[str, ...],
    field_retry_timeout: int,
    field_retry_count: int,
) -> None:
    progress = {
        "started": 0,
        "completed": 0,
        "failed": 0,
        "total": len(candidates),
        "started_at": time.perf_counter(),
        "last_log_at": time.perf_counter(),
    }
    progress_lock = threading.Lock()
    chunks = chunk_records(candidates, detail_workers)

    with ThreadPoolExecutor(max_workers=detail_workers) as executor:
        futures = [
            executor.submit(
                enrich_detail_record_batch,
                chunk,
                check_in,
                check_out,
                adults,
                rooms,
                children,
                total_label,
                progress,
                progress_lock,
                headless,
                locale,
                detail_timeout,
                parent_log_prefix,
                detail_fields,
                field_retry_timeout,
                field_retry_count,
            )
            for chunk in chunks
        ]
        for future in as_completed(futures):
            future.result()


def chunk_records(records: List[Dict], chunk_count: int) -> List[List[Dict]]:
    chunks: List[List[Dict]] = [[] for _ in range(chunk_count)]
    for index, record in enumerate(records):
        chunks[index % chunk_count].append(record)
    return [chunk for chunk in chunks if chunk]


def enrich_records_from_details_serial(
    context: BrowserContext,
    candidates: List[Dict],
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
    children: int,
    total_label: str,
    detail_timeout: int,
    detail_fields: tuple[str, ...],
    field_retry_timeout: int,
    field_retry_count: int,
) -> None:
    log(f"Detail: enriching {len(candidates)} records with 1 worker")
    started_at = time.perf_counter()
    last_log_at = started_at
    failed = 0
    detail_page = context.new_page()
    try:
        for index, record in enumerate(candidates, start=1):
            enrich_one_record_on_page(
                detail_page,
                record,
                check_in,
                check_out,
                adults,
                rooms,
                children,
                index,
                total_label,
                detail_timeout,
                detail_fields,
                field_retry_timeout,
                field_retry_count,
            )
            if record.get("enrich_status") == "failed":
                failed += 1
            now = time.perf_counter()
            if index == len(candidates) or now - last_log_at >= DETAIL_PROGRESS_INTERVAL:
                last_log_at = now
                log(
                    f"Detail progress: {index}/{len(candidates)} "
                    f"failed={failed} elapsed={format_seconds(now - started_at)} "
                    f"avg={format_seconds((now - started_at) / max(1, index))}"
                )
    finally:
        try:
            detail_page.close()
        except Exception as exc:
            log_ignored_error("Detail page close failed", exc)


def enrich_detail_record_batch(
    records: List[Dict],
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
    children: int,
    total_label: str,
    progress: Dict[str, int],
    progress_lock: threading.Lock,
    headless: bool,
    locale: str,
    detail_timeout: int,
    parent_log_prefix: str,
    detail_fields: tuple[str, ...],
    field_retry_timeout: int,
    field_retry_count: int,
) -> None:
    with log_prefix(parent_log_prefix):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(**browser_context_options(locale))
            apply_resource_blocking(context)
            detail_page = context.new_page()
            try:
                for record in records:
                    with progress_lock:
                        progress["started"] += 1
                        index = progress["started"]
                    enrich_one_record_on_page(
                        detail_page,
                        record,
                        check_in,
                        check_out,
                        adults,
                        rooms,
                        children,
                        index,
                        total_label,
                        detail_timeout,
                        detail_fields,
                        field_retry_timeout,
                        field_retry_count,
                    )
                    update_detail_progress(progress, progress_lock, record)
            finally:
                try:
                    detail_page.close()
                except Exception as exc:
                    log_ignored_error("Detail page close failed", exc)
                try:
                    context.close()
                except Exception as exc:
                    log_ignored_error("Detail context close failed", exc)
                try:
                    browser.close()
                except Exception as exc:
                    log_ignored_error("Detail browser close failed", exc)


def update_detail_progress(
    progress: Dict[str, float],
    progress_lock: threading.Lock,
    record: Dict,
) -> None:
    with progress_lock:
        progress["completed"] += 1
        if record.get("enrich_status") == "failed":
            progress["failed"] += 1
        completed = int(progress["completed"])
        failed = int(progress["failed"])
        total = int(progress["total"])
        now = time.perf_counter()
        elapsed = now - float(progress["started_at"])
        should_log = (
            completed >= total
            or now - float(progress["last_log_at"]) >= DETAIL_PROGRESS_INTERVAL
        )
        if should_log:
            progress["last_log_at"] = now
    if should_log:
        log(
            f"Detail progress: {completed}/{total} "
            f"failed={failed} elapsed={format_seconds(elapsed)} "
            f"avg={format_seconds(elapsed / max(1, completed))}"
        )


def enrich_one_record_on_page(
    detail_page: Page,
    record: Dict,
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
    children: int,
    index: int,
    total_label: str,
    detail_timeout: int,
    detail_fields: tuple[str, ...],
    field_retry_timeout: int,
    field_retry_count: int,
) -> None:
    hotel_url = record.get("hotel_url")
    target_url = with_stay_params(
        hotel_url,
        check_in,
        check_out,
        adults=adults,
        rooms=rooms,
        children=children,
    )
    started_at = time.perf_counter()
    try:
        record["enrich_status"] = "attempted"
        record["enrich_error"] = None
        load_started_at = time.perf_counter()
        detail_page.goto(target_url, wait_until="domcontentloaded", timeout=detail_timeout)
        record["_detail_load_seconds"] = elapsed_seconds(load_started_at)
        handle_cookie_popup(detail_page)
        missing_fields = missing_detail_fields(record, detail_fields)
        extract_started_at = time.perf_counter()
        extracted_fields = extract_detail_fields_with_field_retry(
            detail_page,
            missing_fields=missing_fields,
            retry_timeout=field_retry_timeout,
            retry_count=field_retry_count,
        )
        record["_detail_extract_seconds"] = elapsed_seconds(extract_started_at)
    except Exception as exc:
        error_text = str(exc).splitlines()[0]
        record["enrich_status"] = "failed"
        record["enrich_error"] = error_text
        record["_detail_total_seconds"] = elapsed_seconds(started_at)
        log(
            f"Detail failed: {index}/{total_label} "
            f"time={format_seconds(record['_detail_total_seconds'])} - {error_text}"
        )
        return

    merge_missing_fields(record, extracted_fields)
    record["enrich_status"] = "success"
    record["enrich_error"] = None
    record["_detail_total_seconds"] = elapsed_seconds(started_at)


def needs_detail_enrichment(
    record: Dict,
    enrich_missing_only: bool = True,
    detail_fields: tuple[str, ...] = DEFAULT_DETAIL_ENRICH_FIELDS,
) -> bool:
    if not record.get("hotel_url"):
        return False
    if not enrich_missing_only:
        return True
    fields = detail_fields or DEFAULT_DETAIL_ENRICH_FIELDS
    return any(not record.get(field) for field in fields)


def missing_detail_fields(record: Dict, detail_fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(field for field in (detail_fields or DEFAULT_DETAIL_ENRICH_FIELDS) if not record.get(field))


def extract_detail_fields_with_field_retry(
    page: Page,
    missing_fields: tuple[str, ...],
    retry_timeout: int,
    retry_count: int,
) -> Dict:
    target_fields = tuple(field for field in missing_fields if field in FIELD_SELECTORS)
    if target_fields:
        wait_for_any_detail_field(page, target_fields, retry_timeout)

    detail_fields = extract_detail_fields(page)
    remaining_fields = remaining_missing_fields(detail_fields, target_fields)
    for _ in range(max(0, retry_count)):
        if not remaining_fields:
            break
        scroll_detail_for_fields(page, remaining_fields, retry_timeout)
        retry_fields = extract_detail_fields(page)
        merge_missing_fields(detail_fields, retry_fields)
        remaining_fields = remaining_missing_fields(detail_fields, target_fields)
    return detail_fields


def remaining_missing_fields(detail_fields: Dict, target_fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(field for field in target_fields if not detail_fields.get(field))


def wait_for_any_detail_field(page: Page, fields: tuple[str, ...], timeout_ms: int) -> bool:
    selectors: List[str] = []
    for field in fields:
        selectors.extend(FIELD_SELECTORS.get(field) or [])
    deadline = time.perf_counter() + max(0, timeout_ms) / 1000.0
    for selector in selectors:
        remaining_ms = int((deadline - time.perf_counter()) * 1000)
        if remaining_ms <= 0:
            break
        try:
            page.locator(selector).first.wait_for(state="attached", timeout=min(remaining_ms, 500))
            return True
        except Exception:
            continue
    return False


def scroll_detail_for_fields(page: Page, fields: tuple[str, ...], timeout_ms: int) -> None:
    try:
        page.mouse.wheel(0, 1800)
    except Exception as exc:
        log_ignored_error("Detail scroll failed", exc)
    wait_for_any_detail_field(page, fields, timeout_ms)


def detail_enrichment_sort_key(
    record: Dict,
    detail_fields: tuple[str, ...] = DEFAULT_DETAIL_ENRICH_FIELDS,
) -> tuple:
    missing_count = sum(1 for field in DETAIL_ENRICH_FIELDS if not record.get(field))
    critical_missing = sum(1 for field in detail_fields if not record.get(field))
    hotel_name = (record.get("hotel_name") or "").strip().lower()
    hotel_url = (record.get("hotel_url") or "").strip().lower()
    return (-critical_missing, -missing_count, hotel_name, hotel_url)


def merge_missing_fields(record: Dict, detail_fields: Dict) -> bool:
    changed = False
    for field, value in detail_fields.items():
        if value and not record.get(field):
            record[field] = value
            changed = True
    return changed


def with_stay_params(
    hotel_url: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
) -> str:
    split = urlsplit(hotel_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    cid = query.get("cid", "-1")
    currency = query.get("currencyCode", "VND")
    query.update(
        {
            "cid": cid,
            "checkIn": check_in,
            "checkOut": check_out,
            "los": los_from_dates(check_in, check_out),
            "rooms": str(rooms),
            "adults": str(adults),
            "children": str(children),
            "finalPriceView": "1",
            "isShowMobileAppPrice": "false",
            "familyMode": "false",
            "maxRooms": "0",
            "childAges": "",
            "numberOfGuest": "0",
            "missingChildAges": "false",
            "travellerType": "1",
            "showReviewSubmissionEntry": "false",
            "currencyCode": currency,
            "isFreeOccSearch": "false",
        }
    )
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), ""))


def los_from_dates(check_in: str, check_out: str) -> str:
    check_in_date = datetime.strptime(check_in, "%Y-%m-%d").date()
    check_out_date = datetime.strptime(check_out, "%Y-%m-%d").date()
    return str((check_out_date - check_in_date).days)


def browser_context_options(locale: str) -> Dict:
    browser_locale = playwright_locale(locale)
    return {
        "locale": browser_locale,
        "timezone_id": "Asia/Bangkok",
        "viewport": {"width": 1366, "height": 900},
        "user_agent": DESKTOP_USER_AGENT,
        "extra_http_headers": {
            "Accept-Language": f"{browser_locale},{browser_locale.split('-')[0]};q=0.9,en-US;q=0.8,en;q=0.7",
        },
    }


def playwright_locale(locale: str) -> str:
    parts = locale.replace("_", "-").split("-")
    if len(parts) == 2:
        return f"{parts[0].lower()}-{parts[1].upper()}"
    return locale


def format_seconds(seconds: float) -> str:
    return f"{seconds:.1f}s"


def elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 2)
