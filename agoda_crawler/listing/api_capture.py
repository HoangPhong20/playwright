"""Capture structured hotel hints from Agoda listing API responses."""

from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional

from playwright.sync_api import Page

from agoda_crawler.extraction.parsers import (
    canonicalize_price_value,
    normalize_review_score,
    parse_review_count,
    price_value_from_text,
)
from agoda_crawler.utils import compact_text


PROPERTY_ID_KEYS = {
    "hotelid",
    "hotel_id",
    "propertyid",
    "property_id",
    "accommodationid",
    "accommodation_id",
}
URL_KEYS = {
    "hotelurl",
    "hotel_url",
    "propertyurl",
    "property_url",
    "landingurl",
    "landing_url",
    "detailurl",
    "detail_url",
    "pageurl",
    "page_url",
    "url",
}
NAME_KEYS = {
    "hotelname",
    "hotel_name",
    "propertyname",
    "property_name",
    "accommodationname",
    "accommodation_name",
    "displayname",
    "display_name",
    "name",
}
PRICE_KEYS = {
    "price",
    "pricevalue",
    "price_value",
    "displayprice",
    "display_price",
    "finalprice",
    "final_price",
    "roomprice",
    "room_price",
    "averageprice",
    "average_price",
    "totalprice",
    "total_price",
}
RATING_KEYS = {
    "ratingscore",
    "rating_score",
    "reviewscore",
    "review_score",
    "score",
    "rating",
}
REVIEW_COUNT_KEYS = {
    "reviewcount",
    "review_count",
    "numberofreviews",
    "number_of_reviews",
    "reviews",
}
IMAGE_KEYS = {
    "image",
    "imageurl",
    "image_url",
    "mainimage",
    "main_image",
    "mainimageurl",
    "main_image_url",
    "thumbnail",
    "thumbnailurl",
    "thumbnail_url",
    "photo",
    "photourl",
    "photo_url",
    "picture",
    "pictureurl",
    "picture_url",
}


class ListingApiCapture:
    """Collect property-level hints from Playwright response events."""

    def __init__(self, max_responses: int = 80, max_properties: int = 2_000) -> None:
        self.max_responses = max_responses
        self.max_properties = max_properties
        self._lock = threading.Lock()
        self._response_count = 0
        self._json_response_count = 0
        self._properties: Dict[str, Dict[str, str]] = {}

    def attach(self, page: Page) -> None:
        page.on("response", self._handle_response)

    def property_map(self) -> Dict[str, Dict[str, str]]:
        with self._lock:
            return {key: dict(value) for key, value in self._properties.items()}

    def metrics(self) -> Dict[str, int]:
        with self._lock:
            url_count = sum(1 for value in self._properties.values() if value.get("hotel_url"))
            return {
                "api_response_count": self._response_count,
                "api_json_response_count": self._json_response_count,
                "api_property_count": len(self._properties),
                "api_url_count": url_count,
            }

    def _handle_response(self, response) -> None:
        if not _is_relevant_response(response):
            return

        with self._lock:
            if self._response_count >= self.max_responses:
                return
            self._response_count += 1

        try:
            payload = response.json()
        except Exception:
            return

        found = extract_property_records(payload, response.url)
        if not found:
            return

        with self._lock:
            self._json_response_count += 1
            for property_id, data in found.items():
                existing = self._properties.setdefault(property_id, {"source": data["source"]})
                for field, value in data.items():
                    if value and not existing.get(field):
                        existing[field] = value
                if len(self._properties) >= self.max_properties:
                    break


def extract_property_records(payload: Any, source_url: str = "api_response") -> Dict[str, Dict[str, str]]:
    records: Dict[str, Dict[str, str]] = {}
    for item in _iter_dicts(payload):
        property_id = _property_id_from_dict(item)
        if not property_id:
            continue
        extracted = _extract_property_data(item, source_url)
        if not any(value for field, value in extracted.items() if field != "source"):
            continue
        existing = records.setdefault(property_id, {"source": extracted["source"]})
        for field, value in extracted.items():
            if value and not existing.get(field):
                existing[field] = value
    return records


def _extract_property_data(item: Dict[str, Any], source_url: str) -> Dict[str, str]:
    hotel_url = _hotel_url_from_dict(item)
    hotel_name = _first_value_for_keys(item, NAME_KEYS)
    price_value = _price_from_dict(item)
    rating_text = _rating_from_dict(item)
    review_count_text = _review_count_from_dict(item)
    image_url = _image_url_from_dict(item)
    return {
        "hotel_url": hotel_url or "",
        "hotel_name": hotel_name or "",
        "price_value": price_value or "",
        "rating_text": rating_text or "",
        "review_count_text": review_count_text or "",
        "image_url": image_url or "",
        "source": f"api_response:{source_url}",
    }


def _is_relevant_response(response) -> bool:
    url = (getattr(response, "url", "") or "").lower()
    if "agoda" not in url:
        return False
    if not any(token in url for token in ("search", "property", "hotel", "graphql", "api", "mse")):
        return False
    content_type = ""
    try:
        content_type = (response.headers or {}).get("content-type", "").lower()
    except Exception:
        content_type = ""
    return not content_type or "json" in content_type or "javascript" in content_type


def _iter_dicts(value: Any) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            results.append(current)
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return results


def _property_id_from_dict(item: Dict[str, Any]) -> Optional[str]:
    for key, value in item.items():
        if _normalized_key(key) not in PROPERTY_ID_KEYS:
            continue
        text = compact_text(str(value)) if value is not None else None
        if not text:
            continue
        match = re.search(r"\d+", text)
        return match.group(0) if match else text
    return None


