"""Agoda hotel search crawler."""
import time
from typing import Dict, List, Optional

from playwright.sync_api import Browser, Page, sync_playwright

from agoda_crawler.config import (
    DETAIL_TIMEOUT,
    FIELD_RETRY_COUNT,
    FIELD_RETRY_TIMEOUT,
    LOW_NEW_RECORD_ROUNDS,
    LOW_NEW_RECORD_THRESHOLD,
    MAX_SCROLL_ROUNDS,
    SCROLL_WAIT_MS,
    STABLE_ROUNDS,
)
from agoda_crawler.enrichment.detail import (
    DEFAULT_DETAIL_ENRICH_FIELDS,
    browser_context_options as _browser_context_options,
    enrich_records_from_details as _enrich_records_from_details,
    merge_missing_fields as _merge_missing_fields,
    needs_detail_enrichment as _needs_detail_enrichment,
    with_stay_params as _with_stay_params,
)
from agoda_crawler.listing.page_crawl import (
    crawl_current_results_page as _crawl_current_results_page,
    page_scroll_summary as _page_scroll_summary,
    probe_current_page_state as _probe_current_page_state,
)
from agoda_crawler.listing.pagination import (
    PaginationState,
    attach_pagination_summary as _attach_pagination_summary,
    capture_pagination_state as _capture_pagination_state,
    go_to_verified_page_start as _go_to_verified_page_start,
    pagination_change_evidence as _pagination_change_evidence,
)
from agoda_crawler.listing.records import (
    merge_records_into_results as _merge_records_into_results,
    record_key as _record_key,
)
from agoda_crawler.listing.scrolling import scroll_y as _scroll_y
from agoda_crawler.navigation import search_hotels_via_ui
from agoda_crawler.utils.crawl_metrics import (
    attach_timing_summary as _attach_timing_summary,
    elapsed_seconds as _elapsed_seconds,
    format_seconds as _format_seconds,
    mark_price_coverage_status as _mark_price_coverage_status,
    timing_bottleneck as _timing_bottleneck,
)
from agoda_crawler.utils.debug_artifacts import (
    save_pagination_page_artifacts as _save_pagination_page_artifacts,
    update_page_debug_status as _update_page_debug_status,
)
from agoda_crawler.utils.logging import log, log_ignored_error
from agoda_crawler.utils.page_helpers import wait_for_cards
from agoda_crawler.utils.resource_blocking import apply_resource_blocking


PAGINATION_NAVIGATION_ATTEMPTS = 3


def _navigate_to_results(
    page: Page,
    destination: str,
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
    children: int,
) -> str:
    """
    Run the Agoda hotel search using homepage UI only.

    The navigation module validates the results page by hotel card presence.
    """
    return search_hotels_via_ui(
        page,
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        rooms=rooms,
        children=children,
    )


def _validate_supported_occupancy(adults: int, rooms: int, children: int) -> None:
    if adults < 1:
        raise ValueError("adults must be >= 1")
    if rooms < 1:
        raise ValueError("rooms must be >= 1")
    if children < 0:
        raise ValueError("children must be >= 0")


def _reached_page_limit(current_page: int, max_pages: int) -> bool:
    return max_pages > 0 and current_page >= max_pages


def _is_low_new_record_page(new_count: int, threshold: int = LOW_NEW_RECORD_THRESHOLD) -> bool:
    return new_count < threshold


def _deduped_page_records(records_by_key: Dict[str, Dict], page_records: List[Dict]) -> List[Dict]:
    records: List[Dict] = []
    seen_ids = set()
    for page_record in page_records:
        record = records_by_key.get(_record_key(page_record))
        if record is None:
            continue
        record_id = id(record)
        if record_id in seen_ids:
            continue
        seen_ids.add(record_id)
        records.append(record)
    return records


def _should_retry_duplicate_page(attempt: int, max_attempts: int = PAGINATION_NAVIGATION_ATTEMPTS) -> bool:
    return attempt < max_attempts


