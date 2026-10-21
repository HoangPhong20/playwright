import pytest
from playwright.sync_api import sync_playwright

from agoda_crawler.extraction import (
    _hotel_url_key,
    _name_from_hotel_url,
    extract_fast_hotel_links,
    extract_from_hotel_links,
    extract_page_results,
    _looks_like_city_landing_shell,
    _parse_review_count,
    _canonicalize_price_value,
    _price_value_from_text,
    _parse_star_rating,
    _record_key,
    _parse_textual_fallback,
)


def test_parse_textual_fallback_ignores_carousel_index_for_rating() -> None:
    text = (
        "Mo khach san Demo trong the moi 1/10 "
        "Khach san Demo 4 sao tren 5 "
        "Xep hang trung binh Tuyet voi 8,9/10 voi 2.311 bai danh gia "
        "Gia moi dem 1.155.203 \u20ab"
    )

    parsed = _parse_textual_fallback(text)

    assert parsed["rating_text"] == "8.9"
    assert parsed["price_value"] == "1155203"


def test_parse_textual_fallback_handles_contextual_vietnamese_rating() -> None:
    text = (
        "Khach san Demo 4 sao tren 5 "
        "Danh gia cua khach: Tuyet voi 8,7 voi 900 bai danh gia"
    )

    parsed = _parse_textual_fallback(text)

    assert parsed["rating_text"] == "8.7"


def test_parse_textual_fallback_does_not_invent_rating_from_unrelated_numbers() -> None:
    text = (
        "Mo khach san Demo trong the moi 1/10 "
        "1 phong Cach Bai sau 416 m Cach trung tam 1,1 km"
    )

    parsed = _parse_textual_fallback(text)

    assert parsed["rating_text"] is None


def test_parse_textual_fallback_ignores_price_noise_without_digits() -> None:
    text = "Gia hien thi ... \u0110"

    parsed = _parse_textual_fallback(text)

    assert parsed["price_value"] is None


def test_canonicalize_price_value_standardizes_vnd_display_price() -> None:
    assert _canonicalize_price_value("250.484 \u20ab") == "250484"
    assert _canonicalize_price_value("VND 1,155,203") == "1155203"


def test_price_value_from_text_rejects_false_positive_short_numbers() -> None:
    assert _price_value_from_text("2 VND") is None
    assert _price_value_from_text("Gia moi dem VND 1,155,203") == "1155203"


def test_price_value_from_text_is_vnd_only_and_rejects_invalid_amounts() -> None:
    assert _price_value_from_text("USD 100.50") is None
    assert _price_value_from_text("$100.000 VND") is None
    assert _price_value_from_text("-100000 VND") is None
    assert _price_value_from_text("VND -100000") is None
    assert _price_value_from_text("Price -100000 VND") is None
    assert _price_value_from_text("(100000 VND)") is None
    assert _price_value_from_text("VND 1.000,50") is None
    assert _price_value_from_text("VND 0000") is None
    assert _price_value_from_text("VND 0.000") is None


def test_price_value_from_text_keeps_valid_nightly_price_before_discount() -> None:
    text = "VND 1.000.000 per night; discount -100000 VND"

    assert _price_value_from_text(text) == "1000000"


def test_price_value_from_text_prefers_discounted_per_night_price() -> None:
    text = "Gia Goc: 2.419.171 ₫ 2.419.171 ₫ -71% 702.050 ₫ Moi dem, chua co thue"

    assert _price_value_from_text(text) == "702050"


def test_price_value_from_text_does_not_treat_vietnamese_d_as_prefix_currency() -> None:
    text = "Đặt gói để tiết kiệm! 10 tháng 6 2026 từ 673.391 ₫ Xem giá"

    assert _price_value_from_text(text) == "673391"


def test_hotel_url_key_ignores_non_identity_query_and_fragment() -> None:
    first = (
        "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html"
        "?searchrequestid=aaa&tspTypes=8#rooms"
    )
    second = (
        "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html"
        "?searchrequestid=bbb&tspTypes=1"
    )

    assert _hotel_url_key(first) == _hotel_url_key(second)


def test_hotel_url_key_preserves_property_id_and_ignores_stay_parameters() -> None:
    first = (
        "https://www.agoda.com/vi-vn/demo-city/vung-tau"
        "?checkIn=2026-11-09&propertyId=111&checkOut=2026-11-10&cid=1#rooms"
    )
    same_property = (
        "https://www.agoda.com/vi-vn/demo-city/vung-tau"
        "?PROPERTYID=111&checkOut=2026-12-10&checkIn=2026-12-09&utm_source=test"
    )
    different_property = (
        "https://www.agoda.com/vi-vn/demo-city/vung-tau?propertyId=222"
    )

    assert _hotel_url_key(first) == _hotel_url_key(same_property)
    assert _hotel_url_key(first) != _hotel_url_key(different_property)


