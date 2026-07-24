"""Crawl and collect records from the current Agoda listing page."""
import time
from dataclasses import dataclass
from typing import Dict, List

from playwright.sync_api import Page

from agoda_crawler.config import (
    LISTING_FULL_SNAPSHOT_INTERVAL,
    MAX_LISTING_PAGE_SECONDS,
    MIN_PAGE_HOTELS_BEFORE_STABLE,
    MIN_PAGE_HOTELS_BEFORE_FALLBACK,
    MIN_PAGE_HOTELS_BEFORE_TIME_CAP,
    MAX_SCROLL_ROUNDS,
    STABLE_ROUNDS,
    SAVE_DEBUG_ARTIFACTS,
    SCROLL_WAIT_MS,
    WAIT_BEFORE_SCRAPE,
)
from agoda_crawler.extraction import extract_page_results
from agoda_crawler.listing.collection import (
    ListingCollectionMetrics,
    ListingCollectionSnapshot,
    collect_listing_snapshot,
)
from agoda_crawler.listing.pagination import (
    PaginationState,
    capture_pagination_state,
)
from agoda_crawler.listing.records import (
    merge_page_record,
    records_with_url_count,
)
from agoda_crawler.listing.scrolling import (
    advance_results_scroll,
    wait_for_lazy_results,
)
from agoda_crawler.utils.crawl_metrics import elapsed_seconds
from agoda_crawler.utils.debug_artifacts import (
    save_final_listing_artifacts,
    save_listing_debug_artifacts,
)
from agoda_crawler.utils.page_helpers import handle_cookie_popup


@dataclass(frozen=True)
class PageCrawlResult:
    records: List[Dict]
    metrics: ListingCollectionMetrics
    scroll_rounds: int
    scroll_metrics: List[Dict]
    selected_scroll_target: str
    elapsed_seconds: float


@dataclass(frozen=True)
class ListingWaitResult:
    snapshot: object
    updated_existing: bool
    elapsed_ms: int
    grew: bool


@dataclass(frozen=True)
class ListingMergeResult:
    snapshot: ListingCollectionSnapshot
    updated_existing: bool


