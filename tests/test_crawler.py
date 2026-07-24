import pytest

from agoda_crawler.crawler import (
    _merge_missing_fields,
    _mark_price_coverage_status,
    _needs_detail_enrichment,
    _is_low_new_record_page,
    _reached_page_limit,
    _should_retry_duplicate_page,
    _validate_supported_occupancy,
    _with_stay_params,
    crawl_agoda_search,
)


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