def test_hotel_url_key_keeps_legacy_hotel_url_identity() -> None:
    first = "https://www.agoda.com/vi-vn/demo/hotel/demo.html?cid=1&checkIn=2026-11-09"
    second = "https://www.agoda.com/vi-vn/demo/hotel/demo.html?cid=2&checkIn=2026-12-09"

    assert _hotel_url_key(first) == _hotel_url_key(second)


def test_record_key_uses_normalized_hotel_url_when_present() -> None:
    record = {
        "hotel_name": "Demo",
        "hotel_url": "https://www.agoda.com/vi-vn/demo/hotel/vung-tau-vn.html?a=1#x",
    }

    assert _record_key(record) == "https://www.agoda.com/vi-vn/demo/hotel/vung-tau-vn.html"


class _FakeLocator:
    def __init__(self, count: int) -> None:
        self._count = count

    def count(self) -> int:
        return self._count


class _FakePage:
    url = "https://www.agoda.com/vi-vn/city/vung-tau-vn.html"

    def locator(self, selector: str) -> _FakeLocator:
        if selector == 'a[href*="/hotel/"]':
            return _FakeLocator(40)
        return _FakeLocator(1)


def test_city_landing_shell_detection_skips_broad_article_card() -> None:
    assert _looks_like_city_landing_shell(_FakePage(), 'article:has(a[href*="/hotel/"])')


class _FastLinksPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *_args):
        return [
            {
                "href": "/vi-vn/demo/hotel/vung-tau-vn.html?cid=1",
                "text": " Demo Hotel ",
            },
            {
                "href": "/vi-vn/demo/hotel/vung-tau-vn.html?cid=2",
                "text": "Duplicate Demo Hotel",
            },
        ]


def test_extract_fast_hotel_links_dedupes_by_hotel_url() -> None:
    records = extract_fast_hotel_links(_FastLinksPage())

    assert len(records) == 1
    assert records[0]["hotel_name"] == "Demo Hotel"
    assert records[0]["hotel_url"] == "https://www.agoda.com/vi-vn/demo/hotel/vung-tau-vn.html?cid=1"


class _FastLinksWithoutTextPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *_args):
        return [
            {
                "href": "/vi-vn/the-song-vung-tau/hotel/vung-tau-vn.html?cid=1",
                "text": "",
            },
        ]


def test_extract_fast_hotel_links_keeps_urls_without_visible_text() -> None:
    records = extract_fast_hotel_links(_FastLinksWithoutTextPage())

    assert len(records) == 1
    assert records[0]["hotel_name"] == "The Song Vung Tau"


class _FallbackAnchor:
    def __init__(self, href: str, name: str) -> None:
        self.href = href
        self.name = name

    def get_attribute(self, name: str, timeout: int = 1000):
        if name == "href":
            return self.href
        if name == "aria-label":
            return self.name
        return None

    def inner_text(self, timeout: int = 1000) -> str:
        return self.name

    def locator(self, _selector: str):
        return _EmptyFallbackLocator()


class _FallbackAnchors:
    def __init__(self, anchors) -> None:
        self.anchors = anchors

    def count(self) -> int:
        return len(self.anchors)

    def nth(self, index: int):
        return self.anchors[index]


class _EmptyFallbackLocator:
    def __init__(self) -> None:
        self.first = self

    def count(self) -> int:
        return 0


class _FallbackLinksPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def locator(self, selector: str):
        if selector == 'a[href*="/hotel/"]':
            return _FallbackAnchors(
                [
                    _FallbackAnchor(
                        "/vi-vn/card-hotel/hotel/vung-tau-vn.html",
                        "Card Hotel",
                    ),
                    _FallbackAnchor(
                        "/vi-vn/footer-hotel/hotel/vung-tau-vn.html",
                        "Footer Hotel",
                    ),
                ]
            )
        return _EmptyFallbackLocator()


