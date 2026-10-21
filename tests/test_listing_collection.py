import time

import pytest
from playwright.sync_api import sync_playwright

from agoda_crawler.listing import collection
from agoda_crawler.listing.collection import collect_listing_snapshot, normalize_hotel_url
from agoda_crawler.listing.records import merge_records_into_results


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def perf_counter(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_normalize_hotel_url_removes_tracking_params() -> None:
    url = normalize_hotel_url(
        "/vi-vn/demo-hotel/hotel/vung-tau-vn.html?cid=-1&searchrequestid=abc&rooms=1",
        "https://www.agoda.com/vi-vn/search?city=17190",
    )

    assert url == "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html?rooms=1"


def test_normalize_hotel_url_rejects_non_hotel_url() -> None:
    assert normalize_hotel_url("/vi-vn/search?city=17190", "https://www.agoda.com") is None


def test_normalize_hotel_url_accepts_agoda_property_id_route_and_keeps_identity() -> None:
    url = normalize_hotel_url(
        "https://www.agoda.com/vi-vn/example-property/vung-tau"
        "?propertyId=123&checkIn=2026-11-09&checkOut=2026-11-10&cid=-1",
        "https://www.agoda.com/vi-vn/search?city=17190",
    )

    assert url == (
        "https://www.agoda.com/vi-vn/example-property/vung-tau"
        "?propertyId=123&checkIn=2026-11-09&checkOut=2026-11-10"
    )


def test_normalize_hotel_url_rejects_invalid_property_id_routes() -> None:
    rejected = [
        "https://www.agoda.com/vi-vn/example-property/vung-tau",
        "https://www.agoda.com/vi-vn/example-property/vung-tau?propertyId=abc",
        "https://example.com/vi-vn/example-property/vung-tau?propertyId=123",
        "https://www.agoda.com/vi-vn/search/example-property?propertyId=123",
        "https://www.agoda.com/vi-vn/example-property/vung-tau?propertyId=123&PROPERTYID=456",
    ]

    for url in rejected:
        assert normalize_hotel_url(url, "https://www.agoda.com") is None


class _ListingPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 120
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": [
                    "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html?cid=1",
                    "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html?cid=2",
                ],
                "anchorHrefs": [
                    "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html?cid=1",
                ],
                "urlSources": [
                    {
                        "source": "anchor_href",
                        "value": "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html?cid=1",
                    }
                ],
                "name": "Demo Hotel",
                "text": "Demo Hotel 8,7 Tuyet voi 123 nhan xet 500.000 ₫ Gia moi dem",
                "sourceSelector": '[data-selenium="hotel-item"]',
                "outerHtmlPreview": "<div>Demo Hotel</div>",
            },
            {
                "urls": [],
                "anchorHrefs": [],
                "name": "No URL Hotel",
                "text": "No URL Hotel card",
                "sourceSelector": '[data-selenium="hotel-item"]',
                "outerHtmlPreview": "<div>No URL Hotel card</div>",
            },
        ]


