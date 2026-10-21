from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from agoda_crawler import crawler as crawler_module
from agoda_crawler.crawler import (
    _merge_missing_fields,
    _mark_price_coverage_status,
    _needs_detail_enrichment,
    _is_low_new_record_page,
    _reached_page_limit,
    _should_retry_duplicate_page,
    _validate_supported_occupancy,
    _with_stay_params,
    crawl_agoda_search_with_browser,
)
from agoda_crawler.listing import page_crawl as page_crawl_module
from agoda_crawler.listing.collection import ListingCollectionMetrics
from agoda_crawler.listing.page_crawl import PageCrawlResult
from agoda_crawler.listing.pagination import PaginationState


def test_with_stay_params_adds_dates_and_occupancy() -> None:
    url = _with_stay_params(
        "https://www.agoda.com/vi-vn/demo/hotel/vung-tau-vn.html?cid=-1",
        "2026-06-10",
        "2026-06-12",
    )

    assert "cid=-1" in url
    assert "checkIn=2026-06-10" in url
    assert "checkOut=2026-06-12" in url
    assert "los=2" in url
    assert "rooms=1" in url
    assert "adults=2" in url
    assert "children=0" in url
    assert parse_qs(urlsplit(url).query)["currencyCode"] == ["VND"]


def test_with_stay_params_keeps_custom_occupancy() -> None:
    url = _with_stay_params(
        "https://www.agoda.com/vi-vn/demo/hotel/vung-tau-vn.html?cid=-1",
        "2026-06-10",
        "2026-06-12",
        adults=3,
        rooms=2,
        children=1,
    )

    assert "rooms=2" in url
    assert "adults=3" in url
    assert "children=1" in url


def test_with_stay_params_overrides_foreign_currency() -> None:
    url = _with_stay_params(
        "https://www.agoda.com/demo/hotel/demo.html?currencyCode=USD",
        "2026-06-10",
        "2026-06-12",
    )

    assert parse_qs(urlsplit(url).query)["currencyCode"] == ["VND"]


def test_merge_missing_fields_fills_late_price_data() -> None:
    record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/vung-tau-vn.html",
        "price_value": None,
        "rating_text": "8.7",
    }
    later_record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/vung-tau-vn.html",
        "price_value": "1155203",
        "rating_text": "9.1",
    }

    changed = _merge_missing_fields(record, later_record)

    assert changed is True
    assert record["price_value"] == "1155203"
    assert record["rating_text"] == "8.7"


def test_mark_price_coverage_status_keeps_missing_price_records() -> None:
    records = [
        {"hotel_name": "Priced", "hotel_url": "https://www.agoda.com/a/hotel/x.html", "price_value": "1000"},
        {"hotel_name": "No URL", "hotel_url": None, "price_value": None},
        {
            "hotel_name": "Failed",
            "hotel_url": "https://www.agoda.com/b/hotel/x.html",
            "price_value": None,
            "enrich_status": "failed",
        },
    ]

    _mark_price_coverage_status(records)

    assert records[0]["price_status"] == "present"
    assert records[1]["price_status"] == "missing_no_url"
    assert records[2]["price_status"] == "missing_after_detail_retry"


def test_needs_detail_enrichment_skips_when_only_non_price_field_missing() -> None:
    record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/vung-tau-vn.html",
        "price_value": "1000",
        "rating_text": "8.7",
        "review_count_text": "100 reviews",
        "star_rating_text": "4 stars",
    }

    assert _needs_detail_enrichment(record, enrich_missing_only=True) is False


def test_needs_detail_enrichment_uses_rating_as_required_default() -> None:
    record = {
        "hotel_url": "https://www.agoda.com/demo/hotel/vung-tau-vn.html",
        "price_value": "1000",
        "rating_text": None,
        "review_count_text": "22",
        "star_rating_text": None,
    }

    assert _needs_detail_enrichment(record, enrich_missing_only=True) is True


