import time

import pytest

from agoda_crawler.listing import page_crawl
from agoda_crawler.listing.collection import (
    ListingCollectionMetrics,
    ListingCollectionSnapshot,
)
from agoda_crawler.listing.page_crawl import PageCrawlResult
from agoda_crawler.listing.scrolling import ScrollAdvance
from agoda_crawler.listing.records import merge_page_record


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def perf_counter(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakePage:
    def wait_for_timeout(self, _timeout_ms: int) -> None:
        return None


class _EmbeddedIdentityPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *_args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return [
                {
                    "urls": [
                        "https://www.agoda.com/vi-vn/shared/hotel/listing.html?propertyId=123"
                    ],
                    "name": "",
                    "text": "",
                    "dataSelenium": "embedded-state",
                }
            ]
        return []


def test_page_snapshot_passes_accumulated_card_membership_to_embedded_scan() -> None:
    records_by_key = {}
    merge_page_record(
        records_by_key,
        {
            "hotel_name": "Card Hotel",
            "hotel_url": None,
            "listing_property_id": "123",
            "price_value": "500000",
        },
    )

    page_crawl.collect_and_merge_listing_snapshot(
        _EmbeddedIdentityPage(),
        '[data-selenium="hotel-item"]',
        1,
        records_by_key,
        round_number=2,
        full_snapshot=True,
    )

    assert len(records_by_key) == 1
    record = next(iter(records_by_key.values()))
    assert record["hotel_name"] == "Card Hotel"
    assert record["hotel_url"] == (
        "https://www.agoda.com/vi-vn/shared/hotel/listing.html?propertyId=123"
    )
    assert record["price_value"] == "500000"


class _MembershipSequencePage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def __init__(self, cards_by_snapshot, embedded_urls) -> None:
        self.cards_by_snapshot = cards_by_snapshot
        self.embedded_urls = embedded_urls
        self.snapshot_index = 0

    def wait_for_timeout(self, _timeout_ms: int) -> None:
        return None

    def evaluate(self, script: str, *_args):
        if "scrollY" in script:
            self.snapshot_index += 1
            return 0
        if "document.documentElement" in script:
            return [
                {
                    "urls": [url],
                    "name": "",
                    "text": "",
                    "dataSelenium": "embedded-state",
                }
                for url in self.embedded_urls
            ]
        if "excludedContextSelector" in script:
            index = min(self.snapshot_index, len(self.cards_by_snapshot) - 1)
            return self.cards_by_snapshot[index]
        return []


def test_page_membership_counts_unique_unmatched_and_bounds_samples(monkeypatch) -> None:
    embedded_urls = [
        "https://www.agoda.com/vi-vn/shared/hotel/listing.html?propertyId="
        f"{property_id}"
        for property_id in range(1, 31)
    ]
    partial_card = {
        "urls": [],
        "name": "Observed Hotel",
        "text": "Observed Hotel",
        "propertyId": "1",
        "dataSelenium": "hotel-item",
        "sourceSelector": '[data-selenium="hotel-item"]',
    }
    page = _MembershipSequencePage([[], [partial_card]], embedded_urls)
    saved_diagnostics = []
    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "MIN_PAGE_HOTELS_BEFORE_FALLBACK", 0)
    monkeypatch.setattr(
        page_crawl,
        "save_membership_diagnostics",
        lambda _page_number, diagnostics, **_kwargs: saved_diagnostics.append(diagnostics),
        raising=False,
    )

    result = page_crawl.crawl_current_results_page(
        page,
        '[data-selenium="hotel-item"]',
        page_number=1,
        max_rounds=1,
    )
    summary = page_crawl.page_scroll_summary(result)

    assert len(result.records) == 1
    assert result.records[0]["hotel_url"].endswith("propertyId=1")
    assert summary["embedded_candidates_seen"] == 60
    assert summary["embedded_nonmember_unique"] == 30
    assert summary["embedded_unmatched_at_end"] == 29
    assert len(saved_diagnostics) == 1
    assert len(saved_diagnostics[0]["sample_urls"]) == 25
    assert all(len(url) <= 500 for url in saved_diagnostics[0]["sample_urls"])