def test_page_fallback_keeps_card_record_without_admitting_footer_links(monkeypatch) -> None:
    card_record = {
        "hotel_name": "Card Hotel",
        "hotel_url": "https://www.agoda.com/vi-vn/card-hotel/hotel/vung-tau-vn.html",
        "price_value": "500000",
    }
    monkeypatch.setattr(
        "agoda_crawler.extraction.fields.extract_from_cards",
        lambda _page, _selector, _observed_records=None: [card_record.copy()],
    )

    records = extract_page_results(
        _FallbackLinksPage(),
        '[data-selenium="hotel-item"]',
    )

    assert [record["hotel_name"] for record in records] == ["Card Hotel"]
    assert records[0]["hotel_url"] == card_record["hotel_url"]


def test_link_fallback_can_complete_an_observed_property_identity() -> None:
    page = _FallbackLinksPage()
    page.locator = lambda selector: (
        _FallbackAnchors(
            [
                _FallbackAnchor(
                    "/vi-vn/card-hotel/hotel/vung-tau-vn.html?propertyId=123",
                    "Card Hotel",
                )
            ]
        )
        if selector == 'a[href*="/hotel/"]'
        else _EmptyFallbackLocator()
    )

    records = extract_from_hotel_links(
        page,
        observed_records=[
            {
                "hotel_name": "Card Hotel",
                "hotel_url": None,
                "listing_property_id": "123",
            }
        ],
    )

    assert len(records) == 1
    assert records[0]["hotel_name"] == "Card Hotel"
    assert records[0]["hotel_url"].endswith("propertyId=123")


@pytest.mark.parametrize(
    "outside_markup",
    [
        '<footer><article>'
        '<a aria-label="Footer Hotel" '
        'href="https://www.agoda.com/vi-vn/footer/hotel/vung-tau-vn.html">'
        'Footer Hotel</a><span>600000 VND</span></article></footer>',
        '<section class="recommendations"><article>'
        '<a aria-label="Footer Hotel" '
        'href="https://www.agoda.com/vi-vn/footer/hotel/vung-tau-vn.html">'
        'Footer Hotel</a><span>600000 VND</span></article></section>',
    ],
)
def test_broad_card_extraction_does_not_admit_non_listing_article(
    outside_markup: str,
) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            card_url = "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html"
            page.set_content(
                '<article data-selenium="hotel-item">'
                f'<a aria-label="Card Hotel" href="{card_url}">Card Hotel</a>'
                '<span>500000 VND</span></article>'
                f'{outside_markup}',
                wait_until="domcontentloaded",
            )

            records = extract_page_results(
                page,
                'article:has(a[href*="/hotel/"])',
                observed_records=[
                    {
                        "hotel_name": "Card Hotel",
                        "hotel_url": card_url,
                        "price_value": "500000",
                    }
                ],
            )

            assert [record["hotel_name"] for record in records] == ["Card Hotel"]
            assert [record["hotel_url"] for record in records] == [card_url]
        finally:
            browser.close()


def test_broad_card_extraction_keeps_sponsored_listing_under_recommended_heading() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            card_url = "https://www.agoda.com/vi-vn/sponsored/hotel/vung-tau-vn.html"
            page.set_content(
                '<main id="search-results"><h1>Recommended hotels</h1>'
                '<article class="sponsored-result">'
                f'<a aria-label="Sponsored Hotel" href="{card_url}">Sponsored Hotel</a>'
                '<span>700000 VND</span></article></main>',
                wait_until="domcontentloaded",
            )

            records = extract_page_results(
                page,
                'article:has(a[href*="/hotel/"])',
            )

            assert [record["hotel_name"] for record in records] == ["Sponsored Hotel"]
            assert records[0]["hotel_url"] == card_url
        finally:
            browser.close()


def test_broad_card_extraction_rejects_unobserved_card_outside_listing_root() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            card_url = "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html"
            page.set_content(
                '<main id="search-results"><article data-selenium="hotel-item">'
                f'<a aria-label="Card Hotel" href="{card_url}">Card Hotel</a>'
                '<span>500000 VND</span></article></main>'
                '<section aria-label="You might also like">'
                '<h2>You might also like</h2><article>'
                '<a aria-label="Other Hotel" '
                'href="https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html">'
                'Other Hotel</a><span>600000 VND</span></article></section>',
                wait_until="domcontentloaded",
            )

            records = extract_page_results(
                page,
                'article:has(a[href*="/hotel/"])',
                observed_records=[
                    {
                        "hotel_name": "Card Hotel",
                        "hotel_url": card_url,
                        "price_value": "500000",
                    }
                ],
            )

            assert [record["hotel_name"] for record in records] == ["Card Hotel"]
        finally:
            browser.close()


