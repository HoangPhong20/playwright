from agoda_crawler.listing.collection import (
    _property_url_map_from_html,
    collect_listing_snapshot,
    normalize_hotel_url,
)


def test_normalize_hotel_url_removes_tracking_params() -> None:
    url = normalize_hotel_url(
        "/vi-vn/demo-hotel/hotel/vung-tau-vn.html?cid=-1&searchrequestid=abc&rooms=1",
        "https://www.agoda.com/vi-vn/search?city=17190",
    )

    assert url == "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html?rooms=1"


def test_normalize_hotel_url_rejects_non_hotel_url() -> None:
    assert normalize_hotel_url("/vi-vn/search?city=17190", "https://www.agoda.com") is None


class _LightSnapshotPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "PROPERTY_URL_HTML" in script:
            raise AssertionError("light snapshots should not scan full page HTML")
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": [],
                "anchorHrefs": [],
                "name": "Light Snapshot Hotel",
                "text": "Light Snapshot Hotel 8.6 120 reviews",
                "imageUrl": "",
                "propertyId": "123",
                "dataSelenium": "hotel-item",
                "sourceSelector": '[data-selenium="hotel-item"]',
            }
        ]


def test_collect_listing_snapshot_skips_html_property_map_for_light_snapshots() -> None:
    snapshot = collect_listing_snapshot(
        _LightSnapshotPage(),
        '[data-selenium="hotel-item"]',
        1,
        include_embedded=False,
        include_broad_selectors=False,
    )

    assert len(snapshot.records) == 1
    assert snapshot.metrics.property_url_map_count == 0


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
                "imageUrl": "/demo.jpg",
                "sourceSelector": '[data-selenium="hotel-item"]',
                "outerHtmlPreview": "<div>Demo Hotel</div>",
            },
            {
                "urls": [],
                "anchorHrefs": [],
                "name": "No URL Hotel",
                "text": "No URL Hotel card",
                "imageUrl": "",
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
                "imageUrl": "",
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
                "imageUrl": "/fallback.jpg",
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
                "imageUrl": "",
            },
            {
                "urls": ["https://www.agoda.com/vi-vn/beta-hotel/hotel/vung-tau-vn.html?cid=1"],
                "name": "Beta Hotel",
                "text": "Beta Hotel",
                "imageUrl": "",
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
                    "imageUrl": "",
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
                "imageUrl": "",
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
                "imageUrl": "https://pix6.agoda.net/hotelImages/123/123.jpg",
                "propertyId": "123",
                "dataSelenium": "hotel-item",
                "sourceSelector": '[data-selenium="hotel-item"]',
            },
            {
                "urls": ["/vi-vn/lazy-hotel/hotel/vung-tau-vn.html?cid=1"],
                "anchorHrefs": ["/vi-vn/lazy-hotel/hotel/vung-tau-vn.html?cid=1"],
                "name": "",
                "text": "",
                "imageUrl": "",
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


class _DuplicateLazyFieldPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": ["/vi-vn/lazy-field-hotel/hotel/vung-tau-vn.html?cid=1"],
                "anchorHrefs": ["/vi-vn/lazy-field-hotel/hotel/vung-tau-vn.html?cid=1"],
                "name": "Lazy Field Hotel",
                "text": "Lazy Field Hotel",
                "imageUrl": "",
                "propertyId": "789",
                "sourceSelector": '[data-selenium="hotel-item"]',
            },
            {
                "urls": ["/vi-vn/lazy-field-hotel/hotel/vung-tau-vn.html?cid=2"],
                "anchorHrefs": ["/vi-vn/lazy-field-hotel/hotel/vung-tau-vn.html?cid=2"],
                "name": "Lazy Field Hotel",
                "text": "Lazy Field Hotel 4 stars out of 5",
                "imageUrl": "https://pix6.agoda.net/hotelImages/789/789.jpg",
                "propertyId": "789",
                "sourceSelector": '[data-selenium="hotel-item"]',
            },
        ]