def test_probe_membership_rejects_recommendation_and_footer_links(monkeypatch) -> None:
    page = _MembershipSequencePage(
        [
            [
                {
                    "urls": [
                        "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html"
                    ],
                    "name": "Card Hotel",
                    "text": "Card Hotel 500000 VND",
                    "propertyId": "111",
                    "dataSelenium": "hotel-item",
                    "sourceSelector": '[data-selenium="hotel-item"]',
                }
            ]
        ],
        [
            "https://www.agoda.com/vi-vn/recommended/hotel/vung-tau-vn.html?propertyId=222",
            "https://www.agoda.com/vi-vn/footer/hotel/vung-tau-vn.html?propertyId=333",
        ],
    )
    captured_records = []
    saved_diagnostics = []
    work_metrics = {}

    def capture(_page, _page_number, records, **_kwargs):
        captured_records.extend(records)
        return "pagination-state"

    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(
        page_crawl,
        "advance_results_scroll",
        lambda _page: ScrollAdvance(False, "window", 0, 1000, 800),
    )
    monkeypatch.setattr(page_crawl, "capture_pagination_state", capture)
    monkeypatch.setattr(
        page_crawl,
        "save_membership_diagnostics",
        lambda _page_number, diagnostics, **_kwargs: saved_diagnostics.append(diagnostics),
        raising=False,
    )

    state = page_crawl.probe_current_page_state(
        page,
        '[data-selenium="hotel-item"]',
        page_number=2,
        scroll_y_after_navigation=0,
        scroll_wait_ms=0,
        work_metrics_out=work_metrics,
    )

    assert state == "pagination-state"
    assert [record["hotel_name"] for record in captured_records] == ["Card Hotel"]
    assert work_metrics["embedded_candidates_seen"] == 2
    assert work_metrics["embedded_nonmember_unique"] == 2
    assert work_metrics["embedded_unmatched_at_end"] == 2
    assert saved_diagnostics[0]["sample_urls"] == [
        "https://www.agoda.com/vi-vn/recommended/hotel/vung-tau-vn.html?propertyId=222",
        "https://www.agoda.com/vi-vn/footer/hotel/vung-tau-vn.html?propertyId=333",
    ]


def test_page_fallback_card_resolves_pending_embedded_membership(monkeypatch) -> None:
    url = "https://www.agoda.com/vi-vn/shared/hotel/listing.html?propertyId=444"
    page = _MembershipSequencePage([[]], [url])
    saved_diagnostics = []
    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(
        page_crawl,
        "extract_page_results",
        lambda *_args, **_kwargs: [
            {
                "hotel_name": "Late Card Hotel",
                "hotel_url": None,
                "listing_property_id": "444",
            }
        ],
    )
    monkeypatch.setattr(
        page_crawl,
        "save_membership_diagnostics",
        lambda _page_number, diagnostics, **_kwargs: saved_diagnostics.append(diagnostics),
        raising=False,
    )

    result = page_crawl.crawl_current_results_page(
        page,
        '[data-selenium="hotel-item"]',
        page_number=1,
        max_rounds=1,
    )

    assert len(result.records) == 1
    assert page_crawl.page_scroll_summary(result)["embedded_nonmember_unique"] == 1
    assert page_crawl.page_scroll_summary(result)["embedded_unmatched_at_end"] == 0
    assert saved_diagnostics[0]["sample_urls"] == [url]