def _hotel_url_from_dict(item: Dict[str, Any]) -> Optional[str]:
    for key, value in item.items():
        if _normalized_key(key) not in URL_KEYS:
            continue
        raw = _string_value(value)
        if raw and "/hotel/" in raw.lower():
            return raw
    for raw in _hotel_urls_from_value(item):
        return raw
    return None


def _price_from_dict(item: Dict[str, Any]) -> Optional[str]:
    for key, value in _iter_key_values(item):
        normalized_key = _normalized_key(key)
        if normalized_key not in PRICE_KEYS and "price" not in normalized_key:
            continue
        parsed = _parse_price_value(value)
        if parsed:
            return parsed
    return None


def _rating_from_dict(item: Dict[str, Any]) -> Optional[str]:
    for key, value in _iter_key_values(item):
        normalized_key = _normalized_key(key)
        if normalized_key not in RATING_KEYS and "reviewscore" not in normalized_key:
            continue
        parsed = _parse_rating_value(value)
        if parsed:
            return parsed
    return None


def _review_count_from_dict(item: Dict[str, Any]) -> Optional[str]:
    for key, value in _iter_key_values(item):
        normalized_key = _normalized_key(key)
        if normalized_key not in REVIEW_COUNT_KEYS and not (
            "review" in normalized_key and "count" in normalized_key
        ):
            continue
        parsed = _parse_review_count_value(value)
        if parsed:
            return parsed
    return None


def _image_url_from_dict(item: Dict[str, Any]) -> Optional[str]:
    for key, value in _iter_key_values(item):
        normalized_key = _normalized_key(key)
        if normalized_key not in IMAGE_KEYS and not any(
            token in normalized_key
            for token in ("image", "thumbnail", "photo", "picture")
        ):
            continue
        parsed = _parse_image_url_value(value)
        if parsed:
            return parsed
        parsed = _image_url_from_nested_value(value)
        if parsed:
            return parsed
    return None


def _iter_key_values(value: Any):
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                yield key, child
                if isinstance(child, (dict, list)):
                    stack.append(child)
        elif isinstance(current, list):
            stack.extend(current)


def _first_value_for_keys(item: Dict[str, Any], keys: set[str]) -> Optional[str]:
    for key, value in item.items():
        if _normalized_key(key) not in keys:
            continue
        text = _string_value(value)
        if text:
            return text
    return None


def _hotel_urls_from_value(value: Any) -> List[str]:
    urls: List[str] = []
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        else:
            text = _string_value(current)
            if not text or "/hotel/" not in text.lower():
                continue
            urls.extend(_hotel_url_patterns(text))
    return urls


def _hotel_url_patterns(text: str) -> List[str]:
    patterns = [
        r"https?://(?:www\.)?agoda\.com/[^\"'<>\\\s{}\[\]]+?/hotel/(?:all/)?[^\"'<>\\\s{}\[\]]+?\.html(?:\?[^\"'<>\\\s{}\[\]]*)?",
        r"/[a-z]{2}-[a-z]{2}/[^\"'<>\\\s{}\[\]]+?/hotel/(?:all/)?[^\"'<>\\\s{}\[\]]+?\.html(?:\?[^\"'<>\\\s{}\[\]]*)?",
        r"/[^\"'<>\\\s{}\[\]]+?/hotel/(?:all/)?[^\"'<>\\\s{}\[\]]+?\.html(?:\?[^\"'<>\\\s{}\[\]]*)?",
    ]
    urls: List[str] = []
    for pattern in patterns:
        urls.extend(match.group(0).rstrip(".,);") for match in re.finditer(pattern, text, re.I))
    return urls


def _parse_price_value(value: Any) -> Optional[str]:
    if isinstance(value, (int, float)) and value >= 1000:
        return str(int(value))
    text = _string_value(value)
    if not text:
        return None
    return canonicalize_price_value(text) or price_value_from_text(text)


def _parse_rating_value(value: Any) -> Optional[str]:
    if isinstance(value, (int, float)):
        return normalize_review_score(str(value))
    text = _string_value(value)
    if not text:
        return None
    return normalize_review_score(text)


def _parse_review_count_value(value: Any) -> Optional[str]:
    if isinstance(value, int) and value >= 0:
        return str(value)
    text = _string_value(value)
    if not text:
        return None
    if text.isdigit():
        return text
    return parse_review_count(text)


def _parse_image_url_value(value: Any) -> Optional[str]:
    text = _string_value(value)
    if not text:
        return None
    candidates = re.findall(
        r"https?://[^\"'<>\\\s{}\[\]]+|/[^\"'<>\\\s{}\[\]]+",
        text,
        flags=re.IGNORECASE,
    )
    if not candidates:
        candidates = [text]
    for candidate in candidates:
        cleaned = candidate.rstrip(".,);")
        lowered = cleaned.lower()
        if (
            "hotelimages" in lowered
            or "agoda.net" in lowered
            or "pix" in lowered
            or re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", lowered)
        ):
            return cleaned
    return None


def _image_url_from_nested_value(value: Any) -> Optional[str]:
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            stack.extend(current.values())
            continue
        if isinstance(current, list):
            stack.extend(current)
            continue
        parsed = _parse_image_url_value(current)
        if parsed:
            return parsed
    return None


def _string_value(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return compact_text(value)
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())