def test_collect_listing_snapshot_reports_url_metrics() -> None:
    snapshot = collect_listing_snapshot(_ListingPage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 2
    assert snapshot.records[0]["hotel_name"] == "Demo Hotel"
    assert snapshot.records[0]["price_value"] == "500000"
    assert snapshot.records[0]["collect_status"] == "ok"
    assert snapshot.records[1]["hotel_name"] == "No URL Hotel"
    assert snapshot.records[1]["hotel_url"] is None
    assert snapshot.records[1]["collect_status"] == "missing_url"
    assert snapshot.records[1]["record_kind"] == "partial_missing_url"
    assert snapshot.records[1]["partial_debug"]["hotel_name"] == "No URL Hotel"
    assert snapshot.records[1]["partial_debug"]["outer_html_preview"] == "<div>No URL Hotel card</div>"
    assert snapshot.metrics.dom_card_count == 2
    assert snapshot.metrics.candidate_records == 2
    assert snapshot.metrics.candidate_url_count == 2
    assert snapshot.metrics.valid_url_count == 2
    assert snapshot.metrics.unique_canonical_url_count == 1
    assert snapshot.metrics.duplicate_url_count == 1
    assert snapshot.metrics.unique_hotel_count == 2
    assert snapshot.metrics.cards_without_url_count == 1
    assert snapshot.metrics.anchorless_card_count == 1


def test_collect_listing_snapshot_tracks_unrounded_phase_metrics(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(time, "perf_counter", clock.perf_counter)
    page = _ListingPage()
    cards = [
        {
            "urls": ["https://www.agoda.com/vi-vn/metrics/hotel/vung-tau-vn.html"],
            "name": "Metrics Hotel",
            "text": "Metrics Hotel 500000 VND",
        },
        {
            "urls": ["https://www.agoda.com/vi-vn/metrics/hotel/vung-tau-vn.html"],
            "name": "Metrics Hotel",
            "text": "Metrics Hotel 500000 VND",
        },
    ]

    def fake_dom(*_args, **_kwargs):
        clock.advance(0.003)
        return cards

    def fake_embedded(*_args, **_kwargs):
        clock.advance(0.002)
        return []

    def fake_parse(_text):
        clock.advance(0.004)
        return {
            "price_value": "500000",
            "rating_text": None,
            "review_count_text": None,
            "star_rating_text": None,
        }

    original_merge = collection.merge_page_record

    def fake_merge(*args, **kwargs):
        clock.advance(0.001)
        return original_merge(*args, **kwargs)

    monkeypatch.setattr(collection, "_evaluate_listing_dom", fake_dom)
    monkeypatch.setattr(collection, "_evaluate_embedded_hotel_url_cards", fake_embedded)
    monkeypatch.setattr(collection, "_parse_textual_fallback", fake_parse)
    monkeypatch.setattr(collection, "_scroll_y", lambda _page: 0)
    monkeypatch.setattr(collection, "merge_page_record", fake_merge)

    full = collect_listing_snapshot(page, '[data-selenium="hotel-item"]', 1)
    regular = collect_listing_snapshot(
        page,
        '[data-selenium="hotel-item"]',
        1,
        include_embedded=False,
        include_broad_selectors=False,
    )

    assert full.metrics.full_snapshot_count == 1
    assert full.metrics.regular_snapshot_count == 0
    assert full.metrics.dom_call_seconds == pytest.approx(0.003)
    assert full.metrics.embedded_call_seconds == pytest.approx(0.002)
    assert full.metrics.parse_dedupe_seconds == pytest.approx(0.008)
    assert full.metrics.merge_seconds == pytest.approx(0.002)

    assert regular.metrics.full_snapshot_count == 0
    assert regular.metrics.regular_snapshot_count == 1
    assert regular.metrics.dom_call_seconds == pytest.approx(0.003)
    assert regular.metrics.embedded_call_seconds == pytest.approx(0.0)
    assert regular.metrics.parse_dedupe_seconds == pytest.approx(0.008)
    assert regular.metrics.merge_seconds == pytest.approx(0.002)


def test_observed_record_seed_merge_is_counted_as_merge_time(monkeypatch) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(time, "perf_counter", clock.perf_counter)
    monkeypatch.setattr(collection, "_evaluate_listing_dom", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(collection, "_scroll_y", lambda _page: 0)
    original_merge = collection.merge_page_record

    def timed_merge(*args, **kwargs):
        clock.advance(0.004)
        return original_merge(*args, **kwargs)

    monkeypatch.setattr(collection, "merge_page_record", timed_merge)
    observed_record = {
        "hotel_name": "Observed Hotel",
        "hotel_url": "https://www.agoda.com/observed/hotel/vung-tau-vn.html",
    }

    snapshot = collect_listing_snapshot(
        _ListingPage(),
        '[data-selenium="hotel-item"]',
        1,
        include_embedded=False,
        include_broad_selectors=False,
        observed_records=[observed_record],
    )

    assert snapshot.metrics.merge_seconds == pytest.approx(0.004)
    assert snapshot.metrics.parse_dedupe_seconds == pytest.approx(0.0)


class _MissingPricePage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": ["https://www.agoda.com/vi-vn/no-price/hotel/vung-tau-vn.html"],
                "name": "No Price Hotel",
                "text": "No Price Hotel 8.5 Excellent 22 reviews",
            }
        ]


def test_collect_listing_snapshot_does_not_drop_missing_price() -> None:
    snapshot = collect_listing_snapshot(_MissingPricePage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["hotel_name"] == "No Price Hotel"
    assert snapshot.records[0]["price_value"] is None
    assert snapshot.records[0]["hotel_url"]


class _TextFallbackPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": [],
                "name": "",
                "text": "Fallback Hotel 9.1 Exceptional 88 reviews Vung Tau",
            }
        ]