def test_membership_counts_normalize_tracking_aliases_and_reset_each_crawl(
    monkeypatch,
) -> None:
    page = _MembershipSequencePage(
        [[]],
        [
            "https://www.agoda.com/vi-vn/shared/hotel/listing.html"
            "?propertyId=555&cid=first",
            "https://www.agoda.com/vi-vn/shared/hotel/listing.html"
            "?propertyId=555&cid=second",
        ],
    )
    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "MIN_PAGE_HOTELS_BEFORE_FALLBACK", 0)
    monkeypatch.setattr(
        page_crawl,
        "save_membership_diagnostics",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    first = page_crawl.crawl_current_results_page(
        page,
        '[data-selenium="hotel-item"]',
        page_number=1,
        max_rounds=1,
    )
    second = page_crawl.crawl_current_results_page(
        page,
        '[data-selenium="hotel-item"]',
        page_number=1,
        max_rounds=1,
    )

    first_summary = page_crawl.page_scroll_summary(first)
    second_summary = page_crawl.page_scroll_summary(second)
    assert first_summary["embedded_candidates_seen"] == 4
    assert first_summary["embedded_nonmember_unique"] == 1
    assert first_summary["embedded_unmatched_at_end"] == 1
    assert {
        key: second_summary[key]
        for key in (
            "embedded_candidates_seen",
            "embedded_nonmember_unique",
            "embedded_unmatched_at_end",
        )
    } == {
        key: first_summary[key]
        for key in (
            "embedded_candidates_seen",
            "embedded_nonmember_unique",
            "embedded_unmatched_at_end",
        )
    }


def test_membership_writer_failure_keeps_successful_page_results_and_counters(
    monkeypatch,
) -> None:
    record = {
        "hotel_name": "Visible Hotel",
        "hotel_url": "https://www.agoda.com/vi-vn/visible/hotel/vung-tau.html",
    }
    snapshot = ListingCollectionSnapshot(
        records=[record],
        metrics=ListingCollectionMetrics(embedded_candidates_seen=1),
        embedded_nonmember_records=[
            {
                "hotel_url": "https://www.agoda.com/vi-vn/unmatched/hotel/vung-tau.html",
                "canonical_url": "https://www.agoda.com/vi-vn/unmatched/hotel/vung-tau.html",
                "listing_property_id": None,
            }
        ],
    )
    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "MIN_PAGE_HOTELS_BEFORE_FALLBACK", 0)
    monkeypatch.setattr(
        page_crawl,
        "collect_listing_snapshot",
        lambda *_args, **_kwargs: snapshot,
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("diagnostics volume unavailable")

    monkeypatch.setattr(page_crawl, "save_membership_diagnostics", fail_write, raising=False)

    result = page_crawl.crawl_current_results_page(
        _FakePage(),
        "cards",
        page_number=1,
        max_rounds=1,
    )

    summary = page_crawl.page_scroll_summary(result)
    assert len(result.records) == 1
    assert result.records[0]["hotel_name"] == "Visible Hotel"
    assert summary["embedded_candidates_seen"] == 2
    assert summary["embedded_nonmember_unique"] == 1
    assert summary["embedded_unmatched_at_end"] == 1


def test_membership_writer_failure_does_not_mask_page_exception(monkeypatch) -> None:
    record = {
        "hotel_name": "Visible Hotel",
        "hotel_url": "https://www.agoda.com/vi-vn/visible/hotel/vung-tau.html",
    }
    snapshot = ListingCollectionSnapshot(
        records=[record],
        metrics=ListingCollectionMetrics(embedded_candidates_seen=1),
        embedded_nonmember_records=[
            {
                "hotel_url": "https://www.agoda.com/vi-vn/unmatched/hotel/vung-tau.html",
                "canonical_url": "https://www.agoda.com/vi-vn/unmatched/hotel/vung-tau.html",
                "listing_property_id": None,
            }
        ],
    )
    collect_calls = 0

    def collect_snapshot(*_args, **_kwargs):
        nonlocal collect_calls
        collect_calls += 1
        if collect_calls == 1:
            return snapshot
        raise RuntimeError("final snapshot failed")

    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "collect_listing_snapshot", collect_snapshot)
    def fail_write(*_args, **_kwargs):
        raise OSError("diagnostics unavailable")

    monkeypatch.setattr(page_crawl, "save_membership_diagnostics", fail_write, raising=False)
    work_metrics = {}

    with pytest.raises(RuntimeError, match="final snapshot failed"):
        page_crawl.crawl_current_results_page(
            _FakePage(),
            "cards",
            page_number=1,
            max_rounds=1,
            work_metrics_out=work_metrics,
        )

    assert work_metrics["embedded_candidates_seen"] == 1
    assert work_metrics["embedded_nonmember_unique"] == 1
    assert work_metrics["embedded_unmatched_at_end"] == 1