def crawl_current_results_page(
    page: Page,
    card_selector: str,
    page_number: int,
    max_rounds: int = MAX_SCROLL_ROUNDS,
    stable_rounds: int = STABLE_ROUNDS,
    scroll_wait_ms: int = SCROLL_WAIT_MS,
) -> PageCrawlResult:
    page_started_at = time.perf_counter()
    records_by_key: Dict[str, Dict] = {}
    unchanged_rounds = 0
    no_scroll_rounds = 0
    last_metrics = ListingCollectionMetrics()
    debug_saved = False
    completed_rounds = 0
    scroll_metrics: List[Dict] = []
    selected_scroll_target = "unknown"

    for round_number in range(1, max_rounds + 1):
        completed_rounds = round_number
        handle_cookie_popup(page)
        page.wait_for_timeout(WAIT_BEFORE_SCRAPE)
        before_count = len(records_by_key)

        merge_result = collect_and_merge_listing_snapshot(
            page,
            card_selector,
            page_number,
            records_by_key,
            round_number,
            full_snapshot=should_collect_full_listing_snapshot(round_number),
        )
        snapshot = merge_result.snapshot
        last_metrics = snapshot.metrics
        updated_existing = merge_result.updated_existing
        wait_before_count = len(records_by_key)
        wait_before_url_count = records_with_url_count(records_by_key)
        wait_before_dom_count = snapshot.metrics.dom_card_count

        if round_number >= max_rounds:
            break

        scroll_advance = advance_results_scroll(page)
        selected_scroll_target = scroll_advance.target or selected_scroll_target
        wait_result = wait_for_listing_growth(
            page,
            card_selector,
            page_number,
            records_by_key,
            round_number,
            before_total=wait_before_count,
            before_url_count=wait_before_url_count,
            before_dom_count=wait_before_dom_count,
            timeout_ms=scroll_wait_ms,
        )
        after_snapshot = wait_result.snapshot
        after_metrics = after_snapshot.metrics
        last_metrics = after_metrics

        updated_existing = wait_result.updated_existing or updated_existing

        if len(records_by_key) > before_count or updated_existing:
            unchanged_rounds = 0
        else:
            unchanged_rounds += 1

        if scroll_advance.moved or after_metrics.scroll_y != snapshot.metrics.scroll_y:
            no_scroll_rounds = 0
        else:
            no_scroll_rounds += 1

        newly_collected = max(0, len(records_by_key) - before_count)
        records_with_url = sum(1 for record in records_by_key.values() if record.get("hotel_url"))
        records_missing_url = len(records_by_key) - records_with_url
        round_metrics = {
            "round": round_number,
            "scroll_y": scroll_advance.scroll_y,
            "scroll_height": scroll_advance.scroll_height,
            "client_height": scroll_advance.client_height,
            "visible_dom_cards": after_metrics.dom_card_count,
            "newly_collected": newly_collected,
            "total_unique_collected": len(records_by_key),
            "records_with_url": records_with_url,
            "records_missing_url": records_missing_url,
            "selected_scroll_target": scroll_advance.target,
            "moved": scroll_advance.moved,
            "wait_ms": wait_result.elapsed_ms,
            "wait_grew": wait_result.grew,
        }
        scroll_metrics.append(round_metrics)

        if (
            SAVE_DEBUG_ARTIFACTS
            and
            not debug_saved
            and after_metrics.dom_card_count >= 20
            and after_metrics.unique_hotel_count < int(after_metrics.dom_card_count * 0.75)
        ):
            save_listing_debug_artifacts(page, page_number, after_metrics)
            debug_saved = True

        if should_stop_listing_scroll(
            record_count=len(records_by_key),
            unchanged_rounds=unchanged_rounds,
            no_scroll_rounds=no_scroll_rounds,
            stable_rounds=stable_rounds,
            elapsed_seconds=time.perf_counter() - page_started_at,
        ):
            break

    final_merge_result = collect_and_merge_listing_snapshot(
        page,
        card_selector,
        page_number,
        records_by_key,
        completed_rounds,
        full_snapshot=True,
    )
    last_metrics = final_merge_result.snapshot.metrics

    save_final_listing_artifacts(
        page,
        page_number,
        last_metrics,
        completed_rounds,
        scroll_metrics,
        selected_scroll_target,
    )

    page_elapsed_seconds = time.perf_counter() - page_started_at
    should_run_fallback = (
        len(records_by_key) < MIN_PAGE_HOTELS_BEFORE_FALLBACK
        and (
            MAX_LISTING_PAGE_SECONDS <= 0
            or page_elapsed_seconds < MAX_LISTING_PAGE_SECONDS
        )
    )
    if should_run_fallback:
        for record in extract_page_results(page, card_selector):
            attach_listing_metrics(record, page_number, last_metrics, completed_rounds)
            merge_page_record(records_by_key, record)

    return PageCrawlResult(
        records=list(records_by_key.values()),
        metrics=last_metrics,
        scroll_rounds=completed_rounds,
        scroll_metrics=scroll_metrics,
        selected_scroll_target=selected_scroll_target,
        elapsed_seconds=elapsed_seconds(page_started_at),
    )


def merge_listing_snapshot(
    records_by_key: Dict[str, Dict],
    snapshot,
    page_number: int,
    round_number: int,
) -> bool:
    updated_existing = False
    for record in snapshot.records:
        attach_listing_metrics(record, page_number, snapshot.metrics, round_number)
        updated_existing = merge_page_record(records_by_key, record) or updated_existing
    return updated_existing


def collect_and_merge_listing_snapshot(
    page: Page,
    card_selector: str,
    page_number: int,
    records_by_key: Dict[str, Dict],
    round_number: int,
    full_snapshot: bool = True,
) -> ListingMergeResult:
    """Collect the current DOM state immediately and keep any records found."""
    snapshot = collect_listing_snapshot(
        page,
        card_selector,
        page_number,
        include_embedded=full_snapshot,
        include_broad_selectors=full_snapshot,
    )
    updated_existing = merge_listing_snapshot(
        records_by_key,
        snapshot,
        page_number,
        round_number,
    )
    return ListingMergeResult(snapshot=snapshot, updated_existing=updated_existing)


def should_collect_full_listing_snapshot(round_number: int) -> bool:
    interval = max(0, LISTING_FULL_SNAPSHOT_INTERVAL)
    return round_number <= 1 or (interval > 0 and round_number % interval == 0)


def should_stop_listing_scroll(
    record_count: int,
    unchanged_rounds: int,
    no_scroll_rounds: int,
    stable_rounds: int,
    min_page_records: int = MIN_PAGE_HOTELS_BEFORE_STABLE,
    elapsed_seconds: float = 0.0,
    max_page_seconds: int = MAX_LISTING_PAGE_SECONDS,
    min_records_before_time_cap: int = MIN_PAGE_HOTELS_BEFORE_TIME_CAP,
) -> bool:
    if (
        max_page_seconds > 0
        and elapsed_seconds >= max_page_seconds
        and record_count >= min_records_before_time_cap
    ):
        return True
    if unchanged_rounds < stable_rounds:
        return False
    return record_count >= min_page_records or no_scroll_rounds >= stable_rounds


