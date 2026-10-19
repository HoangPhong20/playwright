from agoda_crawler.listing.collection import collect_listing_snapshot, normalize_hotel_url
from agoda_crawler.listing.records import merge_records_into_results


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


def test_collect_listing_snapshot_reads_embedded_hotel_urls() -> None:
    snapshot = collect_listing_snapshot(_EmbeddedUrlPage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["hotel_name"] == "Embedded Hotel"
    assert snapshot.records[0]["hotel_url"] == "https://www.agoda.com/vi-vn/embedded-hotel/hotel/vung-tau-vn.html"
    assert snapshot.metrics.dom_card_count == 0
    assert snapshot.metrics.embedded_url_count == 1


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