def test_crawl_current_results_page_honors_scroll_wait_ms(monkeypatch) -> None:
    captured_timeouts = []

    def fake_snapshot(_page, _card_selector, _page_number, **_kwargs):
        return ListingCollectionSnapshot(
            records=[
                {
                    "hotel_name": "Hotel A",
                    "hotel_url": "https://www.agoda.com/a/hotel/a.html",
                }
            ],
            metrics=ListingCollectionMetrics(dom_card_count=1, unique_hotel_count=1),
        )

    def fake_wait_for_listing_growth(*args, **kwargs):
        captured_timeouts.append(kwargs["timeout_ms"])
        return page_crawl.ListingWaitResult(
            snapshot=fake_snapshot(None, "", 1),
            updated_existing=False,
            elapsed_ms=kwargs["timeout_ms"],
            grew=False,
        )

    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "collect_listing_snapshot", fake_snapshot)
    monkeypatch.setattr(page_crawl, "MIN_PAGE_HOTELS_BEFORE_STABLE", 1)
    monkeypatch.setattr(page_crawl, "MIN_PAGE_HOTELS_BEFORE_FALLBACK", 1)
    monkeypatch.setattr(
        page_crawl,
        "advance_results_scroll",
        lambda _page: ScrollAdvance(True, "window", 600, 2000, 800),
    )
    monkeypatch.setattr(
        page_crawl,
        "wait_for_listing_growth",
        fake_wait_for_listing_growth,
    )
    page_crawl.crawl_current_results_page(
        _FakePage(),
        '[data-selenium="hotel-item"]',
        page_number=1,
        max_rounds=2,
        stable_rounds=2,
        scroll_wait_ms=600,
    )

    assert captured_timeouts == [600]


def test_page_work_metrics_separate_snapshots_from_active_wait(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(time, "perf_counter", clock.perf_counter)

    class _TimedPage:
        def wait_for_timeout(self, timeout_ms: int) -> None:
            clock.advance(timeout_ms / 1000)

    def fake_snapshot(_page, _card_selector, _page_number, **kwargs):
        is_full = kwargs.get("include_embedded", True) and kwargs.get(
            "include_broad_selectors", True
        )
        dom_seconds = 0.003
        embedded_seconds = 0.002 if is_full else 0.0
        parse_seconds = 0.0007
        snapshot_merge_seconds = 0.0004
        clock.advance(
            dom_seconds
            + embedded_seconds
            + parse_seconds
            + snapshot_merge_seconds
        )
        return ListingCollectionSnapshot(
            records=[
                {
                    "hotel_name": "Hotel A",
                    "hotel_url": "https://www.agoda.com/a/hotel/a.html",
                }
            ],
            metrics=ListingCollectionMetrics(
                dom_card_count=1,
                unique_hotel_count=1,
                regular_snapshot_count=int(not is_full),
                full_snapshot_count=int(is_full),
                dom_call_seconds=dom_seconds,
                embedded_call_seconds=embedded_seconds,
                parse_dedupe_seconds=parse_seconds,
                merge_seconds=snapshot_merge_seconds,
            ),
        )

    original_merge = page_crawl.merge_page_record

    def timed_merge(*args, **kwargs):
        clock.advance(0.001)
        return original_merge(*args, **kwargs)

    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "collect_listing_snapshot", fake_snapshot)
    monkeypatch.setattr(page_crawl, "merge_page_record", timed_merge)
    monkeypatch.setattr(page_crawl, "LISTING_FULL_SNAPSHOT_INTERVAL", 5)
    monkeypatch.setattr(page_crawl, "WAIT_BEFORE_SCRAPE", 3)
    monkeypatch.setattr(page_crawl, "MIN_PAGE_HOTELS_BEFORE_STABLE", 1)
    monkeypatch.setattr(page_crawl, "MIN_PAGE_HOTELS_BEFORE_FALLBACK", 1)
    monkeypatch.setattr(
        page_crawl,
        "advance_results_scroll",
        lambda _page: ScrollAdvance(True, "window", 600, 2000, 800),
    )
    monkeypatch.setattr(
        page_crawl,
        "wait_for_lazy_results",
        lambda _page: clock.advance(0.004),
    )

    result = page_crawl.crawl_current_results_page(
        _TimedPage(),
        '[data-selenium="hotel-item"]',
        page_number=1,
        max_rounds=2,
        stable_rounds=2,
        scroll_wait_ms=20,
    )

    assert result.work_metrics["full_snapshot_count"] == 2
    assert result.work_metrics["regular_snapshot_count"] == 4
    assert result.work_metrics["dom_call_seconds"] == pytest.approx(0.018)
    assert result.work_metrics["embedded_call_seconds"] == pytest.approx(0.004)
    assert result.work_metrics["parse_dedupe_seconds"] == pytest.approx(0.0042)
    assert result.work_metrics["merge_seconds"] == pytest.approx(0.0084)
    assert result.work_metrics["active_wait_seconds"] == pytest.approx(0.015)
    assert result.work_metrics["active_wait_seconds"] < (
        result.scroll_metrics[0]["wait_ms"] / 1000
    )
    assert result.work_metrics["other_seconds"] == pytest.approx(0.0)


