from agoda_crawler.listing.api_capture import extract_property_records


def test_extract_property_records_reads_url_price_and_rating() -> None:
    payload = {
        "results": [
            {
                "hotelId": "123",
                "hotelName": "API Hotel",
                "hotelUrl": "/vi-vn/api-hotel/hotel/vung-tau-vn.html?cid=1",
                "displayPrice": "VND 1,200,000",
                "reviewScore": 8.7,
                "reviewCount": 321,
                "mainImageUrl": "https://pix6.agoda.net/hotelImages/123/123.jpg",
            }
        ]
    }

    records = extract_property_records(payload, "https://www.agoda.com/api/search")

    assert records["123"]["hotel_url"] == "/vi-vn/api-hotel/hotel/vung-tau-vn.html?cid=1"
    assert records["123"]["hotel_name"] == "API Hotel"
    assert records["123"]["price_value"] == "1200000"
    assert records["123"]["rating_text"] == "8.7"
    assert records["123"]["review_count_text"] == "321"
    assert records["123"]["image_url"] == "https://pix6.agoda.net/hotelImages/123/123.jpg"
    assert records["123"]["source"] == "api_response:https://www.agoda.com/api/search"


def test_extract_property_records_walks_nested_payload() -> None:
    payload = {
        "data": {
            "search": {
                "properties": [
                    {
                        "propertyId": 456,
                        "content": {
                            "landingUrl": "/vi-vn/nested-hotel/hotel/da-nang-vn.html",
                        },
                    }
                ]
            }
        }
    }

    records = extract_property_records(payload)

    assert records["456"]["hotel_url"] == "/vi-vn/nested-hotel/hotel/da-nang-vn.html"


def test_extract_property_records_reads_nested_price_fields() -> None:
    payload = {
        "results": [
            {
                "propertyId": "789",
                "propertyName": "Nested Price Hotel",
                "propertyUrl": "/vi-vn/nested-price/hotel/vung-tau-vn.html",
                "pricing": {
                    "room": {
                        "displayPrice": "VND 980,000",
                        "reviewScore": "8.6",
                        "reviewCount": "245 reviews",
                        "images": [
                            {
                                "url": "//pix6.agoda.net/hotelImages/789/789.webp",
                            }
                        ],
                    }
                },
            }
        ]
    }

    records = extract_property_records(payload)

    assert records["789"]["price_value"] == "980000"
    assert records["789"]["rating_text"] == "8.6"
    assert records["789"]["review_count_text"] == "245"
    assert records["789"]["image_url"] == "//pix6.agoda.net/hotelImages/789/789.webp"