def test_collect_listing_snapshot_keeps_missing_url_from_card_text() -> None:
    snapshot = collect_listing_snapshot(_TextFallbackPage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["hotel_url"] is None
    assert snapshot.records[0]["hotel_name"].startswith("Fallback Hotel")
    assert snapshot.records[0]["collect_status"] == "missing_url"
    assert snapshot.metrics.cards_without_url_count == 1
    assert snapshot.metrics.cards_without_name_count == 1


class _DistinctUrlPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": ["https://www.agoda.com/vi-vn/alpha-hotel/hotel/vung-tau-vn.html?cid=1"],
                "name": "Alpha Hotel",
                "text": "Alpha Hotel",
            },
            {
                "urls": ["https://www.agoda.com/vi-vn/beta-hotel/hotel/vung-tau-vn.html?cid=1"],
                "name": "Beta Hotel",
                "text": "Beta Hotel",
            },
        ]


def test_collect_listing_snapshot_does_not_dedup_distinct_canonical_urls() -> None:
    snapshot = collect_listing_snapshot(_DistinctUrlPage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 2
    assert snapshot.metrics.unique_canonical_url_count == 2
    assert snapshot.metrics.duplicate_url_count == 0


class _EmbeddedUrlPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return [
                {
                    "urls": ["/vi-vn/embedded-hotel/hotel/vung-tau-vn.html?cid=1"],
                    "name": "",
                    "text": "",
                    "dataSelenium": "embedded-state",
                    "dataTestId": "embedded-state",
                }
            ]
        return []


def test_collect_listing_snapshot_does_not_admit_embedded_only_urls() -> None:
    snapshot = collect_listing_snapshot(_EmbeddedUrlPage(), '[data-selenium="hotel-item"]', 1)

    assert snapshot.records == []
    assert snapshot.metrics.dom_card_count == 0
    assert snapshot.metrics.embedded_url_count == 1


class _SnapshotMembershipPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def __init__(self, cards=None, embedded_urls=None) -> None:
        self.cards = cards or []
        self.embedded_urls = embedded_urls or []

    def evaluate(self, script: str, *_args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return [
                {
                    "urls": [url],
                    "name": "",
                    "text": "",
                    "dataSelenium": "embedded-state",
                    "dataTestId": "embedded-state",
                }
                for url in self.embedded_urls
            ]
        return self.cards


def test_later_embedded_snapshot_enriches_card_observed_before_virtualization() -> None:
    card = {
        "urls": [],
        "name": "Card Hotel",
        "text": "Card Hotel 8.5 Excellent 22 reviews",
        "propertyId": "123",
        "dataSelenium": "hotel-item",
        "sourceSelector": '[data-selenium="hotel-item"]',
    }
    first = collect_listing_snapshot(
        _SnapshotMembershipPage(cards=[card]),
        '[data-selenium="hotel-item"]',
        1,
        include_embedded=False,
    )
    second = collect_listing_snapshot(
        _SnapshotMembershipPage(
            embedded_urls=[
                "https://www.agoda.com/vi-vn/shared/hotel/listing.html?propertyId=123"
            ]
        ),
        '[data-selenium="hotel-item"]',
        1,
        observed_records=first.records,
    )

    assert len(second.records) == 1
    assert second.records[0]["hotel_name"] == "Card Hotel"
    assert second.records[0]["hotel_url"] == (
        "https://www.agoda.com/vi-vn/shared/hotel/listing.html?propertyId=123"
    )
    assert second.records[0]["price_value"] is None
    assert second.embedded_nonmember_records == []


def test_unmatched_embedded_url_is_not_cached_for_a_later_partial_card() -> None:
    embedded = collect_listing_snapshot(
        _SnapshotMembershipPage(
            embedded_urls=[
                "https://www.agoda.com/vi-vn/shared/hotel/listing.html?propertyId=123"
            ]
        ),
        '[data-selenium="hotel-item"]',
        1,
    )
    later_card = collect_listing_snapshot(
        _SnapshotMembershipPage(
            cards=[
                {
                    "urls": [],
                    "name": "Card Hotel",
                    "text": "Card Hotel",
                    "propertyId": "123",
                    "dataSelenium": "hotel-item",
                    "sourceSelector": '[data-selenium="hotel-item"]',
                }
            ]
        ),
        '[data-selenium="hotel-item"]',
        1,
        include_embedded=False,
    )

    assert embedded.records == []
    assert len(later_card.records) == 1
    assert later_card.records[0]["hotel_url"] is None


def test_embedded_match_requires_strong_identity_not_name_similarity() -> None:
    snapshot = collect_listing_snapshot(
        _SnapshotMembershipPage(
            embedded_urls=[
                "https://www.agoda.com/vi-vn/shared-hotel/hotel/vung-tau-vn.html"
            ]
        ),
        '[data-selenium="hotel-item"]',
        1,
        observed_records=[
            {
                "hotel_name": "Shared Hotel",
                "hotel_url": None,
                "price_value": "500000",
            }
        ],
    )

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["hotel_name"] == "Shared Hotel"
    assert snapshot.records[0]["hotel_url"] is None
    assert len(snapshot.embedded_nonmember_records) == 1


def test_embedded_property_id_conflict_is_rejected_even_for_shared_path() -> None:
    shared_path = "https://www.agoda.com/vi-vn/shared/hotel/listing.html"
    snapshot = collect_listing_snapshot(
        _SnapshotMembershipPage(embedded_urls=[f"{shared_path}?propertyId=222"]),
        '[data-selenium="hotel-item"]',
        1,
        observed_records=[
            {
                "hotel_name": "Card Hotel",
                "hotel_url": f"{shared_path}?propertyId=111",
                "listing_property_id": "111",
            }
        ],
    )

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["hotel_url"] == f"{shared_path}?propertyId=111"
    assert snapshot.embedded_nonmember_records == [
        {
            "hotel_url": f"{shared_path}?propertyId=222",
            "canonical_url": f"{shared_path}?propertyId=222",
            "listing_property_id": "222",
        }
    ]


def test_real_card_from_neighboring_city_remains_in_membership() -> None:
    snapshot = collect_listing_snapshot(
        _SnapshotMembershipPage(
            cards=[
                {
                    "urls": [
                        "https://www.agoda.com/vi-vn/nearby/hotel/da-nang-vn.html"
                    ],
                    "name": "Nearby Hotel",
                    "text": "Nearby Hotel",
                    "dataSelenium": "hotel-item",
                    "sourceSelector": '[data-selenium="hotel-item"]',
                }
            ]
        ),
        '[data-selenium="hotel-item"]',
        1,
        include_embedded=False,
    )

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["hotel_name"] == "Nearby Hotel"
    assert snapshot.records[0]["hotel_url"].endswith("da-nang-vn.html")


class _DataAttributeUrlPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": ["/vi-vn/data-url-hotel/hotel/vung-tau-vn.html?cid=1"],
                "anchorHrefs": [],
                "urlSources": [
                    {
                        "source": "attr:data-href",
                        "value": "/vi-vn/data-url-hotel/hotel/vung-tau-vn.html?cid=1",
                    }
                ],
                "name": "Data Url Hotel",
                "text": "Data Url Hotel",
                "sourceSelector": '[data-testid="property-card"]',
            }
        ]


