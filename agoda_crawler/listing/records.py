"""Record identity and merge helpers for listing crawls."""
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlparse

from agoda_crawler.extraction.parsers import hotel_url_key
from agoda_crawler.utils import merge_missing_fields


def record_key(record: Dict) -> str:
    hotel_url = record.get("hotel_url") or record.get("canonical_url")
    if hotel_url:
        return f"url:{hotel_url_key(hotel_url)}"

    property_id = property_identity_value(record)
    if property_id:
        return f"property:{property_id}"

    name = (record.get("hotel_name") or "").strip().casefold()
    if name:
        return f"partial:{name}"

    page_number = record.get("_listing_page") or 0
    source_card_index = record.get("source_card_index")
    snippet = (record.get("listing_text_snippet") or "").strip().casefold()
    return f"partial:{page_number}:{source_card_index}:{snippet[:120]}"


def merge_page_record(records_by_key: Dict[str, Dict], record: Dict) -> bool:
    key = record_key(record)
    matching_keys = _matching_record_keys(records_by_key, record, key)
    if not matching_keys:
        _refresh_record_identity(record)
        records_by_key[_available_record_key(records_by_key, record)] = record
        return True

    existing_records = [records_by_key.pop(match_key) for match_key in matching_keys]
    primary = _choose_primary_record(existing_records, record)
    merge_order = [*existing_records, record]
    if primary is record:
        merge_order = [record, *existing_records]

    changed = False
    for other in merge_order:
        if other is primary:
            continue
        changed = _merge_record_fields(primary, other) or changed

    _refresh_record_identity(primary)
    new_key = record_key(primary)
    if new_key in records_by_key:
        other = records_by_key[new_key]
        primary_id = property_identity_value(primary)
        other_id = property_identity_value(other)
        if primary_id and other_id and primary_id != other_id:
            new_key = _available_record_key(records_by_key, primary)
        else:
            # The canonical URL may already have an entry under an older alias.
            records_by_key.pop(new_key)
            changed = _merge_record_fields(primary, other) or changed
            _refresh_record_identity(primary)
            new_key = record_key(primary)
    records_by_key[new_key] = primary
    return changed or len(matching_keys) > 1 or any(
        match_key != new_key for match_key in matching_keys
    )


def merge_records_into_results(records_by_key: Dict[str, Dict], records: List[Dict]) -> int:
    before_total = len(records_by_key)
    for record in records:
        merge_page_record(records_by_key, record)
    return len(records_by_key) - before_total


def partial_identity_key(record: Dict) -> Optional[str]:
    if not record.get("hotel_name"):
        return None
    name = (record.get("hotel_name") or "").strip().casefold()
    return f"partial:{name}"


def property_identity_key(record: Dict) -> Optional[str]:
    property_id = property_identity_value(record)
    return f"property:{property_id}" if property_id else None


def property_identity_value(record: Dict) -> Optional[str]:
    property_id = (record.get("listing_property_id") or "").strip()
    if property_id:
        return property_id

    hotel_url = record.get("hotel_url") or record.get("canonical_url") or ""
    values = [
        value
        for key, value in parse_qsl(urlparse(hotel_url).query, keep_blank_values=True)
        if key.casefold() == "propertyid"
    ]
    if len(values) == 1 and values[0].isdigit():
        return values[0]
    return None


def records_with_url_count(records_by_key: Dict[str, Dict]) -> int:
    return sum(1 for record in records_by_key.values() if record.get("hotel_url"))


def _matching_record_keys(records_by_key: Dict[str, Dict], record: Dict, key: str) -> List[str]:
    matching_keys = []
    incoming_id = property_identity_value(record)
    direct_match = records_by_key.get(key)
    direct_id = property_identity_value(direct_match) if direct_match else None
    if key in records_by_key and not (incoming_id and direct_id and incoming_id != direct_id):
        matching_keys.append(key)

    property_id = incoming_id
    if property_id:
        for existing_key, existing in records_by_key.items():
            if property_identity_value(existing) == property_id and existing_key not in matching_keys:
                matching_keys.append(existing_key)
    if matching_keys:
        return matching_keys

    name = (record.get("hotel_name") or "").strip().casefold()
    if not name:
        return []

    incoming_has_strong_identity = bool(record.get("hotel_url") or incoming_id)
    name_matches = []
    for existing_key, existing in records_by_key.items():
        existing_name = (existing.get("hotel_name") or "").strip().casefold()
        if existing_name != name:
            continue

        existing_id = property_identity_value(existing)
        if incoming_id and existing_id and incoming_id != existing_id:
            continue
        existing_has_strong_identity = bool(existing.get("hotel_url") or existing_id)
        if incoming_has_strong_identity and existing_has_strong_identity:
            continue
        name_matches.append(existing_key)

    return name_matches if len(name_matches) == 1 else []


def _available_record_key(records_by_key: Dict[str, Dict], record: Dict) -> str:
    key = record_key(record)
    existing = records_by_key.get(key)
    incoming_id = property_identity_value(record)
    existing_id = property_identity_value(existing) if existing else None
    if existing and incoming_id and existing_id and incoming_id != existing_id:
        return f"{key}|property:{incoming_id}"
    return key


def _choose_primary_record(existing_records: List[Dict], incoming: Dict) -> Dict:
    for existing in existing_records:
        if existing.get("hotel_url"):
            return existing
    if incoming.get("hotel_url"):
        return incoming
    return existing_records[0]


def _merge_record_fields(record: Dict, other: Dict) -> bool:
    changed = merge_missing_fields(record, other)
    for field_name in ("candidate_urls", "raw_candidate_urls"):
        values = list(record.get(field_name) or [])
        for value in other.get(field_name) or []:
            if value not in values:
                values.append(value)
                changed = True
        if values and values != record.get(field_name):
            record[field_name] = values
            changed = True
    return changed


def _refresh_record_identity(record: Dict) -> None:
    hotel_url = record.get("hotel_url")
    canonical_url = hotel_url_key(hotel_url) if hotel_url else None
    record["canonical_url"] = canonical_url

    missing = []
    if not hotel_url:
        missing.append("missing_url")
    if not record.get("hotel_name"):
        missing.append("missing_name")
    status = "ok" if not missing else ",".join(missing)
    record["collect_status"] = status
    record["collect_error"] = None if status == "ok" else status
    record["record_kind"] = "full_record" if hotel_url else "partial_missing_url"
    if hotel_url:
        record.pop("partial_debug", None)
