from agoda_crawler.extraction import (
    _hotel_url_key,
    _name_from_hotel_url,
    extract_fast_hotel_links,
    _parse_review_count,
    _canonicalize_price_value,
    _price_value_from_text,
    _record_key,
    _parse_textual_fallback,
)
from agoda_crawler.extraction.fields import (
    FIELD_SELECTOR_TIMEOUT,
    extract_detail_fields,
    extract_from_cards,
    first_text,
)
from agoda_crawler.extraction.selectors import FIELD_SELECTORS


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


def test_detail_text_parsers_handle_vietnamese_review_count() -> None:
    text = "Diem danh gia co so luu tru: 8,3/10 Tuyet voi 1.357 bai danh gia"

    parsed = _parse_textual_fallback(text)

    assert parsed["rating_text"] == "8.3"
    assert _parse_review_count(text) == "1.357"


class _FieldLocator:
    def __init__(self, text: str | None = None, attrs: dict[str, str] | None = None) -> None:
        self.text = text
        self.attrs = attrs or {}
        self.inner_text_timeouts = []
        self.attribute_timeouts = []

    @property
    def first(self):
        return self

    def count(self) -> int:
        return 1 if self.text is not None or self.attrs else 0

    def inner_text(self, timeout: int) -> str:
        self.inner_text_timeouts.append(timeout)
        return self.text or ""

    def get_attribute(self, attr: str, timeout: int):
        self.attribute_timeouts.append((attr, timeout))
        return self.attrs.get(attr)


class _ExtractionCard:
    def __init__(
        self,
        raise_on_scroll: bool = False,
        raise_on_inner_text: bool = False,
    ) -> None:
        self.raise_on_scroll = raise_on_scroll
        self.raise_on_inner_text = raise_on_inner_text
        self.scroll_timeouts = []
        self.locators: dict[str, _FieldLocator] = {
            FIELD_SELECTORS["hotel_name"][0]: _FieldLocator("Demo Hotel"),
            FIELD_SELECTORS["hotel_link"][0]: _FieldLocator(attrs={"href": "/demo/hotel/demo.html"}),
            FIELD_SELECTORS["price_value"][0]: _FieldLocator("VND 1000000"),
            FIELD_SELECTORS["rating_text"][0]: _FieldLocator("8.5"),
            FIELD_SELECTORS["review_count_text"][0]: _FieldLocator("120 reviews"),
        }

    def locator(self, selector: str) -> _FieldLocator:
        return self.locators.get(selector, _FieldLocator())

    def inner_text(self, timeout: int) -> str:
        if self.raise_on_inner_text:
            raise TimeoutError("card text timed out")
        return "Demo Hotel VND 1000000 8.5 120 reviews"

    def scroll_into_view_if_needed(self, timeout: int) -> None:
        self.scroll_timeouts.append(timeout)
        if self.raise_on_scroll:
            raise RuntimeError("cannot scroll")


class _CardsLocator:
    def __init__(self, cards: list[_ExtractionCard]) -> None:
        self.cards = cards

    def count(self) -> int:
        return len(self.cards)

    def nth(self, index: int) -> _ExtractionCard:
        return self.cards[index]


class _CardsPage:
    url = "https://www.agoda.com/vi-vn/search"

    def __init__(self, cards: list[_ExtractionCard]) -> None:
        self.cards = cards

    def locator(self, selector: str) -> _CardsLocator:
        return _CardsLocator(self.cards)


def test_first_text_uses_field_selector_timeout() -> None:
    locator = _FieldLocator("Demo Hotel")

    class Root:
        def locator(self, selector: str) -> _FieldLocator:
            return locator

    assert first_text(Root(), ["h3"]) == "Demo Hotel"
    assert locator.inner_text_timeouts == [FIELD_SELECTOR_TIMEOUT]


def test_extract_from_cards_scrolls_each_card_and_keeps_record_on_scroll_failure() -> None:
    card = _ExtractionCard(raise_on_scroll=True)

    records = extract_from_cards(_CardsPage([card]), '[data-testid="property-card"]', 1)

    assert card.scroll_timeouts
    assert records[0]["hotel_name"] == "Demo Hotel"


def test_extract_from_cards_keeps_record_when_card_text_times_out() -> None:
    card = _ExtractionCard(raise_on_inner_text=True)

    records = extract_from_cards(_CardsPage([card]), '[data-testid="property-card"]', 1)

    assert records[0]["hotel_name"] == "Demo Hotel"
    assert records[0]["price_value"] == "1000000"


def test_extract_from_cards_skips_one_broken_card() -> None:
    class BrokenCard:
        def scroll_into_view_if_needed(self, timeout: int) -> None:
            pass

        def locator(self, selector: str):
            raise RuntimeError("detached card")

    records = extract_from_cards(
        _CardsPage([BrokenCard(), _ExtractionCard()]),
        '[data-testid="property-card"]',
        1,
    )

    assert len(records) == 1
    assert records[0]["hotel_name"] == "Demo Hotel"


class _DetailElement:
    def __init__(self, text: str = "", attrs: dict[str, str] | None = None) -> None:
        self.text = text
        self.attrs = attrs or {}

    @property
    def first(self):
        return self

    def count(self) -> int:
        return 1

    def nth(self, _index: int):
        return self

    def inner_text(self, timeout: int) -> str:
        return self.text

    def get_attribute(self, attr: str, timeout: int):
        return self.attrs.get(attr)


class _EmptyDetailLocator:
    @property
    def first(self):
        return self

    def count(self) -> int:
        return 0

    def nth(self, _index: int):
        return self

    def inner_text(self, timeout: int) -> str:
        return ""

    def get_attribute(self, attr: str, timeout: int):
        return None


class _DetailListLocator:
    def __init__(self, elements: list[_DetailElement]) -> None:
        self.elements = elements

    @property
    def first(self):
        return self.elements[0] if self.elements else _EmptyDetailLocator()

    def count(self) -> int:
        return len(self.elements)

    def nth(self, index: int):
        return self.elements[index]


class _DetailPage:
    url = "https://www.agoda.com/demo/hotel/vung-tau-vn.html"

    def __init__(self, script_text: str) -> None:
        self.script_text = script_text

    def evaluate(self, script: str):
        if "document.scripts" in script:
            return [self.script_text]
        return None

    def locator(self, selector: str):
        if selector == "script":
            return _DetailListLocator([_DetailElement(self.script_text)])
        if selector == "body":
            return _DetailElement("Demo Hotel Tuyet voi 8,5 voi 120 bai danh gia")
        if selector == "img":
            return _DetailListLocator([])
        return _EmptyDetailLocator()


def test_extract_detail_fields_reads_price_from_script_state() -> None:
    fields = extract_detail_fields(
        _DetailPage('{"hotelName":"Demo","finalPrice":755000,"currencyCode":"VND"}')
    )

    assert fields["price_value"] == "755000"
