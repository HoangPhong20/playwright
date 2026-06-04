"""Record identity and merge helpers for listing crawls."""
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from agoda_crawler.enrichment.detail import merge_missing_fields


def record_key(record: Dict) -> str:
    canonical_url = record.get("canonical_url")
    if canonical_url:
        return f"url:{canonical_url}"

    hotel_url = record.get("hotel_url")
    if hotel_url:
        parsed = urlparse(hotel_url)
        path = parsed.path.rstrip("/").lower()
        return f"url:{urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, '', '', ''))}"

    property_id = (record.get("listing_property_id") or "").strip()
    if property_id:
        return f"property:{property_id}"

    name = (record.get("hotel_name") or "").strip().casefold()
    location = (record.get("location_text") or "").strip().casefold()
    if name:
        return f"partial:{name}|{location}"

    page_number = record.get("_listing_page") or 0
    source_card_index = record.get("source_card_index")
    snippet = (record.get("listing_text_snippet") or record.get("image_url") or "").strip().casefold()
    return f"partial:{page_number}:{source_card_index}:{snippet[:120]}"


def merge_page_record(records_by_key: Dict[str, Dict], record: Dict) -> bool:
    key = record_key(record)
    existing = records_by_key.get(key)
    if existing is None:
        partial_key = partial_identity_key(record)
        if key.startswith("url:") and partial_key:
            partial_record = records_by_key.pop(partial_key, None)
            if partial_record is not None:
                merge_missing_fields(record, partial_record)
        property_key = property_identity_key(record)
        if key.startswith("url:") and property_key:
            property_record = records_by_key.pop(property_key, None)
            if property_record is not None:
                merge_missing_fields(record, property_record)
        records_by_key[key] = record
        return True
    return merge_missing_fields(existing, record)


def merge_records_into_results(records_by_key: Dict[str, Dict], records: List[Dict]) -> int:
    before_total = len(records_by_key)
    for record in records:
        merge_page_record(records_by_key, record)
    return len(records_by_key) - before_total


def partial_identity_key(record: Dict) -> Optional[str]:
    if not record.get("hotel_name"):
        return None
    name = (record.get("hotel_name") or "").strip().casefold()
    location = (record.get("location_text") or "").strip().casefold()
    return f"partial:{name}|{location}"


def property_identity_key(record: Dict) -> Optional[str]:
    property_id = (record.get("listing_property_id") or "").strip()
    return f"property:{property_id}" if property_id else None


def records_with_url_count(records_by_key: Dict[str, Dict]) -> int:
    return sum(1 for record in records_by_key.values() if record.get("hotel_url"))