def test_failed_page_crawl_publishes_partial_metrics_after_round_failure(
    monkeypatch,
) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(page_crawl.time, "perf_counter", clock.perf_counter)

    class _TimedPage:
        def wait_for_timeout(self, timeout_ms: int) -> None:
            clock.advance(timeout_ms / 1000)

    snapshot = ListingCollectionSnapshot(
        records=[],
        metrics=ListingCollectionMetrics(dom_card_count=1, unique_hotel_count=0),
    )

    def collect_snapshot(_page, _selector, _page_number, _records, round_number, **_kwargs):
        if round_number == 2:
            raise RuntimeError("round 2 snapshot failed")
        clock.advance(0.12)
        return page_crawl.ListingMergeResult(
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
        return page_crawl.ListingWaitResult(
            snapshot=snapshot,
            updated_existing=False,
            elapsed_ms=30,
            grew=False,
            work_metrics={"active_wait_seconds": 0.03},
        )

    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "WAIT_BEFORE_SCRAPE", 100)
    monkeypatch.setattr(page_crawl, "collect_and_merge_listing_snapshot", collect_snapshot)
    monkeypatch.setattr(
        page_crawl,
        "advance_results_scroll",
        lambda _page: ScrollAdvance(True, "window", 600, 2000, 800),
    )
    monkeypatch.setattr(page_crawl, "wait_for_listing_growth", finish_first_wait)
    partial_metrics = {}

    with pytest.raises(RuntimeError, match="round 2 snapshot failed"):
        page_crawl.crawl_current_results_page(
            _TimedPage(),
            "cards",
            page_number=1,
            max_rounds=3,
            stable_rounds=3,
            scroll_wait_ms=30,
            work_metrics_out=partial_metrics,
        )

    assert partial_metrics["regular_snapshot_count"] == 1
    assert partial_metrics["full_snapshot_count"] == 1
    assert partial_metrics["dom_call_seconds"] == pytest.approx(0.1)
    assert partial_metrics["merge_seconds"] == pytest.approx(0.02)
    assert partial_metrics["active_wait_seconds"] == pytest.approx(0.23)
    assert partial_metrics["scroll_rounds_total"] == 2
    assert partial_metrics["scroll_rounds_max"] == 2
    assert partial_metrics["scroll_actions"] == 1
    assert partial_metrics["other_seconds"] == pytest.approx(0.0)