def test_collect_listing_snapshot_keeps_url_source_debug() -> None:
    snapshot = collect_listing_snapshot(_DataAttributeUrlPage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["hotel_url"] == "https://www.agoda.com/vi-vn/data-url-hotel/hotel/vung-tau-vn.html"
    assert snapshot.records[0]["raw_candidate_urls"] == [
        "/vi-vn/data-url-hotel/hotel/vung-tau-vn.html?cid=1"
    ]
    assert snapshot.records[0]["url_sources"][0]["source"] == "attr:data-href"
    assert snapshot.records[0]["card_source"] == '[data-testid="property-card"]'


class _PropertyIdMergePage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": [],
                "anchorHrefs": [],
                "name": "Lazy Hotel",
                "text": "Mo Lazy Hotel trong the moi",
                "propertyId": "123",
                "dataSelenium": "hotel-item",
                "sourceSelector": '[data-selenium="hotel-item"]',
            },
            {
                "urls": ["/vi-vn/lazy-hotel/hotel/vung-tau-vn.html?cid=1"],
                "anchorHrefs": ["/vi-vn/lazy-hotel/hotel/vung-tau-vn.html?cid=1"],
                "name": "",
                "text": "",
                "propertyId": "123",
                "sourceSelector": "hotel-anchor-closest",
            },
        ]


