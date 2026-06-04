from agoda_crawler.listing import page_crawl
from agoda_crawler.listing.collection import (
    ListingCollectionMetrics,
    ListingCollectionSnapshot,
)
from agoda_crawler.listing.scrolling import ScrollAdvance


class _FakePage:
    def wait_for_timeout(self, _timeout_ms: int) -> None:
        return None


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
    monkeypatch.setattr(
        page_crawl,
        "save_final_listing_artifacts",
        lambda *args, **kwargs: None,
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