def test_collect_listing_snapshot_merges_fields_from_duplicate_lazy_card() -> None:
    snapshot = collect_listing_snapshot(_DuplicateLazyFieldPage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 1
    assert snapshot.records[0]["image_url"] == "https://pix6.agoda.net/hotelImages/789/789.jpg"


def test_property_url_map_from_html_reads_escaped_url_near_property_id() -> None:
    html = (
        '<script>{"propertyId":"123",'
        '"landingURL":"\\/vi-vn\\/resolved-hotel\\/hotel\\/vung-tau-vn.html?cid=1"}'
        "</script>"
    )

    result = _property_url_map_from_html(
        html,
        ["123"],
        "https://www.agoda.com/vi-vn/search?city=17190",
    )

    assert result["123"]["url"] == "https://www.agoda.com/vi-vn/resolved-hotel/hotel/vung-tau-vn.html"
    assert result["123"]["source"] == "property_url_map:html_near_property_id"


class _PropertyUrlMapPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "scrollY" in script:
            return 0
        if "PROPERTY_URL_HTML" in script:
            return (
                '<script>{"propertyId":"123",'
                '"url":"\\/vi-vn\\/resolved-hotel\\/hotel\\/vung-tau-vn.html?cid=1"}'
                "</script>"
            )
        if "document.documentElement" in script:
            return []
        return [
            {
                "urls": [],
                "anchorHrefs": [],
                "name": "Resolved Hotel",
                "text": "Mo Resolved Hotel trong the moi",
                "imageUrl": "",
                "propertyId": "123",
                "dataSelenium": "hotel-item",
                "sourceSelector": '[data-selenium="hotel-item"]',
            }
        ]


def test_collect_listing_snapshot_resolves_missing_url_from_property_url_map() -> None:
    snapshot = collect_listing_snapshot(_PropertyUrlMapPage(), '[data-selenium="hotel-item"]', 1)

    assert len(snapshot.records) == 1
    record = snapshot.records[0]
    assert record["hotel_url"] == "https://www.agoda.com/vi-vn/resolved-hotel/hotel/vung-tau-vn.html"
    assert record["collect_status"] == "ok"
    assert record["record_kind"] == "full_record"
    assert record["url_resolution_source"] == "property_url_map:html_near_property_id"
    assert snapshot.metrics.cards_with_url_before_resolve == 0
    assert snapshot.metrics.cards_with_url_after_resolve == 1
    assert snapshot.metrics.property_url_map_count == 1
    assert snapshot.metrics.property_url_resolved_count == 1


class _ApiUrlMapPage:
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
                "name": "",
                "text": "Mo API Hotel trong the moi",
                "imageUrl": "",
                "propertyId": "456",
                "dataSelenium": "hotel-item",
                "sourceSelector": '[data-selenium="hotel-item"]',
            }
        ]


def test_collect_listing_snapshot_resolves_missing_url_and_fields_from_api_map() -> None:
    snapshot = collect_listing_snapshot(
        _ApiUrlMapPage(),
        '[data-selenium="hotel-item"]',
        1,
        api_property_map={
            "456": {
                "hotel_url": "/vi-vn/api-hotel/hotel/da-nang-vn.html?cid=1",
                "hotel_name": "API Hotel",
                "price_value": "1200000",
                "rating_text": "8.7",
                "review_count_text": "321",
                "image_url": "//pix6.agoda.net/hotelImages/456/456.jpg",
                "source": "api_response:https://www.agoda.com/api/search",
            }
        },
        api_metrics={
            "api_response_count": 3,
            "api_json_response_count": 1,
            "api_property_count": 1,
            "api_url_count": 1,
        },
    )

    assert len(snapshot.records) == 1
    record = snapshot.records[0]
    assert record["hotel_name"] == "API Hotel"
    assert record["hotel_url"] == "https://www.agoda.com/vi-vn/api-hotel/hotel/da-nang-vn.html"
    assert record["price_value"] == "1200000"
    assert record["rating_text"] == "8.7"
    assert record["review_count_text"] == "321"
    assert record["image_url"] == "https://pix6.agoda.net/hotelImages/456/456.jpg"
    assert record["url_resolution_source"] == "api_response:https://www.agoda.com/api/search"
    assert record["api_merged_fields"] == [
        "price_value",
        "rating_text",
        "review_count_text",
        "image_url",
    ]
    assert snapshot.metrics.api_response_count == 3
    assert snapshot.metrics.api_json_response_count == 1
    assert snapshot.metrics.api_property_count == 1
    assert snapshot.metrics.api_url_count == 1
    assert snapshot.metrics.api_url_resolved_count == 1


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
                "imageUrl": "https://pix6.agoda.net/hotelImages/456/456.jpg",
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
                "imageUrl": "",
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