def test_collect_listing_snapshot_merges_partial_with_url_by_property_id() -> None:
    snapshot = collect_listing_snapshot(_PropertyIdMergePage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["hotel_name"] == "Lazy Hotel"
    assert snapshot.records[0]["listing_property_id"] == "123"
    assert snapshot.records[0]["hotel_url"] == "https://www.agoda.com/vi-vn/lazy-hotel/hotel/vung-tau-vn.html"
    assert snapshot.records[0]["record_kind"] == "full_record"


class _CandidateCardsPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def __init__(self, cards):
        self.cards = cards

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return self.cards


def test_property_id_route_snapshot_keeps_44_distinct_hotels_and_prices() -> None:
    cards = [
        {
            "urls": [
                "https://www.agoda.com/vi-vn/shared-city/vung-tau"
                f"?propertyId={property_id}"
            ],
            "name": f"Demo Hotel {property_id}",
            "text": f"Demo Hotel {property_id} Gia moi dem VND 500.000",
        }
        for property_id in range(1000, 1044)
    ]

    snapshot = collect_listing_snapshot(
        _CandidateCardsPage(cards), '[data-selenium="hotel-item"]', 1
    )

    assert len(snapshot.records) == 44
    assert snapshot.metrics.unique_canonical_url_count == 44
    assert snapshot.metrics.unique_hotel_count == 44
    assert all(record["price_value"] == "500000" for record in snapshot.records)
    assert {
        record["canonical_url"].rsplit("=", 1)[-1] for record in snapshot.records
    } == {str(property_id) for property_id in range(1000, 1044)}


def test_partial_and_full_snapshots_merge_in_either_order_for_44_properties() -> None:
    partial_cards = [
        {
            "urls": [],
            "name": f"Demo Hotel {property_id}",
            "text": f"Demo Hotel {property_id} No price available",
            "propertyId": str(property_id),
        }
        for property_id in range(1000, 1044)
    ]
    full_cards = [
        {
            "urls": [
                "https://www.agoda.com/vi-vn/shared-city/vung-tau"
                f"?propertyId={property_id}"
            ],
            "name": f"Demo Hotel {property_id}",
            "text": f"Demo Hotel {property_id} Gia moi dem VND 500.000",
        }
        for property_id in range(1000, 1044)
    ]
    partial_snapshot = collect_listing_snapshot(
        _CandidateCardsPage(partial_cards), '[data-selenium="hotel-item"]', 1
    )
    full_snapshot = collect_listing_snapshot(
        _CandidateCardsPage(full_cards), '[data-selenium="hotel-item"]', 1
    )

    for ordered_snapshots in (
        (partial_snapshot, full_snapshot),
        (full_snapshot, partial_snapshot),
    ):
        records_by_key = {}
        for snapshot in ordered_snapshots:
            merge_records_into_results(records_by_key, snapshot.records)

        records = list(records_by_key.values())
        assert len(records) == 44
        assert all(record["hotel_url"] for record in records)
        assert all(record["price_value"] == "500000" for record in records)
        assert all(record["collect_status"] == "ok" for record in records)
        assert all(record["record_kind"] == "full_record" for record in records)
        assert all("partial_debug" not in record for record in records)


class _ImageSlidePage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": [],
                "anchorHrefs": [],
                "name": "Phong nghi",
                "text": "Phong nghi",
                "propertyId": "456",
                "tagName": "LI",
                "className": "aaa63-snap",
                "sourceSelector": "li",
                "outerHtmlPreview": '<li aria-roledescription="slide"><img alt="Phong nghi"></li>',
            }
        ]