def test_needs_detail_enrichment_when_price_missing() -> None:
    record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/vung-tau-vn.html",
        "price_value": None,
        "rating_text": "8.7",
        "review_count_text": "100 reviews",
        "star_rating_text": "4 stars",
    }

    assert _needs_detail_enrichment(record, enrich_missing_only=True) is True


def test_needs_detail_enrichment_when_configured_star_rating_missing() -> None:
    record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/vung-tau-vn.html",
        "price_value": "1000",
        "rating_text": "8.7",
        "review_count_text": "100 reviews",
        "star_rating_text": None,
    }

    assert _needs_detail_enrichment(
        record,
        enrich_missing_only=True,
        detail_fields=("price_value", "star_rating_text"),
    ) is True


def test_validate_supported_occupancy_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError, match="adults must be >= 1"):
        _validate_supported_occupancy(0, 1, 0)

    with pytest.raises(ValueError, match="rooms must be >= 1"):
        _validate_supported_occupancy(1, 0, 0)

    with pytest.raises(ValueError, match="children must be >= 0"):
        _validate_supported_occupancy(1, 1, -1)


def test_reached_page_limit_treats_zero_as_all_pages() -> None:
    assert _reached_page_limit(100, 0) is False
    assert _reached_page_limit(1, 2) is False
    assert _reached_page_limit(2, 2) is True


def test_low_new_record_page_uses_strictly_less_than_threshold() -> None:
    assert _is_low_new_record_page(9, threshold=10) is True
    assert _is_low_new_record_page(10, threshold=10) is False


def test_duplicate_pagination_retries_until_last_attempt() -> None:
    assert _should_retry_duplicate_page(1, max_attempts=3) is True
    assert _should_retry_duplicate_page(2, max_attempts=3) is True
    assert _should_retry_duplicate_page(3, max_attempts=3) is False