def _enrich_pending_records(
    context,
    records: List[Dict],
    check_in: str,
    check_out: str,
    adults: int,
    rooms: int,
    children: int,
    detail_pages_used: int,
    max_detail_pages: int,
    detail_concurrency: int,
    headless: bool,
    locale: str,
    enrich_missing_only: bool,
    detail_timeout: int,
    detail_fields: tuple[str, ...],
    field_retry_timeout: int,
    field_retry_count: int,
) -> int:
    pending = [
        record
        for record in records
        if not record.get("enrich_status")
        and _needs_detail_enrichment(record, enrich_missing_only, detail_fields)
    ]
    if not pending:
        return detail_pages_used

    if max_detail_pages > 0:
        remaining = max_detail_pages - detail_pages_used
        if remaining <= 0:
            for record in pending:
                record["enrich_status"] = "skipped"
                record["enrich_error"] = "max_detail_pages_reached"
            return detail_pages_used
        pending = pending[:remaining]

    _enrich_records_from_details(
        context,
        pending,
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        rooms=rooms,
        children=children,
        max_detail_pages=0,
        detail_concurrency=max(1, detail_concurrency),
        headless=headless,
        locale=locale,
        enrich_missing_only=enrich_missing_only,
        detail_timeout=detail_timeout,
        detail_fields=detail_fields,
        field_retry_timeout=field_retry_timeout,
        field_retry_count=field_retry_count,
    )
    return detail_pages_used + len(pending)


def crawl_agoda_search(
    max_pages: int = 2,
    headless: bool = False,
    destination: str = "Vung Tau",
    check_in: str = "2026-06-10",
    check_out: str = "2026-06-11",
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
    locale: str = "vi-vn",
    enrich_details: bool = False,
    max_detail_pages: int = 10,
    detail_concurrency: int = 1,
    enrich_missing_only: bool = True,
    detail_timeout: int = DETAIL_TIMEOUT,
    max_scroll_rounds: int = MAX_SCROLL_ROUNDS,
    stable_rounds: int = STABLE_ROUNDS,
    scroll_wait_ms: int = SCROLL_WAIT_MS,
    detail_fields: tuple[str, ...] = DEFAULT_DETAIL_ENRICH_FIELDS,
    field_retry_timeout: int = FIELD_RETRY_TIMEOUT,
    field_retry_count: int = FIELD_RETRY_COUNT,
) -> List[Dict]:
    """
    Crawl Agoda hotel search results and return a list of hotel records.

    Search is intentionally UI-only:
    - open Agoda homepage
    - force Hotels tab
    - select destination suggestion
    - select dates in calendar
    - click Search
    - validate hotel listing cards before extraction
    """
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(headless=headless)
            return crawl_agoda_search_with_browser(
                browser,
                max_pages=max_pages,
                destination=destination,
                check_in=check_in,
                check_out=check_out,
                adults=adults,
                rooms=rooms,
                children=children,
                locale=locale,
                enrich_details=enrich_details,
                max_detail_pages=max_detail_pages,
                detail_concurrency=detail_concurrency,
                enrich_missing_only=enrich_missing_only,
                detail_timeout=detail_timeout,
                max_scroll_rounds=max_scroll_rounds,
                stable_rounds=stable_rounds,
                scroll_wait_ms=scroll_wait_ms,
                headless=headless,
                detail_fields=detail_fields,
                field_retry_timeout=field_retry_timeout,
                field_retry_count=field_retry_count,
            )
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception as exc:
                    log_ignored_error("Browser close failed", exc)