def test_failed_final_snapshot_publishes_partial_page_metrics(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(page_crawl.time, "perf_counter", clock.perf_counter)

    class _TimedPage:
        def wait_for_timeout(self, timeout_ms: int) -> None:
            clock.advance(timeout_ms / 1000)

    snapshot = ListingCollectionSnapshot(
        records=[],
        metrics=ListingCollectionMetrics(dom_card_count=1, unique_hotel_count=0),
    )
    calls = 0

    def collect_snapshot(_page, _selector, _page_number, _records, _round_number, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            clock.advance(0.05)
            raise RuntimeError("final snapshot failed")
        clock.advance(0.12)
        return page_crawl.ListingMergeResult(
            snapshot=snapshot,
            updated_existing=False,
            work_metrics={
                "regular_snapshot_count": 1,
                "full_snapshot_count": 1,
                "dom_call_seconds": 0.1,
                "merge_seconds": 0.02,
            },
        )

    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "WAIT_BEFORE_SCRAPE", 100)
    monkeypatch.setattr(page_crawl, "collect_and_merge_listing_snapshot", collect_snapshot)
    partial_metrics = {}

    with pytest.raises(RuntimeError, match="final snapshot failed"):
        page_crawl.crawl_current_results_page(
            _TimedPage(),
            "cards",
            page_number=1,
            max_rounds=1,
            work_metrics_out=partial_metrics,
        )

    assert calls == 2
    assert partial_metrics["regular_snapshot_count"] == 1
    assert partial_metrics["full_snapshot_count"] == 1
    assert partial_metrics["dom_call_seconds"] == pytest.approx(0.1)
    assert partial_metrics["active_wait_seconds"] == pytest.approx(0.1)
    assert partial_metrics["scroll_rounds_total"] == 1
    assert partial_metrics["scroll_actions"] == 0
    assert partial_metrics["other_seconds"] == pytest.approx(0.05)


def test_scroll_metrics_aggregate_total_max_and_empty_probe_rejected_actions() -> None:
    from agoda_crawler.utils.crawl_metrics import aggregate_scroll_metrics

    def page_result(rounds: int, moved: list[bool], records: list[dict]):
        return PageCrawlResult(
            records=records,
            metrics=ListingCollectionMetrics(),
            scroll_rounds=rounds,
            scroll_metrics=[{"moved": value} for value in moved],
            selected_scroll_target="window",
            elapsed_seconds=0.0,
        )

    first_page = page_result(2, [True, False], [{"hotel_name": "Hotel A"}])
    empty_page = page_result(1, [], [])
    rejected_page_attempt = page_result(
        4,
        [True, True, False],
        [{"hotel_name": "Hotel A"}],
    )
    probe_work = {"scroll_rounds_total": 0, "scroll_rounds_max": 0, "scroll_actions": 1}

    totals = aggregate_scroll_metrics(
        [
            page_crawl.page_scroll_summary(first_page),
            page_crawl.page_scroll_summary(empty_page),
            page_crawl.page_scroll_summary(rejected_page_attempt),
            probe_work,
        ]
    )

    assert totals == {
        "scroll_rounds_total": 7,
        "scroll_rounds_max": 4,
        "scroll_actions": 4,
    }
    assert totals["scroll_rounds_total"] != totals["scroll_rounds_max"]


@pytest.mark.parametrize(
    ("moved", "expected_snapshot_calls", "expected_actions"),
    [(True, 2, 1), (False, 1, 0)],
)
def test_probe_scroll_metrics_count_only_successful_scroll_actions(
    monkeypatch,
    moved: bool,
    expected_snapshot_calls: int,
    expected_actions: int,
) -> None:
    snapshot_calls = []
    probe_state = object()
    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "WAIT_BEFORE_SCRAPE", 0)
    monkeypatch.setattr(
        page_crawl,
        "collect_and_merge_listing_snapshot",
        lambda *_args, **_kwargs: snapshot_calls.append(True),
    )
    monkeypatch.setattr(
        page_crawl,
        "advance_results_scroll",
        lambda _page: ScrollAdvance(moved, "window", 600, 2000, 800),
    )
    monkeypatch.setattr(page_crawl, "wait_for_lazy_results", lambda _page: None)
    monkeypatch.setattr(page_crawl, "capture_pagination_state", lambda *_args, **_kwargs: probe_state)

    work_metrics = {}
    result = page_crawl.probe_current_page_state(
        _FakePage(),
        "cards",
        page_number=2,
        scroll_y_after_navigation=0,
        scroll_wait_ms=100,
        work_metrics_out=work_metrics,
    )

    assert result is probe_state
    assert len(snapshot_calls) == expected_snapshot_calls
    assert work_metrics["scroll_rounds_total"] == 0
    assert work_metrics["scroll_rounds_max"] == 0
    assert work_metrics["scroll_actions"] == expected_actions
    assert work_metrics["regular_snapshot_count"] == 0
    assert work_metrics["full_snapshot_count"] == 0
    assert work_metrics["active_wait_seconds"] >= 0
    assert work_metrics["other_seconds"] >= 0