def test_collect_listing_snapshot_marks_image_slide_invalid_not_partial_hotel() -> None:
    snapshot = collect_listing_snapshot(_ImageSlidePage(), '[data-selenium="hotel-item"]', 1)

    assert snapshot.records == []
    assert snapshot.metrics.invalid_card_count == 1
    assert snapshot.metrics.invalid_card_samples[0]["property_id"] == "456"


class _GenericAccommodationLabelPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": [],
                "anchorHrefs": ["https://www.agoda.com/vi-vn/"],
                "name": "Khách sạn + Nhà",
                "text": "Khách sạn + Nhà",
                "sourceSelector": 'div[data-selenium*="hotel" i]',
                "dataSelenium": "hotel-filter",
            }
        ]


def test_collect_listing_snapshot_drops_generic_accommodation_label() -> None:
    snapshot = collect_listing_snapshot(
        _GenericAccommodationLabelPage(),
        '[data-selenium="hotel-item"]',
        1,
    )

    assert snapshot.records == []
    assert snapshot.metrics.invalid_card_count == 1


@pytest.mark.parametrize(
    "outside_markup",
    [
        '<footer><div><a href="https://www.agoda.com/vi-vn/footer/hotel/vung-tau-vn.html">Footer Hotel</a></div></footer>',
        '<footer><article><a href="https://www.agoda.com/vi-vn/footer/hotel/vung-tau-vn.html">Footer Hotel</a></article></footer>',
        '<footer><li data-hotelid="222"><a href="https://www.agoda.com/vi-vn/footer/hotel/vung-tau-vn.html">Footer Hotel</a></li></footer>',
        '<section class="recommendations"><article><a href="https://www.agoda.com/vi-vn/footer/hotel/vung-tau-vn.html">Footer Hotel</a></article></section>',
    ],
)
def test_dom_collection_does_not_promote_non_listing_hotel_links(outside_markup: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<article data-selenium="hotel-item">'
                '<a href="https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html">'
                'Card Hotel</a><span>500000 VND</span></article>'
                f'{outside_markup}',
                wait_until="domcontentloaded",
            )

            snapshot = collect_listing_snapshot(
                page,
                '[data-selenium="hotel-item"]',
                1,
                include_embedded=False,
            )

            assert [record["hotel_name"] for record in snapshot.records] == ["Card Hotel"]
            assert [record["hotel_url"] for record in snapshot.records] == [
                "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html"
            ]
        finally:
            browser.close()


def test_dom_collection_keeps_genuine_broad_article_card() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<main id="search-results"><h1>Recommended hotels</h1>'
                '<article class="sponsored-result">'
                '<a href="https://www.agoda.com/vi-vn/broad/hotel/vung-tau-vn.html">'
                'Broad Hotel</a><span>700000 VND</span></article></main>',
                wait_until="domcontentloaded",
            )

            snapshot = collect_listing_snapshot(
                page,
                '[data-selenium="missing-card-selector"]',
                1,
                include_embedded=False,
            )

            assert [record["hotel_name"] for record in snapshot.records] == ["Broad Hotel"]
            assert snapshot.records[0]["hotel_url"] == (
                "https://www.agoda.com/vi-vn/broad/hotel/vung-tau-vn.html"
            )
        finally:
            browser.close()


@pytest.mark.parametrize(
    "outside_markup",
    [
        '<section aria-label="Recently viewed hotels">'
        '<h2>Recently viewed hotels</h2><div>'
        '<a href="https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html">'
        'Other Hotel</a><span>600000 VND</span></div></section>',
        '<section aria-label="You might also like">'
        '<h2>You might also like</h2><article>'
        '<a href="https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html">'
        'Other Hotel</a><span>600000 VND</span></article></section>',
    ],
)
def test_dom_collection_rejects_cards_outside_verified_listing_root(
    outside_markup: str,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<main id="search-results"><article data-selenium="hotel-item">'
                '<a href="https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html">'
                'Card Hotel</a><span>500000 VND</span></article></main>'
                f'{outside_markup}',
                wait_until="domcontentloaded",
            )

            snapshot = collect_listing_snapshot(
                page,
                '[data-selenium="hotel-item"]',
                1,
                include_embedded=False,
            )

            assert [record["hotel_name"] for record in snapshot.records] == ["Card Hotel"]
        finally:
            browser.close()


