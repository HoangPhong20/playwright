from agoda_crawler.extraction import (
    _hotel_url_key,
    _name_from_hotel_url,
    extract_fast_hotel_links,
    _looks_like_city_landing_shell,
    _parse_review_count,
    _canonicalize_price_value,
    _price_value_from_text,
    _parse_star_rating,
    _normalize_location_text,
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


def test_price_value_from_text_prefers_discounted_per_night_price() -> None:
    text = "Gia Goc: 2.419.171 ₫ 2.419.171 ₫ -71% 702.050 ₫ Moi dem, chua co thue"

    assert _price_value_from_text(text) == "702050"


def test_price_value_from_text_does_not_treat_vietnamese_d_as_prefix_currency() -> None:
    text = "Đặt gói để tiết kiệm! 10 tháng 6 2026 từ 673.391 ₫ Xem giá"

    assert _price_value_from_text(text) == "673391"


def test_hotel_url_key_ignores_query_and_fragment() -> None:
    first = (
        "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html"
        "?searchrequestid=aaa&tspTypes=8#rooms"
    )
    second = (
        "https://www.agoda.com/vi-vn/demo-hotel/hotel/vung-tau-vn.html"
        "?searchrequestid=bbb&tspTypes=1"
    )

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

    def evaluate(self, script: str):
        return [
            {
                "href": "/vi-vn/demo/hotel/vung-tau-vn.html?cid=1",
                "text": " Demo Hotel ",
                "imageUrl": "/demo.jpg",
            },
            {
                "href": "/vi-vn/demo/hotel/vung-tau-vn.html?cid=2",
                "text": "Duplicate Demo Hotel",
                "imageUrl": "",
            },
        ]


def test_extract_fast_hotel_links_dedupes_by_hotel_url() -> None:
    records = extract_fast_hotel_links(_FastLinksPage(), 1)

    assert len(records) == 1
    assert records[0]["hotel_name"] == "Demo Hotel"
    assert records[0]["hotel_url"] == "https://www.agoda.com/vi-vn/demo/hotel/vung-tau-vn.html?cid=1"
    assert records[0]["image_url"] == "https://www.agoda.com/demo.jpg"


class _FastLinksWithoutTextPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str):
        return [
            {
                "href": "/vi-vn/the-song-vung-tau/hotel/vung-tau-vn.html?cid=1",
                "text": "",
                "imageUrl": "",
            },
        ]


def test_extract_fast_hotel_links_keeps_urls_without_visible_text() -> None:
    records = extract_fast_hotel_links(_FastLinksWithoutTextPage(), 1)

    assert len(records) == 1
    assert records[0]["hotel_name"] == "The Song Vung Tau"


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


def test_normalize_location_text_drops_repeated_ward_chunk() -> None:
    raw = "252 Duong Ba Cu Phuong 3, Phường 3, Vung Tau, Viet Nam"

    normalized = _normalize_location_text(raw)

    assert normalized == "252 Duong Ba Cu Phuong 3, Vung Tau, Viet Nam"