def test_probe_preserves_wait_metrics_when_first_snapshot_fails(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(page_crawl.time, "perf_counter", clock.perf_counter)

    class _TimedPage:
        def wait_for_timeout(self, timeout_ms: int) -> None:
            clock.advance(timeout_ms / 1000)

    def fail_snapshot(*_args, **_kwargs):
        raise RuntimeError("initial probe snapshot failed")

    monkeypatch.setattr(page_crawl, "handle_cookie_popup", lambda _page: None)
    monkeypatch.setattr(page_crawl, "WAIT_BEFORE_SCRAPE", 100)
    monkeypatch.setattr(page_crawl, "collect_and_merge_listing_snapshot", fail_snapshot)
    work_metrics = {}

    with pytest.raises(RuntimeError, match="initial probe snapshot failed"):
        page_crawl.probe_current_page_state(
            _TimedPage(),
            "cards",
            page_number=2,
            scroll_y_after_navigation=0,
            scroll_wait_ms=100,
            work_metrics_out=work_metrics,
        )

    assert work_metrics["active_wait_seconds"] == pytest.approx(0.1)
    assert work_metrics["regular_snapshot_count"] == 0
    assert work_metrics["other_seconds"] == pytest.approx(0.0)


def test_should_collect_full_listing_snapshot_uses_interval(monkeypatch) -> None:
    monkeypatch.setattr(page_crawl, "LISTING_FULL_SNAPSHOT_INTERVAL", 5)

    assert page_crawl.should_collect_full_listing_snapshot(1) is True
    assert page_crawl.should_collect_full_listing_snapshot(2) is False
    assert page_crawl.should_collect_full_listing_snapshot(5) is True


def test_should_collect_full_listing_snapshot_can_disable_interval(monkeypatch) -> None:
    monkeypatch.setattr(page_crawl, "LISTING_FULL_SNAPSHOT_INTERVAL", 0)

    assert page_crawl.should_collect_full_listing_snapshot(1) is True
    assert page_crawl.should_collect_full_listing_snapshot(2) is False


def test_listing_scroll_stability_requires_page_record_floor() -> None:
    assert page_crawl.should_stop_listing_scroll(
        record_count=87,
        unchanged_rounds=3,
        no_scroll_rounds=0,
        stable_rounds=3,
        min_page_records=100,
    ) is False

    assert page_crawl.should_stop_listing_scroll(
        record_count=100,
        unchanged_rounds=3,
        no_scroll_rounds=0,
        stable_rounds=3,
        min_page_records=100,
    ) is True


def test_listing_scroll_stops_when_page_cannot_scroll_further() -> None:
    assert page_crawl.should_stop_listing_scroll(
        record_count=87,
        unchanged_rounds=3,
        no_scroll_rounds=3,
        stable_rounds=3,
        min_page_records=100,
    ) is True


def test_listing_scroll_time_cap_requires_minimum_records() -> None:
    assert page_crawl.should_stop_listing_scroll(
        record_count=59,
        unchanged_rounds=0,
        no_scroll_rounds=0,
        stable_rounds=3,
        elapsed_seconds=300,
        max_page_seconds=240,
        min_records_before_time_cap=60,
    ) is False

    assert page_crawl.should_stop_listing_scroll(
        record_count=60,
        unchanged_rounds=0,
        no_scroll_rounds=0,
        stable_rounds=3,
        elapsed_seconds=300,
        max_page_seconds=240,
        min_records_before_time_cap=60,
    ) is True