def page_scroll_summary(result: PageCrawlResult) -> Dict:
    return {
        "unique_records": len(result.records),
        "scroll_rounds": result.scroll_rounds,
        "elapsed_seconds": result.elapsed_seconds,
        "selected_scroll_target": result.selected_scroll_target,
        "max_visible_dom_cards": max(
            (item.get("visible_dom_cards", 0) for item in result.scroll_metrics),
            default=result.metrics.dom_card_count,
        ),
        "max_total_unique_collected": max(
            (item.get("total_unique_collected", 0) for item in result.scroll_metrics),
            default=len(result.records),
        ),
    }


def wait_for_listing_growth(
    page: Page,
    card_selector: str,
    page_number: int,
    records_by_key: Dict[str, Dict],
    round_number: int,
    before_total: int,
    before_url_count: int,
    before_dom_count: int,
    timeout_ms: int,
) -> ListingWaitResult:
    started_at = time.perf_counter()
    deadline = started_at + max(0, timeout_ms) / 1000.0
    last_snapshot = None
    updated_existing = False
    grew = False
    waited_for_lazy = False

    while True:
        merge_result = collect_and_merge_listing_snapshot(
            page,
            card_selector,
            page_number,
            records_by_key,
            round_number,
            full_snapshot=False,
        )
        snapshot = merge_result.snapshot
        last_snapshot = snapshot
        updated_existing = merge_result.updated_existing or updated_existing

        total_count = len(records_by_key)
        url_count = records_with_url_count(records_by_key)
        dom_count = snapshot.metrics.dom_card_count
        grew = (
            total_count > before_total
            or url_count > before_url_count
            or dom_count > before_dom_count
        )
        if grew or time.perf_counter() >= deadline:
            break

        remaining_ms = int((deadline - time.perf_counter()) * 1000)
        if remaining_ms <= 0:
            break
        if not waited_for_lazy:
            wait_for_lazy_results(page)
            waited_for_lazy = True
        else:
            page.wait_for_timeout(min(150, remaining_ms))

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    return ListingWaitResult(
        snapshot=last_snapshot,
        updated_existing=updated_existing,
        elapsed_ms=elapsed_ms,
        grew=grew,
    )


def attach_listing_metrics(
    record: Dict,
    page_number: int,
    metrics: ListingCollectionMetrics,
    round_number: int,
) -> None:
    record["_listing_page"] = page_number
    record["_listing_scroll_round"] = round_number
    record["_listing_dom_card_count"] = metrics.dom_card_count
    record["_listing_candidate_records"] = metrics.candidate_records
    record["_listing_embedded_url_count"] = metrics.embedded_url_count
    record["_listing_candidate_url_count"] = metrics.candidate_url_count
    record["_listing_valid_url_count"] = metrics.valid_url_count
    record["_listing_duplicate_url_count"] = metrics.duplicate_url_count
    record["_listing_unique_url_count"] = metrics.unique_canonical_url_count
    record["_listing_unique_record_count"] = metrics.unique_hotel_count
    record["_listing_invalid_card_count"] = metrics.invalid_card_count
    record["_listing_anchorless_card_count"] = metrics.anchorless_card_count
    record["_listing_cards_without_url_count"] = metrics.cards_without_url_count
    record["_listing_cards_without_name_count"] = metrics.cards_without_name_count


def probe_current_page_state(
    page: Page,
    card_selector: str,
    page_number: int,
    scroll_y_after_navigation: int,
    scroll_wait_ms: int,
) -> PaginationState:
    records_by_key: Dict[str, Dict] = {}
    handle_cookie_popup(page)
    page.wait_for_timeout(WAIT_BEFORE_SCRAPE)
    collect_and_merge_listing_snapshot(
        page,
        card_selector,
        page_number,
        records_by_key,
        0,
    )

    scroll_advance = advance_results_scroll(page)
    if scroll_advance.moved:
        page.wait_for_timeout(min(max(0, scroll_wait_ms), 800))
        wait_for_lazy_results(page)
        collect_and_merge_listing_snapshot(
            page,
            card_selector,
            page_number,
            records_by_key,
            0,
        )

    return capture_pagination_state(
        page,
        page_number,
        list(records_by_key.values()),
        scroll_y_after_navigation=scroll_y_after_navigation,
    )
