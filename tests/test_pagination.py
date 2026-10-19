from agoda_crawler.listing.pagination import (
    capture_pagination_state,
    pagination_change_evidence,
    pagination_end_reason,
)


def test_pagination_end_reason_accepts_visible_disabled_next_control() -> None:
    assert pagination_end_reason(
        {"visible_next_count": 1, "next_disabled": True, "pagination_text": "1 of 3"}
    ) == "next_control_disabled"


def test_enabled_visible_next_defeats_stale_page_count() -> None:
    assert pagination_end_reason(
        {"visible_next_count": 1, "next_disabled": False, "pagination_text": "1 of 1"}
    ) is None


def test_pagination_end_reason_requires_positive_exact_page_count() -> None:
    assert pagination_end_reason({"pagination_text": "Page 5 of 5"}) == "page_count_reached"
    assert pagination_end_reason({"pagination_text": "Page 0 of 0"}) is None
    assert pagination_end_reason({"pagination_text": "Page 6 of 5"}) is None
    assert pagination_end_reason({"pagination_text": "Page 1 of 5"}) is None


def test_missing_pagination_evidence_is_not_end_of_results() -> None:
    assert pagination_end_reason({}) is None


class _PaginationPage:
    url = "https://www.agoda.com/vi-vn/search?city=17190"

    def evaluate(self, script: str, *args):
        if "window.scrollY" in script:
            return 0
        return ""


def test_pagination_identity_detects_property_id_change_on_shared_path() -> None:
    page = _PaginationPage()
    first = capture_pagination_state(
        page,
        1,
        records=[
            {
                "hotel_url": "https://www.agoda.com/vi-vn/shared-city/vung-tau?propertyId=111"
            }
        ],
    )
    second = capture_pagination_state(
        page,
        2,
        records=[
            {
                "hotel_url": "https://www.agoda.com/vi-vn/shared-city/vung-tau?propertyId=222"
            }
        ],
    )

    evidence = pagination_change_evidence(first, second)

    assert evidence["signs"]["canonical_url_set_changed"] is True
    assert first.canonical_urls != second.canonical_urls