def test_dom_collection_ignores_recommendation_links_inside_broad_card_wrapper() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<main><article data-selenium="hotel-item">'
                '<a href="https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html">'
                'Card Hotel</a><span>500000 VND</span></article>'
                '<article><section class="recommendations">'
                '<a aria-label="Other Hotel" '
                'href="https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html">'
                'Other Hotel</a><span>600000 VND</span>'
                '</section></article></main>',
                wait_until="domcontentloaded",
            )

            snapshot = collect_listing_snapshot(
                page,
                '[data-selenium="hotel-item"]',
                1,
                include_embedded=False,
            )

            assert [record["hotel_name"] for record in snapshot.records] == ["Card Hotel"]
            assert [record["hotel_url"] for record in snapshot.records] == [
                "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html"
            ]
        finally:
            browser.close()


def test_dom_collection_uses_only_eligible_subtree_for_mixed_card_identity() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(
                '<main><article data-selenium="hotel-item" data-hotelid="111">'
                '<section class="recommendations">'
                '<a aria-label="Other Hotel" '
                'href="https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html?propertyId=222">'
                'Other Hotel</a><span>600000 VND</span><img alt="Other Image"></section>'
                '<h3 data-selenium="hotel-name">Card Hotel</h3>'
                '<a aria-label="Card Hotel" '
                'href="https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html?propertyId=111">'
                'Card Hotel</a><span style="display:none">900000 VND</span>'
                '<span>500000 VND</span></article></main>',
                wait_until="domcontentloaded",
            )

            snapshot = collect_listing_snapshot(
                page,
                '[data-selenium="hotel-item"]',
                1,
                include_embedded=False,
            )

            assert len(snapshot.records) == 1
            record = snapshot.records[0]
            assert record["hotel_name"] == "Card Hotel"
            assert record["hotel_url"] == (
                "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html?propertyId=111"
            )
            assert record["listing_property_id"] == "111"
            assert record["price_value"] == "500000"
        finally:
            browser.close()


def test_dom_collection_excludes_recommendation_text_nested_in_hotel_anchor() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            hotel_url = (
                "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html?propertyId=111"
            )
            page.set_content(
                '<main><article data-selenium="hotel-item">'
                f'<a href="{hotel_url}">'
                '<span class="recommendations">Other Hotel</span>Card Hotel</a>'
                '<span>500000 VND</span></article></main>',
                wait_until="domcontentloaded",
            )

            snapshot = collect_listing_snapshot(
                page,
                '[data-selenium="hotel-item"]',
                1,
                include_embedded=False,
            )

            assert len(snapshot.records) == 1
            assert snapshot.records[0]["hotel_name"] == "Card Hotel"
            assert snapshot.records[0]["hotel_url"] == hotel_url
        finally:
            browser.close()


def test_dom_collection_supplements_unverified_candidate_by_observed_identity() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            other_url = "https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html"
            page.set_content(
                '<main id="search-results"><article data-selenium="hotel-item">'
                '<a href="https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html">'
                'Card Hotel</a><span>500000 VND</span></article></main>'
                '<section><h2>Recent properties</h2><div>'
                f'<a href="{other_url}">Other Hotel</a><span>600000 VND</span>'
                '</div></section>',
                wait_until="domcontentloaded",
            )

            snapshot = collect_listing_snapshot(
                page,
                '[data-selenium="hotel-item"]',
                1,
                include_embedded=False,
                observed_records=[
                    {"hotel_name": "Other Hotel", "hotel_url": other_url}
                ],
            )

            assert {record["hotel_name"] for record in snapshot.records} == {
                "Card Hotel",
                "Other Hotel",
            }
        finally:
            browser.close()