def crawl_agoda_search_with_browser(
    browser: Browser,
    max_pages: int = 2,
    headless: bool = True,
    destination: str = "Vung Tau",
    check_in: str = "2026-06-10",
    check_out: str = "2026-06-11",
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
    locale: str = "vi-vn",
    enrich_details: bool = False,
    max_detail_pages: int = 10,
    detail_concurrency: int = 1,
    enrich_missing_only: bool = True,
    detail_timeout: int = DETAIL_TIMEOUT,
    max_scroll_rounds: int = MAX_SCROLL_ROUNDS,
    stable_rounds: int = STABLE_ROUNDS,
    scroll_wait_ms: int = SCROLL_WAIT_MS,
    detail_fields: tuple[str, ...] = DEFAULT_DETAIL_ENRICH_FIELDS,
    field_retry_timeout: int = FIELD_RETRY_TIMEOUT,
    field_retry_count: int = FIELD_RETRY_COUNT,
) -> List[Dict]:
    """Crawl one Agoda search using an existing browser instance."""
    _validate_supported_occupancy(adults, rooms, children)

    job_started_at = time.perf_counter()
    timing: Dict[str, float] = {}
    results_by_key: Dict[str, Dict] = {}
    context = None
    try:
        context = browser.new_context(**_browser_context_options(locale))
        apply_resource_blocking(context)
        page: Page = context.new_page()

        search_started_at = time.perf_counter()
        card_selector = _navigate_to_results(
            page,
            destination,
            check_in,
            check_out,
            adults,
            rooms,
            children,
        )
        timing["search_seconds"] = _elapsed_seconds(search_started_at)
        log(f"Timing: search={_format_seconds(timing['search_seconds'])}")

        requested_pages = max_pages if max_pages > 0 else 0
        pages_collected = 0
        duplicate_pages = 0
        page_unique_url_counts: Dict[int, int] = {}
        page_unique_record_counts: Dict[int, int] = {}
        page_statuses: Dict[int, str] = {}
        page_scroll_summaries: Dict[int, Dict] = {}
        accepted_state: Optional[PaginationState] = None
        current_page = 1
        low_new_record_rounds = 0
        detail_pages_used = 0
        detail_seconds = 0.0

        listing_started_at = time.perf_counter()
        page_result = _crawl_current_results_page(
            page,
            card_selector,
            current_page,
            max_rounds=max_scroll_rounds,
            stable_rounds=stable_rounds,
            scroll_wait_ms=scroll_wait_ms,
        )
        page_records = page_result.records
        accepted_state = _capture_pagination_state(page, current_page, page_records)
        page_unique_url_counts[current_page] = len(accepted_state.canonical_urls)
        page_unique_record_counts[current_page] = len(page_records)
        page_scroll_summaries[current_page] = _page_scroll_summary(page_result)
        page_statuses[current_page] = "collected"
        _update_page_debug_status(current_page, "collected")
        new_count = _merge_records_into_results(results_by_key, page_records)
        if _is_low_new_record_page(new_count):
            low_new_record_rounds += 1
        else:
            low_new_record_rounds = 0
        pages_collected += 1
        log(
            f"Page {current_page} done: "
            f"records={len(page_records)} new={new_count} total={len(results_by_key)} "
            f"time={_format_seconds(page_result.elapsed_seconds)}"
        )
        while not _reached_page_limit(current_page, max_pages):
            target_page = current_page + 1
            navigated = False
            for attempt in range(1, PAGINATION_NAVIGATION_ATTEMPTS + 1):
                if accepted_state and attempt > 1:
                    try:
                        page.goto(accepted_state.url, wait_until="domcontentloaded", timeout=30_000)
                        wait_for_cards(page)
                    except Exception as exc:
                        log_ignored_error(
                            f"Page {target_page}: retry reload failed attempt={attempt}/3",
                            exc,
                        )
                if not _go_to_verified_page_start(
                    page,
                    target_page,
                    prefer_next=(attempt == 1),
                ):
                    continue
                card_selector = wait_for_cards(page)
                scroll_y_after_navigation = _scroll_y(page)
                probe_state = _probe_current_page_state(
                    page,
                    card_selector,
                    target_page,
                    scroll_y_after_navigation=scroll_y_after_navigation,
                    scroll_wait_ms=scroll_wait_ms,
                )
                probe_evidence = (
                    _pagination_change_evidence(accepted_state, probe_state)
                    if accepted_state
                    else {"verified": True, "signs": {}, "sign_count": 0}
                )
                if not probe_evidence.get("verified"):
                    page_unique_url_counts[target_page] = len(probe_state.canonical_urls)
                    page_unique_record_counts[target_page] = len(probe_state.canonical_urls)
                    page_statuses[target_page] = "duplicate_page"
                    _save_pagination_page_artifacts(
                        page,
                        target_page,
                        "duplicate_page",
                        probe_evidence,
                    )
                    log(
                        f"Page {target_page}: duplicate probe "
                        f"attempt={attempt}/3 signs={probe_evidence.get('sign_count')}"
                    )
                    continue

                try:
                    page.evaluate("() => window.scrollTo(0, 0)")
                    page.wait_for_timeout(500)
                except Exception as exc:
                    log_ignored_error(f"Page {target_page}: scroll reset failed", exc)
                candidate_result = _crawl_current_results_page(
                    page,
                    card_selector,
                    target_page,
                    max_rounds=max_scroll_rounds,
                    stable_rounds=stable_rounds,
                    scroll_wait_ms=scroll_wait_ms,
                )
                candidate_records = candidate_result.records
                candidate_state = _capture_pagination_state(
                    page,
                    target_page,
                    candidate_records,
                    scroll_y_after_navigation=scroll_y_after_navigation,
                )
                evidence = (
                    _pagination_change_evidence(accepted_state, candidate_state)
                    if accepted_state
                    else {"verified": True, "signs": {}, "sign_count": 0}
                )
                page_unique_url_counts[target_page] = len(candidate_state.canonical_urls)
                if evidence.get("verified"):
                    new_count = _merge_records_into_results(results_by_key, candidate_records)
                    if _is_low_new_record_page(new_count):
                        low_new_record_rounds += 1
                    else:
                        low_new_record_rounds = 0
                    log(
                        f"Page {target_page} done: "
                        f"records={len(candidate_records)} new={new_count} "
                        f"total={len(results_by_key)} signs={evidence.get('sign_count')} "
                        f"time={_format_seconds(candidate_result.elapsed_seconds)}"
                    )
                    pages_collected += 1
                    page_unique_record_counts[target_page] = len(candidate_records)
                    page_scroll_summaries[target_page] = _page_scroll_summary(candidate_result)
                    page_statuses[target_page] = "collected"
                    _update_page_debug_status(target_page, "collected", evidence)
                    accepted_state = candidate_state
                    current_page = target_page
                    navigated = True
                    break

                page_statuses[target_page] = "duplicate_page"
                _update_page_debug_status(target_page, "duplicate_page", evidence)
                _save_pagination_page_artifacts(
                    page,
                    target_page,
                    "duplicate_page",
                    evidence,
                )
                log(
                    f"Page {target_page}: duplicate "
                    f"attempt={attempt}/{PAGINATION_NAVIGATION_ATTEMPTS} "
                    f"signs={evidence.get('sign_count')}"
                )
                if _should_retry_duplicate_page(attempt):
                    continue
                break
            if not navigated:
                duplicate_pages += 1
                break
            if low_new_record_rounds >= LOW_NEW_RECORD_ROUNDS:
                log(
                    "Pagination stopped: "
                    f"new_records_below_{LOW_NEW_RECORD_THRESHOLD} "
                    f"for {low_new_record_rounds} consecutive pages"
                )
                break

        all_results = list(results_by_key.values())
        timing["listing_seconds"] = max(0.0, _elapsed_seconds(listing_started_at) - detail_seconds)
        log(
            f"Timing: listing={_format_seconds(timing['listing_seconds'])} "
            f"pages={pages_collected} records={len(all_results)}"
        )
        _attach_pagination_summary(
            all_results,
            pages_requested=requested_pages,
            pages_collected=pages_collected,
            duplicate_pages=duplicate_pages,
            page_unique_url_counts=page_unique_url_counts,
            page_unique_record_counts=page_unique_record_counts,
            page_statuses=page_statuses,
            page_scroll_summaries=page_scroll_summaries,
        )
        if enrich_details:
            detail_batch_started_at = time.perf_counter()
            detail_pages_used = _enrich_pending_records(
                context,
                all_results,
                check_in,
                check_out,
                adults,
                rooms,
                children,
                detail_pages_used,
                max(0, max_detail_pages),
                detail_concurrency,
                headless,
                locale,
                enrich_missing_only,
                detail_timeout,
                detail_fields,
                field_retry_timeout,
                field_retry_count,
            )
            detail_seconds += _elapsed_seconds(detail_batch_started_at)
            timing["detail_seconds"] = detail_seconds
            log(f"Timing: detail={_format_seconds(timing['detail_seconds'])}")
        else:
            timing["detail_seconds"] = 0.0
        _mark_price_coverage_status(all_results)
        timing["total_seconds"] = _elapsed_seconds(job_started_at)
        _attach_timing_summary(all_results, timing)
        log(
            "Timing total: "
            f"search={_format_seconds(timing.get('search_seconds', 0.0))} "
            f"listing={_format_seconds(timing.get('listing_seconds', 0.0))} "
            f"detail={_format_seconds(timing.get('detail_seconds', 0.0))} "
            f"total={_format_seconds(timing.get('total_seconds', 0.0))} "
            f"bottleneck={_timing_bottleneck(timing)}"
        )
    finally:
        if context is not None:
            try:
                context.close()
            except Exception as exc:
                log_ignored_error("Context close failed", exc)

    return list(results_by_key.values())
