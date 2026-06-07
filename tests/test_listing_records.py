from agoda_crawler.listing.records import merge_records_into_results


def test_merge_records_into_results_replaces_partial_with_url_record() -> None:
    records_by_key = {
        "partial:demo hotel": {
            "hotel_name": "Demo Hotel",
            "hotel_url": None,
            "price_value": "1000",
        }
    }

    new_count = merge_records_into_results(
        records_by_key,
        [
            {
                "hotel_name": "Demo Hotel",
                "hotel_url": "https://www.agoda.com/demo/hotel/demo-hotel.html",
                "canonical_url": "https://www.agoda.com/demo/hotel/demo-hotel.html",
                "price_value": None,
            }
        ],
    )

    assert new_count == 0
    assert list(records_by_key) == [
        "url:https://www.agoda.com/demo/hotel/demo-hotel.html"
    ]
    assert records_by_key[
        "url:https://www.agoda.com/demo/hotel/demo-hotel.html"
    ]["price_value"] == "1000"


def test_merge_records_into_results_replaces_property_record_with_url_record() -> None:
    records_by_key = {
        "property:123": {
            "hotel_name": "Demo Hotel",
            "hotel_url": None,
            "listing_property_id": "123",
            "rating_text": "9.0",
        }
    }

    new_count = merge_records_into_results(
        records_by_key,
        [
            {
                "hotel_name": "Demo Hotel",
                "hotel_url": "https://www.agoda.com/demo/hotel/demo-hotel.html",
                "canonical_url": "https://www.agoda.com/demo/hotel/demo-hotel.html",
                "listing_property_id": "123",
                "rating_text": None,
            }
        ],
    )

    assert new_count == 0
    assert list(records_by_key) == [
        "url:https://www.agoda.com/demo/hotel/demo-hotel.html"
    ]
    assert records_by_key[
        "url:https://www.agoda.com/demo/hotel/demo-hotel.html"
    ]["rating_text"] == "9.0"