def test_broad_card_extraction_ignores_recommendation_inside_card_wrapper() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            card_url = "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html"
            page.set_content(
                '<main><article data-selenium="hotel-item">'
                f'<a aria-label="Card Hotel" href="{card_url}">Card Hotel</a>'
                '<span>500000 VND</span></article>'
                '<article><section class="recommendations">'
                '<a aria-label="Other Hotel" '
                'href="https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html">'
                'Other Hotel</a><span>600000 VND</span>'
                '</section></article></main>',
                wait_until="domcontentloaded",
            )

            records = extract_page_results(
                page,
                'article:has(a[href*="/hotel/"])',
                observed_records=[
                    {
                        "hotel_name": "Card Hotel",
                        "hotel_url": card_url,
                        "price_value": "500000",
                    }
                ],
            )

            assert [record["hotel_name"] for record in records] == ["Card Hotel"]
            assert [record["hotel_url"] for record in records] == [card_url]
        finally:
            browser.close()


def test_broad_card_extraction_uses_only_eligible_subtree_for_mixed_card() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            card_url = (
                "https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html?propertyId=111"
            )
            page.set_content(
                '<main><article data-selenium="hotel-item" data-hotelid="111">'
                '<section class="recommendations">'
                '<a aria-label="Other Hotel" '
                'href="https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html?propertyId=222">'
                'Other Hotel</a><span>600000 VND</span><img alt="Other Image"></section>'
                '<h3 data-selenium="hotel-name">Card Hotel</h3>'
                f'<a aria-label="Card Hotel" href="{card_url}">Card Hotel</a>'
                '<span style="display:none">900000 VND</span>'
                '<span>500000 VND</span></article></main>',
                wait_until="domcontentloaded",
            )

            records = extract_page_results(
                page,
                'article:has(a[href*="/hotel/"])',
                observed_records=[
                    {
                        "hotel_name": "Card Hotel",
                        "hotel_url": card_url,
                        "listing_property_id": "111",
                        "price_value": "500000",
                    }
                ],
            )

            assert len(records) == 1
            assert records[0]["hotel_name"] == "Card Hotel"
            assert records[0]["hotel_url"] == card_url
            assert records[0]["price_value"] == "500000"
        finally:
            browser.close()


def test_broad_card_extraction_excludes_recommendation_text_in_hotel_anchor() -> None:
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

            records = extract_page_results(
                page,
                'article:has(a[href*="/hotel/"])',
                observed_records=[
                    {"hotel_name": "Card Hotel", "hotel_url": hotel_url}
                ],
            )

            assert len(records) == 1
            assert records[0]["hotel_name"] == "Card Hotel"
            assert records[0]["hotel_url"] == hotel_url
        finally:
            browser.close()


def test_broad_card_extraction_supplements_observed_identity_outside_root() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            other_url = "https://www.agoda.com/vi-vn/other/hotel/vung-tau-vn.html"
            page.set_content(
                '<main id="search-results"><article data-selenium="hotel-item">'
                '<a aria-label="Card Hotel" '
                'href="https://www.agoda.com/vi-vn/card/hotel/vung-tau-vn.html">'
                'Card Hotel</a><span>500000 VND</span></article></main>'
                '<section><h2>Recent properties</h2><article>'
                f'<a aria-label="Other Hotel" href="{other_url}">Other Hotel</a>'
                '<span>600000 VND</span></article></section>',
                wait_until="domcontentloaded",
            )

            records = extract_page_results(
                page,
                'article:has(a[href*="/hotel/"])',
                observed_records=[
                    {"hotel_name": "Other Hotel", "hotel_url": other_url}
                ],
            )

            assert {record["hotel_name"] for record in records} == {
                "Card Hotel",
                "Other Hotel",
            }
        finally:
            browser.close()


def test_name_from_hotel_url_uses_slug_before_hotel_path() -> None:
    assert (
        _name_from_hotel_url("https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html")
        == "Demo Hotel"
    )


def test_detail_text_parsers_handle_vietnamese_review_and_stars() -> None:
    text = "Diem danh gia co so luu tru: 8,3/10 Tuyet voi 1.357 bai danh gia"
    star = "4 sao tren 5"

    parsed = _parse_textual_fallback(text)

    assert parsed["rating_text"] == "8.3"
    assert _parse_review_count(text) == "1.357"
    assert _parse_star_rating(star) == "4 stars"


def test_textual_fallback_returns_empty_values_for_blank_text() -> None:
    parsed = _parse_textual_fallback("")

    assert parsed["price_value"] is None
