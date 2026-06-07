"""Fast listing-page hotel identity collection and diagnostics."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from playwright.sync_api import Page

from agoda_crawler.extraction import _empty_record
from agoda_crawler.extraction.parsers import (
    hotel_url_key as _hotel_url_key,
    name_from_hotel_url as _name_from_hotel_url,
    parse_textual_fallback as _parse_textual_fallback,
)
from agoda_crawler.utils import compact_text


TRACKING_QUERY_PREFIXES = (
    "utm_",
)
TRACKING_QUERY_KEYS = {
    "cid",
    "ds",
    "searchrequestid",
    "tag",
    "tspTypes",
    "countryId",
    "finalPriceView",
    "isShowMobileAppPrice",
    "numberOfBedrooms",
    "familyMode",
    "maxRooms",
    "isCalendarCallout",
    "childAges",
    "numberOfGuest",
    "missingChildAges",
    "travellerType",
    "showReviewSubmissionEntry",
    "currencyCode",
    "isFreeOccSearch",
}


@dataclass(frozen=True)
class ListingCollectionMetrics:
    dom_card_count: int = 0
    candidate_records: int = 0
    embedded_url_count: int = 0
    candidate_url_count: int = 0
    valid_url_count: int = 0
    unique_canonical_url_count: int = 0
    duplicate_url_count: int = 0
    unique_hotel_count: int = 0
    invalid_card_count: int = 0
    anchorless_card_count: int = 0
    cards_without_url_count: int = 0
    cards_without_name_count: int = 0
    scroll_y: int = 0
    invalid_card_samples: List[Dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ListingCollectionSnapshot:
    records: List[Dict]
    metrics: ListingCollectionMetrics


def normalize_hotel_url(raw_url: str, base_url: str) -> Optional[str]:
    """Resolve and normalize an Agoda hotel URL for stable hotel identity."""
    if not raw_url:
        return None

    url = urljoin(base_url, raw_url)
    split = urlsplit(url)
    if "/hotel/" not in split.path.lower():
        return None

    query = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        if key in TRACKING_QUERY_KEYS:
            continue
        if any(key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query.append((key, value))

    return urlunsplit(
        (
            split.scheme.lower(),
            split.netloc.lower(),
            split.path.rstrip("/"),
            urlencode(query, doseq=True),
            "",
        )
    )


def collect_listing_snapshot(
    page: Page,
    card_selector: str,
    page_number: int,
    include_embedded: bool = True,
    include_broad_selectors: bool = True,
) -> ListingCollectionSnapshot:
    """Collect hotel identity candidates quickly from the current listing DOM."""
    raw_cards = _evaluate_listing_dom(
        page,
        card_selector,
        include_broad_selectors=include_broad_selectors,
    )
    embedded_cards = _evaluate_embedded_hotel_url_cards(page) if include_embedded else []
    candidate_cards = raw_cards + embedded_cards
    records_by_key: Dict[str, Dict] = {}
    valid_url_count = 0
    candidate_url_count = 0
    cards_without_url_count = 0
    cards_without_name_count = 0
    invalid_card_count = 0
    anchorless_card_count = 0
    canonical_url_keys: set[str] = set()
    invalid_card_samples: List[Dict[str, Any]] = []
    property_key_index: Dict[str, str] = {}

    for card_index, raw_card in enumerate(candidate_cards):
        raw_urls = [value for value in raw_card.get("urls", []) if value]
        if not raw_card.get("anchorHrefs"):
            anchorless_card_count += 1
        candidate_url_count += len(raw_urls)
        normalized_candidates = [
            normalized
            for raw_url in raw_urls
            if (normalized := normalize_hotel_url(raw_url, page.url))
        ]
        valid_url_count += len(normalized_candidates)
        normalized_urls = _unique_values(normalized_candidates)

        raw_text = compact_text(raw_card.get("text"))
        explicit_name = _clean_hotel_name(
            compact_text(raw_card.get("name"))
            or compact_text(raw_card.get("imageAlt"))
        )
        name = explicit_name or _name_from_card_text(raw_text)
        if not explicit_name:
            cards_without_name_count += 1

        image_url = raw_card.get("imageUrl")
        property_id = _property_id(raw_card)
        property_key = f"property:{property_id}" if property_id else None
        if not normalized_urls:
            cards_without_url_count += 1
            if not _has_hotel_signal(raw_card, name, raw_text, image_url):
                invalid_card_count += 1
                if len(invalid_card_samples) < 25:
                    invalid_card_samples.append(_card_debug_sample(raw_card, name, raw_text))
                continue

        hotel_url = normalized_urls[0] if normalized_urls else None
        canonical_url = _hotel_url_key(hotel_url) if hotel_url else None
        if canonical_url:
            canonical_url_keys.add(canonical_url)
            record_key = f"url:{canonical_url}"
        elif property_key and property_key in property_key_index:
            record_key = property_key_index[property_key]
        elif property_key:
            record_key = property_key
        else:
            record_key = _partial_record_key(
                name=name,
                raw_text=raw_text,
                image_url=image_url,
                page_number=page_number,
                card_index=card_index,
            )

        if record_key in records_by_key:
            _merge_card_urls(records_by_key[record_key], normalized_urls)
            continue

        if not name and hotel_url:
            name = _name_from_hotel_url(hotel_url)

        record = _empty_record(name, hotel_url, page_number)
        record["canonical_url"] = canonical_url
        record["collect_status"] = _collect_status(name, hotel_url)
        record["collect_error"] = None if record["collect_status"] == "ok" else record["collect_status"]
        record["record_kind"] = "full_record" if hotel_url else "partial_missing_url"
        record["source_card_index"] = card_index
        record["candidate_urls"] = normalized_urls
        record["raw_candidate_urls"] = _unique_values(raw_urls)
        record["url_sources"] = raw_card.get("urlSources") or []
        record["available_anchor_hrefs"] = raw_card.get("anchorHrefs") or []
        record["card_source"] = raw_card.get("sourceSelector")
        record["card_tag"] = raw_card.get("tagName")
        record["card_data_selenium"] = raw_card.get("dataSelenium")
        record["card_data_testid"] = raw_card.get("dataTestId")
        record["listing_property_id"] = property_id

        parsed = _parse_textual_fallback(raw_text)
        record["price_value"] = parsed["price_value"]
        record["rating_text"] = parsed["rating_text"]
        record["review_count_text"] = parsed["review_count_text"]
        record["star_rating_text"] = parsed["star_rating_text"]

        if image_url:
            record["image_url"] = urljoin(page.url, image_url)

        if raw_text and not hotel_url:
            record["listing_text_snippet"] = raw_text[:500]
            record["card_text_preview"] = raw_text[:300]

        if not hotel_url:
            record["outer_html_preview"] = raw_card.get("outerHtmlPreview")
            record["partial_debug"] = {
                "hotel_name": name,
                "card_text_preview": (raw_text or "")[:300],
                "outer_html_preview": raw_card.get("outerHtmlPreview"),
                "available_anchor_hrefs": raw_card.get("anchorHrefs") or [],
                "raw_candidate_urls": _unique_values(raw_urls),
                "url_sources": raw_card.get("urlSources") or [],
                "selector": raw_card.get("sourceSelector"),
                "property_id": property_id,
                "card_source": {
                    "tag": raw_card.get("tagName"),
                    "data_selenium": raw_card.get("dataSelenium"),
                    "data_testid": raw_card.get("dataTestId"),
                    "class_name": raw_card.get("className"),
                },
            }

        if hotel_url and property_key:
            previous_key = property_key_index.get(property_key)
            if previous_key and previous_key != record_key:
                previous_record = records_by_key.pop(previous_key, None)
                if previous_record is not None:
                    _merge_record_fields(record, previous_record)
                    property_key_index[property_key] = record_key

        records_by_key[record_key] = record
        if property_key:
            property_key_index[property_key] = record_key

    unique_hotel_count = len(records_by_key)
    metrics = ListingCollectionMetrics(
        dom_card_count=len(raw_cards),
        candidate_records=len(candidate_cards),
        embedded_url_count=len(embedded_cards),
        candidate_url_count=candidate_url_count,
        valid_url_count=valid_url_count,
        unique_canonical_url_count=len(canonical_url_keys),
        duplicate_url_count=max(0, valid_url_count - len(canonical_url_keys)),
        unique_hotel_count=unique_hotel_count,
        invalid_card_count=invalid_card_count,
        anchorless_card_count=anchorless_card_count,
        cards_without_url_count=cards_without_url_count,
        cards_without_name_count=cards_without_name_count,
        scroll_y=_scroll_y(page),
        invalid_card_samples=invalid_card_samples,
    )
    return ListingCollectionSnapshot(list(records_by_key.values()), metrics)


def _card_debug_sample(raw_card: Dict, name: Optional[str], raw_text: Optional[str]) -> Dict[str, Any]:
    return {
        "hotel_name": name,
        "card_text_preview": (raw_text or "")[:300],
        "outer_html_preview": raw_card.get("outerHtmlPreview"),
        "available_anchor_hrefs": raw_card.get("anchorHrefs") or [],
        "raw_candidate_urls": raw_card.get("urls") or [],
        "url_sources": raw_card.get("urlSources") or [],
        "selector": raw_card.get("sourceSelector"),
        "card_source": {
            "tag": raw_card.get("tagName"),
            "class_name": raw_card.get("className"),
            "data_selenium": raw_card.get("dataSelenium"),
            "data_testid": raw_card.get("dataTestId"),
        },
        "property_id": _property_id(raw_card),
    }


def _unique_values(values) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _has_hotel_signal(
    raw_card: Dict,
    name: Optional[str],
    text: Optional[str],
    image_url: Optional[str],
) -> bool:
    if _looks_like_non_hotel_dom(raw_card, name, text):
        return False

    data_attrs = " ".join(
        compact_text(raw_card.get(key)) or ""
        for key in ("dataSelenium", "dataTestId")
    ).casefold()
    if any(token in data_attrs for token in ("hotel-item", "property-card", "search-result-card")):
        return True

    image = (compact_text(image_url) or "").casefold()
    if "hotelimages" in image and _looks_like_property_container(raw_card):
        return True

    ascii_text = _ascii_text(text or "").casefold()
    if re.search(r"\b(?:mo|open)\b.{1,160}\b(?:trong the moi|new tab)\b", ascii_text):
        return bool(_property_id(raw_card) or _looks_like_property_container(raw_card))

    has_price = bool(re.search(r"\b(?:vnd|per night|moi dem|gia moi dem)\b", ascii_text))
    has_review = bool(re.search(r"\b(?:reviews?|nhan xet|danh gia|\d(?:[.,]\d)?\s*/\s*10)\b", ascii_text))
    if has_price and has_review:
        return True

    name_text = _ascii_text(name or "").casefold()
    if re.fullmatch(r"(?:khach san|hotel|resort|villa|apartment|homestay)\s*\(\d+\)", name_text):
        return False
    return bool(name_text and re.search(r"\b(?:hotel|khach san|resort|villa|apartment|homestay)\b", name_text))


def _property_id(raw_card: Dict) -> Optional[str]:
    value = compact_text(raw_card.get("propertyId"))
    if not value:
        return None
    match = re.search(r"\d+", value)
    return match.group(0) if match else value


def _looks_like_property_container(raw_card: Dict) -> bool:
    source = (compact_text(raw_card.get("sourceSelector")) or "").casefold()
    tag = (compact_text(raw_card.get("tagName")) or "").casefold()
    attrs = " ".join(
        compact_text(raw_card.get(key)) or ""
        for key in ("dataSelenium", "dataTestId", "className")
    ).casefold()
    return (
        "hotel-item" in attrs
        or "property-card" in attrs
        or "search-result-card" in attrs
        or "propertycard" in attrs
        or "hotel-item" in source
        or "property-card" in source
        or tag in {"article"}
    )


def _looks_like_non_hotel_dom(
    raw_card: Dict,
    name: Optional[str],
    text: Optional[str],
) -> bool:
    source = (compact_text(raw_card.get("sourceSelector")) or "").casefold()
    tag = (compact_text(raw_card.get("tagName")) or "").casefold()
    class_name = (compact_text(raw_card.get("className")) or "").casefold()
    outer_html = (compact_text(raw_card.get("outerHtmlPreview")) or "").casefold()
    ascii_name = _ascii_text(name or "").casefold()
    ascii_text = _ascii_text(text or "").casefold()

    slide_tokens = (
        'aria-roledescription="slide"',
        "ssrweb-mosaicphotos",
        "aaa63-snap",
        "splide__slide",
        "swiper-slide",
        "carousel",
    )
    if source == "li" and tag == "li" and any(token in outer_html or token in class_name for token in slide_tokens):
        return True

    if (
        source == "li"
        and tag == "li"
        and not _property_id(raw_card)
        and not _looks_like_property_container(raw_card)
        and not re.search(r"\b(?:mo|open)\b.{1,160}\b(?:trong the moi|new tab)\b", ascii_text)
    ):
        return True

    generic_labels = {
        "khach san + nha",
        "hotels + homes",
        "hotel + homes",
        "hotel + home",
        "khach san",
        "hotels",
        "hotel",
    }
    if ascii_name in generic_labels or ascii_text in generic_labels:
        return True

    filter_tokens = (
        "search-filter-",
        "filteritem",
        "filter item",
        "accommodationtype",
        "hotelareaid",
        "starratingwithluxury",
    )
    if any(token in outer_html or token in class_name for token in filter_tokens):
        return True

    if re.fullmatch(r"(?:khach san|hotel|resort|villa|apartment|homestay)\s*\(\d+\)", ascii_name):
        return True
    if re.fullmatch(r"(?:khach san|hotel|resort|villa|apartment|homestay)\s*\(\d+\)", ascii_text):
        return True
    return False


def _name_from_card_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None

    normalized = compact_text(text)
    if not normalized:
        return None

    opened_name = _name_from_open_new_tab_text(normalized)
    if opened_name:
        return opened_name

    parts = [
        compact_text(part)
        for part in normalized.replace("|", "\n").split("\n")
        if compact_text(part)
    ]
    if not parts:
        parts = [normalized]

    for part in parts:
        if _looks_like_non_name(part):
            continue
        return _clean_hotel_name(part[:120])

    return _clean_hotel_name(normalized[:120])


def _name_from_open_new_tab_text(text: str) -> Optional[str]:
    ascii_value = _ascii_text(text)
    patterns = [
        r"\bMo\s+(.+?)\s+trong\s+the\s+moi\b",
        r"\bOpen\s+(.+?)\s+in\s+new\s+tab\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, ascii_value, flags=re.IGNORECASE)
        if not match:
            continue
        raw_name = text[match.start(1):match.end(1)]
        return _clean_hotel_name(raw_name)
    return None


def _clean_hotel_name(value: Optional[str]) -> Optional[str]:
    text = compact_text(value)
    if not text:
        return None

    ascii_value = _ascii_text(text)
    cleanup_patterns = [
        r"^Anh truoc cua co so luu tru\s+",
        r"^Photo of\s+",
        r"^Mo\s+",
        r"\s+trong the moi$",
        r"^Open\s+",
        r"\s+in new tab$",
    ]
    for pattern in cleanup_patterns:
        match = re.search(pattern, ascii_value, flags=re.IGNORECASE)
        if match:
            if match.start() == 0:
                text = text[match.end():]
                ascii_value = ascii_value[match.end():]
            else:
                text = text[:match.start()]
                ascii_value = ascii_value[:match.start()]
    return compact_text(text)


def _ascii_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.replace("\u0111", "d").replace("\u0110", "D")


def _looks_like_non_name(value: str) -> bool:
    lowered = value.lower()
    non_name_tokens = (
        "vnd",
        "reviews",
        "nhan xet",
        "danh gia",
        "per night",
        "moi dem",
        "gia",
        "stars out of",
        "sao",
    )
    if any(token in lowered for token in non_name_tokens):
        return True
    return bool(len(value) <= 4 and any(char.isdigit() for char in value))


def _partial_record_key(
    name: Optional[str],
    raw_text: Optional[str],
    image_url: Optional[str],
    page_number: int,
    card_index: int,
) -> str:
    if name:
        return (
            "partial:"
            f"{_identity_part(name)}|page:{page_number}"
        )

    source = compact_text(raw_text) or compact_text(image_url) or str(card_index)
    digest = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"partial:{page_number}:{digest}:{card_index}"


def _identity_part(value: Optional[str]) -> str:
    return (compact_text(value) or "").casefold()


def _collect_status(name: Optional[str], hotel_url: Optional[str]) -> str:
    missing = []
    if not hotel_url:
        missing.append("missing_url")
    if not name:
        missing.append("missing_name")
    return "ok" if not missing else ",".join(missing)


def _merge_card_urls(record: Dict, normalized_urls: List[str]) -> None:
    if not normalized_urls:
        return

    existing = list(record.get("candidate_urls") or [])
    for url in normalized_urls:
        if url not in existing:
            existing.append(url)
    record["candidate_urls"] = existing


def _merge_record_fields(record: Dict, other: Dict) -> None:
    for field, value in other.items():
        if value and not record.get(field):
            record[field] = value
    _merge_card_urls(record, list(other.get("candidate_urls") or []))


def _evaluate_embedded_hotel_url_cards(page: Page) -> List[Dict]:
    try:
        rows = page.evaluate(
            """
            () => {
                const html = (document.documentElement && document.documentElement.innerHTML) || '';
                const decoded = html
                    .replace(/\\\\u002F/g, '/')
                    .replace(/\\\\\\//g, '/')
                    .replace(/&amp;/g, '&');
                const urls = new Set();
                const patterns = [
                    /https?:\\/\\/(?:www\\.)?agoda\\.com\\/[^"'<>\\s]+?\\/hotel\\/[^"'<>\\s]+?\\.html(?:\\?[^"'<>\\s]*)?/gi,
                    /\\/[a-z]{2}-[a-z]{2}\\/[^"'<>\\s]+?\\/hotel\\/[^"'<>\\s]+?\\.html(?:\\?[^"'<>\\s]*)?/gi,
                    /\\/[^"'<>\\s]+?\\/hotel\\/[^"'<>\\s]+?\\.html(?:\\?[^"'<>\\s]*)?/gi,
                ];
                for (const pattern of patterns) {
                    let match;
                    while ((match = pattern.exec(decoded)) !== null) {
                        urls.add(match[0]);
                    }
                }
                return Array.from(urls).map((url) => ({
                    urls: [url],
                    name: '',
                    text: '',
                    imageUrl: '',
                    imageAlt: '',
                    dataSelenium: 'embedded-state',
                    dataTestId: 'embedded-state',
                }));
            }
            """
        )
    except Exception:
        return []
    return rows if isinstance(rows, list) else []


def _scroll_y(page: Page) -> int:
    try:
        return int(page.evaluate("() => Math.round(window.scrollY || 0)"))
    except Exception:
        return 0


def _evaluate_listing_dom(
    page: Page,
    card_selector: str,
    include_broad_selectors: bool = True,
) -> List[Dict]:
    strict_selectors = [
        card_selector,
        '[data-selenium="hotel-item"]',
        '[data-selenium="hotel-item-container"]',
        '[data-testid="property-card"]',
        '[data-testid="search-result-card"]',
        '[data-testid="hotel-card"]',
        '[data-element-name="property-card"]',
        '[data-element-name="hotel-item"]',
        'li[data-selenium="hotel-item"]',
    ]
    broad_selectors = [
        'article',
        'li',
        'div[data-selenium*="hotel" i]',
        'div[data-testid*="property" i]',
    ]
    selectors = strict_selectors + broad_selectors if include_broad_selectors else strict_selectors
    try:
        rows = page.evaluate(
            """
            selectors => {
                const cards = [];
                const seen = new Set();
                const textSignal = (value) => {
                    const text = (value || '')
                        .normalize('NFD')
                        .replace(/[\\u0300-\\u036f]/g, '')
                        .replace(/đ/g, 'd')
                        .replace(/Đ/g, 'D');
                    return /(?:VND|reviews?|nhan xet|danh gia|gia moi dem|per night|hotel|khach san)/i.test(text);
                };
                const firstText = (element, selector) => {
                    const found = element.querySelector(selector);
                    return found ? (
                        found.innerText ||
                        found.getAttribute('aria-label') ||
                        found.getAttribute('title') ||
                        ''
                    ) : '';
                };
                const firstAttribute = (element, names) => {
                    for (const name of names) {
                        const direct = element.getAttribute && element.getAttribute(name);
                        if (direct) return direct;
                    }
                    const selector = names.map((name) => `[${name}]`).join(',');
                    const found = element.querySelector(selector);
                    if (!found) return '';
                    for (const name of names) {
                        const value = found.getAttribute(name);
                        if (value) return value;
                    }
                    return '';
                };
                const pushUrl = (urls, urlSources, value, source) => {
                    if (!value) return;
                    const text = String(value).replace(/&amp;/g, '&');
                    const matches = text.match(/(?:https?:\\/\\/[^"'<>\\s]+)?\\/[a-z]{2}-[a-z]{2}\\/[^"'<>\\s]+?\\/hotel\\/(?:all\\/)?[^"'<>\\s]+?\\.html(?:\\?[^"'<>\\s]*)?/gi) || [];
                    if (matches.length === 0 && text.includes('/hotel/')) {
                        urls.push(text);
                        urlSources.push({ source, value: text.slice(0, 500) });
                        return;
                    }
                    for (const match of matches) {
                        urls.push(match);
                        urlSources.push({ source, value: match.slice(0, 500) });
                    }
                };
                const collectUrlCandidates = (element) => {
                    const urls = [];
                    const urlSources = [];
                    const anchorHrefs = [];
                    const anchors = [];
                    if (element.matches && element.matches('a[href]')) {
                        anchors.push(element);
                    }
                    anchors.push(...Array.from(element.querySelectorAll('a[href]')));

                    let parent = element.parentElement;
                    let depth = 0;
                    while (parent && depth < 5) {
                        if (parent.matches && parent.matches('a[href]')) {
                            anchors.push(parent);
                        }
                        parent = parent.parentElement;
                        depth += 1;
                    }

                    for (const anchor of anchors) {
                        const href = anchor.href || anchor.getAttribute('href') || '';
                        if (href) {
                            anchorHrefs.push(href);
                            pushUrl(urls, urlSources, href, 'anchor_href');
                        }
                    }

                    const attrElements = [
                        element,
                        ...Array.from(element.querySelectorAll('[href], [onclick], [role="link"], [data-href], [data-url], [data-link], [data-target-url], [data-property-url], [data-selenium], [data-testid]')).slice(0, 80),
                    ];
                    for (const node of attrElements) {
                        for (const attr of Array.from(node.attributes || [])) {
                            const name = attr.name || '';
                            if (
                                name === 'href' ||
                                name === 'onclick' ||
                                name.startsWith('data-') ||
                                name === 'aria-label' ||
                                name === 'title'
                            ) {
                                pushUrl(urls, urlSources, attr.value, `attr:${name}`);
                            }
                        }
                    }

                    return {
                        urls: Array.from(new Set(urls)),
                        urlSources,
                        anchorHrefs: Array.from(new Set(anchorHrefs)),
                    };
                };
                const add = (element, sourceSelector) => {
                    if (!element || seen.has(element)) return;
                    seen.add(element);
                    const urlData = collectUrlCandidates(element);
                    const anchors = Array.from(element.querySelectorAll('a[href]'));
                    if (element.matches && element.matches('a[href]')) anchors.unshift(element);
                    const hotelAnchors = anchors.filter((anchor) => {
                        const href = anchor.href || anchor.getAttribute('href') || '';
                        return href.includes('/hotel/');
                    });
                    const nameAnchor = hotelAnchors.find((anchor) => (
                        anchor.innerText || anchor.getAttribute('aria-label') || anchor.getAttribute('title')
                    ));
                    const text = (element.innerText || '').replace(/\\s+/g, ' ').trim();
                    const nameSelectorText = firstText(
                        element,
                        [
                            '[data-selenium*="hotel-name" i]',
                            '[data-testid*="property-name" i]',
                            '[data-testid*="hotel-name" i]',
                            '[data-element-name*="property-name" i]',
                            '[aria-label*="hotel" i]',
                        ].join(',')
                    );
                    const name = (
                        nameSelectorText ||
                        (nameAnchor && (
                            nameAnchor.innerText ||
                            nameAnchor.getAttribute('aria-label') ||
                            nameAnchor.getAttribute('title')
                        )) ||
                        element.getAttribute('aria-label') ||
                        element.getAttribute('title') ||
                        ''
                    ).replace(/\\s+/g, ' ').trim();
                    const img = element.querySelector('img');
                    const imageUrl = img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '';
                    const imageAlt = img ? (img.alt || img.title || img.getAttribute('aria-label') || '') : '';
                    const propertyId = firstAttribute(
                        element,
                        ['data-hotelid', 'property-id', 'data-property-id', 'hotel-id', 'data-propertyid']
                    ) || (img ? (img.getAttribute('data-property-id') || '') : '');
                    cards.push({
                        urls: urlData.urls,
                        urlSources: urlData.urlSources,
                        anchorHrefs: urlData.anchorHrefs,
                        name,
                        text,
                        imageUrl,
                        imageAlt: (imageAlt || '').replace(/\\s+/g, ' ').trim(),
                        dataSelenium: element.getAttribute('data-selenium') || '',
                        dataTestId: element.getAttribute('data-testid') || '',
                        className: element.getAttribute('class') || '',
                        tagName: element.tagName || '',
                        sourceSelector,
                        propertyId,
                        outerHtmlPreview: (element.outerHTML || '').replace(/\\s+/g, ' ').trim().slice(0, 1000),
                    });
                };

                for (const selector of selectors) {
                    try {
                        document.querySelectorAll(selector).forEach((element) => {
                            const text = element.innerText || '';
                            const img = element.querySelector('img');
                            if (
                                element.querySelector('a[href*="/hotel/"]') ||
                                textSignal(text) ||
                                (img && (img.alt || img.title || img.src || img.currentSrc)) ||
                                (element.innerText || '').match(/(?:₫|VND|reviews?|nhận xét|đánh giá)/i)
                            ) {
                                add(element, selector);
                            }
                        });
                    } catch (error) {
                    }
                }

                document.querySelectorAll('a[href*="/hotel/"]').forEach((anchor) => {
                    add(anchor.closest('article, li, [data-testid*="card" i], [data-selenium*="hotel" i], div') || anchor, 'hotel-anchor-closest');
                });

                return cards;
            }
            """,
            selectors,
        )
    except Exception:
        return []
    return rows if isinstance(rows, list) else []