def test_crawl_scroll_metrics_include_empty_probe_and_rejected_page_attempts(monkeypatch) -> None:
    page = SimpleNamespace(
        evaluate=lambda *_args, **_kwargs: 0,
        wait_for_timeout=lambda *_args, **_kwargs: None,
    )
    context = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    browser = SimpleNamespace(new_context=lambda **_kwargs: context)
    page_results = iter(
        [
            PageCrawlResult(
                records=[],
                metrics=ListingCollectionMetrics(),
                scroll_rounds=2,
                scroll_metrics=[{"moved": True}, {"moved": False}],
                selected_scroll_target="window",
                elapsed_seconds=0.0,
                work_metrics={
                    "regular_snapshot_count": 2,
                    "full_snapshot_count": 1,
                    "dom_call_seconds": 0.1,
                    "embedded_call_seconds": 0.2,
                    "parse_dedupe_seconds": 0.03,
                    "merge_seconds": 0.04,
                    "active_wait_seconds": 0.05,
                    "other_seconds": 0.06,
                },
            ),
            PageCrawlResult(
                records=[],
                metrics=ListingCollectionMetrics(),
                scroll_rounds=4,
                scroll_metrics=[{"moved": True}, {"moved": True}, {"moved": False}],
                selected_scroll_target="window",
                elapsed_seconds=0.0,
                work_metrics={
                    "regular_snapshot_count": 3,
                    "full_snapshot_count": 2,
                    "dom_call_seconds": 0.13,
                    "embedded_call_seconds": 0.14,
                    "parse_dedupe_seconds": 0.15,
                    "merge_seconds": 0.16,
                    "active_wait_seconds": 0.17,
                    "other_seconds": 0.18,
                },
            ),
        ]
    )
    state = PaginationState(
        page_number=1,
        url="https://www.agoda.com/search",
        active_page_text="1",
        scroll_y_after_navigation=0,
        scroll_y_after_crawl=0,
        first_hotel_identity="hotel-a",
        canonical_urls=("hotel-a",),
    )
    evidence = iter(
        [
            {"verified": True, "signs": {}, "sign_count": 0},
            {"verified": False, "signs": {}, "sign_count": 0},
        ]
    )

    def fake_probe(_page, _selector, page_number, **kwargs):
        probe_metrics = kwargs.get("work_metrics_out")
        if probe_metrics is not None:
            probe_metrics.update(
                scroll_rounds_total=0,
                scroll_rounds_max=0,
                scroll_actions=1,
                regular_snapshot_count=1,
                full_snapshot_count=0,
                dom_call_seconds=0.07,
                embedded_call_seconds=0.08,
                parse_dedupe_seconds=0.09,
                merge_seconds=0.1,
                active_wait_seconds=0.11,
                other_seconds=0.12,
            )
        return PaginationState(
            page_number=page_number,
            url=state.url,
            active_page_text=state.active_page_text,
            scroll_y_after_navigation=0,
            scroll_y_after_crawl=0,
            first_hotel_identity=state.first_hotel_identity,
            canonical_urls=state.canonical_urls,
        )

    monkeypatch.setattr(crawler_module, "_browser_context_options", lambda _locale: {})
    monkeypatch.setattr(crawler_module, "apply_resource_blocking", lambda _context: None)
    monkeypatch.setattr(crawler_module, "_navigate_to_results", lambda *_args, **_kwargs: "cards")
    monkeypatch.setattr(
        crawler_module,
        "_crawl_current_results_page",
        lambda *_args, **_kwargs: next(page_results),
    )
    monkeypatch.setattr(crawler_module, "_capture_pagination_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(crawler_module, "_end_of_results_reason", lambda _page: None)
    monkeypatch.setattr(crawler_module, "_go_to_verified_page_start", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(crawler_module, "wait_for_cards", lambda _page: "cards")
    monkeypatch.setattr(crawler_module, "_scroll_y", lambda _page: 0)
    monkeypatch.setattr(crawler_module, "_probe_current_page_state", fake_probe)
    monkeypatch.setattr(
        crawler_module,
        "_pagination_change_evidence",
        lambda *_args, **_kwargs: next(evidence),
    )
    monkeypatch.setattr(crawler_module, "PAGINATION_NAVIGATION_ATTEMPTS", 1)
    monkeypatch.setattr(crawler_module, "_update_page_debug_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        crawler_module,
        "_save_pagination_page_artifacts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(crawler_module, "log", lambda _message: None)

    outcome = {}
    metrics = {}
    crawl_agoda_search_with_browser(
        browser,
        max_pages=2,
        pagination_outcome=outcome,
        metrics_outcome=metrics,
    )

    assert outcome["status"] == "failed"
    assert outcome["page_statuses"]["2"] == "duplicate_page"
    assert set(outcome["page_scroll_summaries"]) == {"1"}
    assert outcome["page_scroll_summaries"]["1"]["scroll_rounds"] == 2
    assert outcome["scroll_rounds_total"] == 6
    assert outcome["scroll_rounds_max"] == 4
    assert outcome["scroll_actions"] == 4
    assert metrics["regular_snapshot_count"] == 6
    assert metrics["full_snapshot_count"] == 3
    assert metrics["dom_call_seconds"] == pytest.approx(0.3)
    assert metrics["embedded_call_seconds"] == pytest.approx(0.42)
    assert metrics["parse_dedupe_seconds"] == pytest.approx(0.27)
    assert metrics["merge_seconds"] == pytest.approx(0.3)
    assert metrics["active_wait_seconds"] == pytest.approx(0.33)
    assert metrics["other_seconds"] == pytest.approx(0.36)
    assert metrics["scroll_rounds_total"] == 6
    assert metrics["scroll_rounds_max"] == 4
    assert metrics["scroll_actions"] == 4
    assert metrics["detail_candidates"] == 0
    assert metrics["detail_attempts"] == 0
    assert metrics["detail_failures"] == 0


def test_crawler_scroll_metrics_survive_probe_failure(monkeypatch):
    page_result = PageCrawlResult(
        records=[],
        metrics=ListingCollectionMetrics(),
        scroll_rounds=2,
        scroll_metrics=[{"moved": True}, {"moved": False}],
        selected_scroll_target="window",
        elapsed_seconds=0.0,
        work_metrics={"regular_snapshot_count": 2},
    )
    state = PaginationState(
        page_number=1,
        url="https://www.agoda.com/search",
        active_page_text="1",
        scroll_y_after_navigation=0,
        scroll_y_after_crawl=0,
        first_hotel_identity=None,
        canonical_urls=(),
    )
    page = SimpleNamespace(
        evaluate=lambda *_args, **_kwargs: 0,
        wait_for_timeout=lambda *_args, **_kwargs: None,
    )
    context = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    browser = SimpleNamespace(new_context=lambda **_kwargs: context)
    monkeypatch.setattr(crawler_module, "_browser_context_options", lambda _locale: {})
    monkeypatch.setattr(crawler_module, "apply_resource_blocking", lambda _context: None)
    monkeypatch.setattr(crawler_module, "_navigate_to_results", lambda *_args, **_kwargs: "cards")
    monkeypatch.setattr(
        crawler_module, "_crawl_current_results_page", lambda *_args, **_kwargs: page_result
    )
    monkeypatch.setattr(crawler_module, "_capture_pagination_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(crawler_module, "_end_of_results_reason", lambda _page: None)
    monkeypatch.setattr(crawler_module, "_go_to_verified_page_start", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(crawler_module, "wait_for_cards", lambda _page: "cards")
    monkeypatch.setattr(crawler_module, "_scroll_y", lambda _page: 0)

    def fail_probe(*_args, **_kwargs):
        raise RuntimeError("probe state capture failed")

    monkeypatch.setattr(crawler_module, "_probe_current_page_state", fail_probe)
    monkeypatch.setattr(crawler_module, "log", lambda _message: None)
    metrics = {}

    with pytest.raises(RuntimeError, match="probe state capture failed"):
        crawl_agoda_search_with_browser(browser, max_pages=2, metrics_outcome=metrics)

    assert metrics["scroll_rounds_total"] == 2
    assert metrics["scroll_rounds_max"] == 2
    assert metrics["scroll_actions"] == 1
    assert metrics["regular_snapshot_count"] == 2


def test_crawler_metrics_include_partial_page_work_on_collection_exception(monkeypatch):
    class Clock:
        def __init__(self):
            self.now = 0.0

        def perf_counter(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(
        crawler_module, "time", SimpleNamespace(perf_counter=clock.perf_counter)
    )
    monkeypatch.setattr(
        page_crawl_module, "time", SimpleNamespace(perf_counter=clock.perf_counter)
    )

    class TimedPage:
        def wait_for_timeout(self, timeout_ms):
            clock.advance(timeout_ms / 1000)

    page = TimedPage()
    context = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    browser = SimpleNamespace(new_context=lambda **_kwargs: context)
    snapshot = page_crawl_module.ListingCollectionSnapshot(
        records=[],
        metrics=ListingCollectionMetrics(dom_card_count=1, unique_hotel_count=0),
    )

    def collect_snapshot(_page, _selector, _page_number, _records, round_number, **_kwargs):
        if round_number == 2:
            raise RuntimeError("round 2 snapshot failed")
        clock.advance(0.12)
        return page_crawl_module.ListingMergeResult(
            snapshot=snapshot,
            updated_existing=False,
            work_metrics={
                "regular_snapshot_count": 1,
                "full_snapshot_count": 1,
                "dom_call_seconds": 0.1,
                "merge_seconds": 0.02,
            },
        )

    def finish_first_wait(*_args, **_kwargs):
        clock.advance(0.03)
        return page_crawl_module.ListingWaitResult(
            snapshot=snapshot,
            updated_existing=False,
            elapsed_ms=30,
            grew=False,
            work_metrics={"active_wait_seconds": 0.03},
        )

    monkeypatch.setattr(crawler_module, "_browser_context_options", lambda _locale: {})
    monkeypatch.setattr(crawler_module, "apply_resource_blocking", lambda _context: None)
    monkeypatch.setattr(crawler_module, "_navigate_to_results", lambda *_args, **_kwargs: "cards")
    monkeypatch.setattr(page_crawl_module, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl_module, "WAIT_BEFORE_SCRAPE", 100)
    monkeypatch.setattr(page_crawl_module, "collect_and_merge_listing_snapshot", collect_snapshot)
    monkeypatch.setattr(
        page_crawl_module,
        "advance_results_scroll",
        lambda _page: SimpleNamespace(
            moved=True,
            target="window",
            scroll_y=600,
            scroll_height=2000,
            client_height=800,
        ),
    )
    monkeypatch.setattr(page_crawl_module, "wait_for_listing_growth", finish_first_wait)
    monkeypatch.setattr(crawler_module, "log", lambda _message: None)
    metrics = {}

    with pytest.raises(RuntimeError, match="round 2 snapshot failed"):
        crawl_agoda_search_with_browser(
            browser,
            max_pages=1,
            max_scroll_rounds=3,
            stable_rounds=3,
            scroll_wait_ms=30,
            metrics_outcome=metrics,
        )

    assert metrics["regular_snapshot_count"] == 1
    assert metrics["full_snapshot_count"] == 1
    assert metrics["dom_call_seconds"] == pytest.approx(0.1)
    assert metrics["merge_seconds"] == pytest.approx(0.02)
    assert metrics["active_wait_seconds"] == pytest.approx(0.23)
    assert metrics["scroll_rounds_total"] == 2
    assert metrics["scroll_rounds_max"] == 2
    assert metrics["scroll_actions"] == 1


def test_first_page_metrics_survive_initial_pagination_capture_failure(monkeypatch):
    page_result = PageCrawlResult(
        records=[],
        metrics=ListingCollectionMetrics(),
        scroll_rounds=3,
        scroll_metrics=[],
        selected_scroll_target="window",
        elapsed_seconds=0.0,
        work_metrics={"scroll_actions": 2},
    )
    page = SimpleNamespace()
    context = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    browser = SimpleNamespace(new_context=lambda **_kwargs: context)

    monkeypatch.setattr(crawler_module, "_browser_context_options", lambda _locale: {})
    monkeypatch.setattr(crawler_module, "apply_resource_blocking", lambda _context: None)
    monkeypatch.setattr(
        crawler_module, "_navigate_to_results", lambda *_args, **_kwargs: "cards"
    )
    monkeypatch.setattr(
        crawler_module,
        "_crawl_current_results_page",
        lambda *_args, **_kwargs: page_result,
    )

    def fail_capture(*_args, **_kwargs):
        raise RuntimeError("initial pagination state failed")

    monkeypatch.setattr(crawler_module, "_capture_pagination_state", fail_capture)
    monkeypatch.setattr(crawler_module, "log", lambda _message: None)
    metrics = {}

    with pytest.raises(RuntimeError, match="initial pagination state failed"):
        crawl_agoda_search_with_browser(
            browser,
            max_pages=1,
            metrics_outcome=metrics,
        )

    assert metrics["scroll_rounds_total"] == 3
    assert metrics["scroll_rounds_max"] == 3
    assert metrics["scroll_actions"] == 2


def test_probe_work_metrics_survive_pagination_state_failure(monkeypatch):
    state = PaginationState(
        page_number=1,
        url="https://www.agoda.com/search",
        active_page_text="1",
        scroll_y_after_navigation=0,
        scroll_y_after_crawl=0,
        first_hotel_identity=None,
        canonical_urls=(),
    )
    page_result = PageCrawlResult(
        records=[],
        metrics=ListingCollectionMetrics(),
        scroll_rounds=1,
        scroll_metrics=[{"moved": True}],
        selected_scroll_target="window",
        elapsed_seconds=0.0,
        work_metrics={"regular_snapshot_count": 1, "dom_call_seconds": 0.05},
    )
    page = SimpleNamespace(
        evaluate=lambda *_args, **_kwargs: 0,
        wait_for_timeout=lambda *_args, **_kwargs: None,
    )
    context = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    browser = SimpleNamespace(new_context=lambda **_kwargs: context)
    snapshot_calls = []

    def collect_probe_snapshot(*_args, **_kwargs):
        snapshot_calls.append(True)
        return SimpleNamespace(
            work_metrics={"regular_snapshot_count": 1, "dom_call_seconds": 0.1}
        )

    def fail_state_capture(*_args, **_kwargs):
        raise RuntimeError("probe state capture failed")

    monkeypatch.setattr(crawler_module, "_browser_context_options", lambda _locale: {})
    monkeypatch.setattr(crawler_module, "apply_resource_blocking", lambda _context: None)
    monkeypatch.setattr(crawler_module, "_navigate_to_results", lambda *_args, **_kwargs: "cards")
    monkeypatch.setattr(
        crawler_module, "_crawl_current_results_page", lambda *_args, **_kwargs: page_result
    )
    monkeypatch.setattr(crawler_module, "_capture_pagination_state", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(crawler_module, "_end_of_results_reason", lambda _page: None)
    monkeypatch.setattr(crawler_module, "_go_to_verified_page_start", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(crawler_module, "wait_for_cards", lambda _page: "cards")
    monkeypatch.setattr(crawler_module, "_scroll_y", lambda _page: 0)
    monkeypatch.setattr(page_crawl_module, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl_module, "WAIT_BEFORE_SCRAPE", 0)
    monkeypatch.setattr(
        page_crawl_module, "collect_and_merge_listing_snapshot", collect_probe_snapshot
    )
    monkeypatch.setattr(
        page_crawl_module,
        "advance_results_scroll",
        lambda _page: SimpleNamespace(moved=True),
    )
    monkeypatch.setattr(page_crawl_module, "wait_for_lazy_results", lambda _page: None)
    monkeypatch.setattr(page_crawl_module, "capture_pagination_state", fail_state_capture)
    monkeypatch.setattr(crawler_module, "log", lambda _message: None)
    metrics = {}

    with pytest.raises(RuntimeError, match="probe state capture failed"):
        crawl_agoda_search_with_browser(browser, max_pages=2, metrics_outcome=metrics)

    assert len(snapshot_calls) == 2
    assert metrics["regular_snapshot_count"] == 3
    assert metrics["dom_call_seconds"] == pytest.approx(0.25)
    assert metrics["scroll_actions"] == 2


def test_standalone_metrics_survive_browser_launch_failure(monkeypatch):
    clock = SimpleNamespace(now=0.0)

    def perf_counter():
        return clock.now

    def self_launch(**_kwargs):
        clock.now += 0.4
        raise RuntimeError("browser launch failed")

    class Playwright:
        chromium = SimpleNamespace(launch=self_launch)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(crawler_module, "time", SimpleNamespace(perf_counter=perf_counter))
    monkeypatch.setattr(crawler_module, "sync_playwright", Playwright)
    metrics = {}

    with pytest.raises(RuntimeError, match="browser launch failed"):
        crawler_module.crawl_agoda_search(metrics_outcome=metrics)

    assert metrics["job_wall_seconds"] == pytest.approx(0.4)
    assert metrics["search_wall_seconds"] == 0.0
    assert metrics["listing_wall_seconds"] == 0.0
    assert metrics["detail_wall_seconds"] == 0.0
    assert metrics["detail_attempts"] == 0


def test_crawler_metrics_survive_navigation_and_context_close_failures(monkeypatch):
    class Clock:
        def __init__(self):
            self.now = 0.0

        def perf_counter(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(
        crawler_module, "time", SimpleNamespace(perf_counter=clock.perf_counter)
    )
    page = SimpleNamespace()

    class Context:
        def new_page(self):
            return page

        def close(self):
            clock.advance(0.25)
            raise RuntimeError("context close failed")

    class Browser:
        def new_context(self, **_kwargs):
            return Context()

    monkeypatch.setattr(crawler_module, "_browser_context_options", lambda _locale: {})
    monkeypatch.setattr(crawler_module, "apply_resource_blocking", lambda _context: None)

    def fail_navigation(*_args, **_kwargs):
        clock.advance(0.375)
        raise RuntimeError("navigation failed")

    monkeypatch.setattr(crawler_module, "_navigate_to_results", fail_navigation)
    monkeypatch.setattr(crawler_module, "log", lambda _message: None)
    metrics = {}

    with pytest.raises(RuntimeError, match="navigation failed"):
        crawl_agoda_search_with_browser(Browser(), metrics_outcome=metrics)

    assert metrics["search_wall_seconds"] == 0.375
    assert metrics["listing_wall_seconds"] == 0.0
    assert metrics["detail_wall_seconds"] == 0.0
    assert metrics["job_wall_seconds"] == 0.625


def test_probe_reports_snapshot_work_and_active_wait_metrics(monkeypatch) -> None:
    class Clock:
        def __init__(self):
            self.now = 0.0

        def perf_counter(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(
        page_crawl_module, "time", SimpleNamespace(perf_counter=clock.perf_counter)
    )
    monkeypatch.setattr(page_crawl_module, "WAIT_BEFORE_SCRAPE", 100)
    snapshots = iter(
        [
            {
                "regular_snapshot_count": 1,
                "full_snapshot_count": 0,
                "dom_call_seconds": 0.01,
                "embedded_call_seconds": 0.02,
                "parse_dedupe_seconds": 0.03,
                "merge_seconds": 0.04,
            },
            {
                "regular_snapshot_count": 0,
                "full_snapshot_count": 1,
                "dom_call_seconds": 0.05,
                "embedded_call_seconds": 0.06,
                "parse_dedupe_seconds": 0.07,
                "merge_seconds": 0.08,
            },
        ]
    )

    def collect_snapshot(*_args, **_kwargs):
        metrics = next(snapshots)
        clock.advance(
            sum(
                metrics[key]
                for key in (
                    "dom_call_seconds",
                    "embedded_call_seconds",
                    "parse_dedupe_seconds",
                    "merge_seconds",
                )
            )
        )
        return SimpleNamespace(work_metrics=metrics)

    monkeypatch.setattr(page_crawl_module, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(
        page_crawl_module,
        "collect_and_merge_listing_snapshot",
        collect_snapshot,
    )
    monkeypatch.setattr(
        page_crawl_module,
        "advance_results_scroll",
        lambda _page: SimpleNamespace(moved=True),
    )
    monkeypatch.setattr(
        page_crawl_module,
        "wait_for_lazy_results",
        lambda _page: clock.advance(0.03),
    )
    state = PaginationState(
        page_number=2,
        url="https://www.agoda.com/search?page=2",
        active_page_text="2",
        scroll_y_after_navigation=0,
        scroll_y_after_crawl=100,
        first_hotel_identity=None,
        canonical_urls=(),
    )
    monkeypatch.setattr(
        page_crawl_module, "capture_pagination_state", lambda *_args, **_kwargs: state
    )
    page = SimpleNamespace(
        wait_for_timeout=lambda milliseconds: clock.advance(milliseconds / 1000)
    )
    metrics = {}

    result = page_crawl_module.probe_current_page_state(
        page,
        "cards",
        2,
        scroll_y_after_navigation=0,
        scroll_wait_ms=200,
        work_metrics_out=metrics,
    )

    assert result is state
    assert metrics["regular_snapshot_count"] == 1
    assert metrics["full_snapshot_count"] == 1
    assert metrics["dom_call_seconds"] == pytest.approx(0.06)
    assert metrics["embedded_call_seconds"] == pytest.approx(0.08)
    assert metrics["parse_dedupe_seconds"] == pytest.approx(0.1)
    assert metrics["merge_seconds"] == pytest.approx(0.12)
    assert metrics["active_wait_seconds"] == pytest.approx(0.33)
    assert metrics["other_seconds"] == pytest.approx(0.0)
    assert metrics["scroll_rounds_total"] == 0
    assert metrics["scroll_rounds_max"] == 0
    assert metrics["scroll_actions"] == 1
