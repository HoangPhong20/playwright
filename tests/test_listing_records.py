from agoda_crawler.listing.records import merge_page_record, merge_records_into_results


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


def test_merge_records_keeps_distinct_property_ids_on_the_same_path() -> None:
    records_by_key = {}

    expected = {"111": ("500000", "8.1"), "222": ("700000", "9.2")}
    for property_id, (price, rating) in expected.items():
        record = {
            "hotel_name": "Same Display Name",
            "hotel_url": (
                "https://www.agoda.com/vi-vn/demo-city/vung-tau"
                f"?propertyId={property_id}"
            ),
            "price_value": price,
            "rating_text": rating,
        }
        merge_page_record(records_by_key, record)

    assert len(records_by_key) == 2
    actual = {
        record["canonical_url"].rsplit("=", 1)[-1]: (
            record["price_value"],
            record["rating_text"],
        )
        for record in records_by_key.values()
    }
    assert actual == expected


def test_merge_records_does_not_join_same_name_with_conflicting_property_ids() -> None:
    records_by_key = {}
    merge_page_record(
        records_by_key,
        {
            "hotel_name": "Same Display Name",
            "listing_property_id": "111",
            "hotel_url": "https://www.agoda.com/vi-vn/first/hotel/first.html",
            "price_value": "500000",
        },
    )
    merge_page_record(
        records_by_key,
        {
            "hotel_name": "Same Display Name",
            "listing_property_id": "222",
            "hotel_url": "https://www.agoda.com/vi-vn/second/hotel/second.html",
            "price_value": "700000",
        },
    )

    assert len(records_by_key) == 2
    assert {record["listing_property_id"] for record in records_by_key.values()} == {"111", "222"}


def test_conflicting_property_ids_do_not_merge_even_when_url_is_the_same() -> None:
    records_by_key = {}
    shared_url = "https://www.agoda.com/vi-vn/shared/hotel/shared.html"

    for property_id, price in (("111", "500000"), ("222", "700000")):
        merge_page_record(
            records_by_key,
            {
                "hotel_name": "Same Display Name",
                "listing_property_id": property_id,
                "hotel_url": shared_url,
                "price_value": price,
            },
        )

    assert len(records_by_key) == 2
    assert {record["listing_property_id"] for record in records_by_key.values()} == {"111", "222"}
    assert {record["price_value"] for record in records_by_key.values()} == {"500000", "700000"}


def test_merge_full_record_then_partial_observation_keeps_one_complete_record() -> None:
    records_by_key = {}
    full_record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/vi-vn/demo-city/vung-tau?propertyId=111",
        "price_value": "500000",
    }
    merge_page_record(records_by_key, full_record)

    merge_page_record(
        records_by_key,
        {
            "hotel_name": "Demo Hotel",
            "listing_property_id": "111",
            "hotel_url": None,
            "price_value": None,
            "partial_debug": {"reason": "later partial card"},
        },
    )

    assert len(records_by_key) == 1
    merged = next(iter(records_by_key.values()))
    assert merged["hotel_url"] == full_record["hotel_url"]
    assert merged["price_value"] == "500000"
    assert merged["canonical_url"].endswith("?propertyId=111")
    assert merged["collect_status"] == "ok"
    assert merged["collect_error"] is None
    assert merged["record_kind"] == "full_record"
    assert "partial_debug" not in merged


def test_merge_name_fallback_upgrades_only_one_unidentified_partial() -> None:
    records_by_key = {
        "partial:demo hotel": {
            "hotel_name": "Demo Hotel",
            "hotel_url": None,
            "price_value": "500000",
        }
    }

    merge_page_record(
        records_by_key,
        {
            "hotel_name": "Demo Hotel",
            "hotel_url": "https://www.agoda.com/vi-vn/demo/hotel/demo.html",
            "price_value": None,
        },
    )

    assert len(records_by_key) == 1
    assert next(iter(records_by_key.values()))["price_value"] == "500000"
