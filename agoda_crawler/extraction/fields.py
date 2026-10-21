"""
Extraction logic: pull structured hotel data out of listing cards.

Element helpers (first_text, first_href, â€¦) live here because they are only
needed for data extraction and depend on FIELD_SELECTORS.
"""
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urljoin, urlparse

from playwright.sync_api import Page

from agoda_crawler.extraction.parsers import (
    hotel_url_key as _hotel_url_key,
    name_from_hotel_url as _name_from_hotel_url,
    parse_review_count as _parse_review_count,
    parse_review_score as _parse_review_score,
    parse_star_rating as _parse_star_rating,
    parse_textual_fallback as _parse_textual_fallback,
    price_value_from_text as _price_value_from_text,
    raw_snippet as _raw_snippet,
)
from agoda_crawler.extraction.selectors import (
    FIELD_SELECTORS,
    LISTING_CARD_MEMBERSHIP_CLASSIFIER_JS,
    LISTING_CARD_MEMBERSHIP_CONFIG,
    NON_LISTING_CONTEXT_EXCLUSION_SELECTOR,
    NON_LISTING_CONTEXT_SELECTORS,
)
from agoda_crawler.config import CLICK_DEFAULT
from agoda_crawler.utils import compact_text, utc_now_iso


# ---------------------------------------------------------------------------
# Element-level helpers
# ---------------------------------------------------------------------------

def first_text(root, selectors: List[str], *, listing_scope: bool = False) -> Optional[str]:
    for selector in selectors:
        if listing_scope:
            selector = _exclude_non_listing_descendants(selector)
        locator = root.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            text = compact_text(
                _text_without_excluded_context(locator) if listing_scope
                else locator.inner_text(timeout=CLICK_DEFAULT)
            )
        except Exception:
            continue
        if text:
            return text
    return None


def first_href(
    root,
    selectors: List[str],
    base_url: str,
    *,
    listing_scope: bool = False,
) -> Optional[str]:
    for selector in selectors:
        if listing_scope:
            selector = _exclude_non_listing_descendants(selector)
        locator = root.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            href = locator.get_attribute("href", timeout=CLICK_DEFAULT)
        except Exception:
            continue
        if href:
            return urljoin(base_url, href)
    return None


def first_attr(
    root,
    selectors: List[str],
    attr: str,
    *,
    listing_scope: bool = False,
) -> Optional[str]:
    for selector in selectors:
        if listing_scope:
            selector = _exclude_non_listing_descendants(selector)
        locator = root.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            value = locator.get_attribute(attr, timeout=CLICK_DEFAULT)
        except Exception:
            value = None
        value = compact_text(value)
        if value:
            return value
    return None


def _exclude_non_listing_descendants(selector: str) -> str:
    return f"{selector}:not({NON_LISTING_CONTEXT_EXCLUSION_SELECTOR})"


def _text_without_excluded_context(locator) -> str:
    try:
        return locator.evaluate(
            """(element, excludedSelector) => {
                if (!element.querySelector(excludedSelector)) return element.innerText || '';
                const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
                const visibleText = [];
                let node;
                while ((node = walker.nextNode())) {
                    let current = node.parentElement;
                    let visible = true;
                    while (current && current !== element.parentElement) {
                        if (current.matches(excludedSelector) || current.hidden) {
                            visible = false;
                            break;
                        }
                        const style = window.getComputedStyle(current);
                        if (
                            style.display === 'none' ||
                            style.visibility === 'hidden' ||
                            style.visibility === 'collapse'
                        ) {
                            visible = false;
                            break;
                        }
                        current = current.parentElement;
                    }
                    if (visible && node.nodeValue) visibleText.push(node.nodeValue);
                }
                return visibleText.join(' ');
            }""",
            NON_LISTING_CONTEXT_SELECTORS,
        )
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Card-level extraction
# ---------------------------------------------------------------------------

def _extract_card(card, page_url: str) -> Optional[Dict]:
    """Extract one hotel record from a listing-card locator. Returns None if no name found."""
    hotel_name = (
        first_text(card, FIELD_SELECTORS["hotel_name"], listing_scope=True)
        or first_attr(card, FIELD_SELECTORS["hotel_link"], "aria-label", listing_scope=True)
        or first_attr(card, FIELD_SELECTORS["hotel_link"], "title", listing_scope=True)
    )
    if not hotel_name:
        return None

    raw_text = _text_without_excluded_context(card)
    raw_snippet = _raw_snippet(raw_text)
    parsed = _parse_textual_fallback(raw_snippet)

    price_value = (
        _price_value_from_text(
            first_text(card, FIELD_SELECTORS["price_value"], listing_scope=True) or ""
        )
        or parsed["price_value"]
    )
    rating_text = first_text(card, FIELD_SELECTORS["rating_text"], listing_scope=True) or parsed["rating_text"]
    review_count_text = first_text(card, FIELD_SELECTORS["review_count_text"], listing_scope=True) or parsed["review_count_text"]
    star_rating_text = first_text(card, FIELD_SELECTORS["star_rating_text"], listing_scope=True) or parsed["star_rating_text"]

    return {
        "hotel_name": hotel_name,
        "hotel_url": first_href(
            card,
            FIELD_SELECTORS["hotel_link"],
            page_url,
            listing_scope=True,
        ),
        "price_value": price_value,
        "rating_text": rating_text,
        "review_count_text": review_count_text,
        "star_rating_text": star_rating_text,
        "crawled_at": utc_now_iso(),
    }


def _empty_record(name: Optional[str], url: Optional[str]) -> Dict:
    """Minimal record used by the link-based fallback extractor."""
    return {
        "hotel_name": name,
        "hotel_url": url,
        "price_value": None,
        "rating_text": None,
        "review_count_text": None,
        "star_rating_text": None,
        "crawled_at": utc_now_iso(),
    }


def extract_fast_hotel_links(page: Page) -> List[Dict]:
    """
    Fast DOM-level collector for scroll rounds.

    Playwright locator extraction is comparatively expensive when Agoda keeps
    many virtualized hotel links in the DOM. This collector only captures the
    identity fields needed to know whether scrolling loaded new hotels; detail
    enrichment can fill price/rating fields later.
    """
    try:
        rows = page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href*="/hotel/"]'))
                .map((anchor) => {
                    const href = anchor.href || anchor.getAttribute("href") || "";
                    const text = (
                        anchor.innerText ||
                        anchor.getAttribute("aria-label") ||
                        anchor.getAttribute("title") ||
                        ""
                    ).replace(/\\s+/g, " ").trim();
                    return { href, text };
                })
                .filter((row) => row.href)
            """,
        )
    except Exception:
        return []

    results: List[Dict] = []
    seen_urls: set = set()
    for row in rows:
        hotel_url = urljoin(page.url, row.get("href", ""))
        hotel_key = _hotel_url_key(hotel_url)
        if hotel_key in seen_urls:
            continue
        seen_urls.add(hotel_key)

        name = compact_text(row.get("text")) or _name_from_hotel_url(hotel_url)

        record = _empty_record(name, hotel_url)
        results.append(record)

    return results


# ---------------------------------------------------------------------------
# Page-level extraction
# ---------------------------------------------------------------------------

def extract_from_cards(
    page: Page,
    card_selector: str,
    observed_records: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Extract all hotel records from listing cards on the current page."""
    cards = page.locator(card_selector)
    results = []
    for idx in range(cards.count()):
        card = cards.nth(idx)
        membership_evidence = _listing_card_membership_evidence(card)
        if membership_evidence == "excluded":
            continue
        record = _extract_card(card, page.url)
        if not record:
            continue
        if membership_evidence == "unverified" and not any(
            _same_observed_hotel(record, observed)
            for observed in observed_records or []
        ):
            continue
        results.append(record)
    return results


def extract_from_hotel_links(
    page: Page,
    observed_records: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    Fallback extractor: collect hotel links when card selectors yield nothing.
    Attempts to enrich fields from the nearest parent container.
    """
    links = page.locator('a[href*="/hotel/"]')
    results: List[Dict] = []
    seen_urls: set = set()

    for idx in range(links.count()):
        a = links.nth(idx)
        if _listing_card_membership_evidence(a) == "excluded":
            continue
        try:
            href = a.get_attribute("href", timeout=1000)
        except Exception:
            continue
        if not href:
            continue

        hotel_url = urljoin(page.url, href)
        hotel_key = _hotel_url_key(hotel_url)
        candidate = {"hotel_url": hotel_url}
        matching_observation = next(
            (
                record
                for record in observed_records or []
                if _same_observed_hotel(candidate, record)
            ),
            None,
        )
        if matching_observation is None:
            continue
        if hotel_key in seen_urls:
            continue
        seen_urls.add(hotel_key)

        try:
            name = compact_text(_text_without_excluded_context(a))
        except Exception:
            name = ""
        if not name:
            name = compact_text(a.get_attribute("aria-label", timeout=1000))
        if not name:
            name = compact_text(a.get_attribute("title", timeout=1000))
        if not name:
            name = matching_observation.get("hotel_name") or ""
        if not name:
            continue

        if "/city/" in page.url:
            results.append(_empty_record(name, hotel_url))
            continue

        container = a.locator("xpath=ancestor::article[1]").first
        if container.count() == 0:
            container = a.locator("xpath=ancestor::*[self::div or self::li][1]").first

        if container.count() == 0:
            results.append(_empty_record(name, hotel_url))
            continue

        try:
            raw_text = _text_without_excluded_context(container)
        except Exception:
            raw_text = None

        raw_snippet = _raw_snippet(raw_text)
        parsed = _parse_textual_fallback(raw_snippet)
        price_value = (
            _price_value_from_text(
                first_text(container, FIELD_SELECTORS["price_value"], listing_scope=True) or ""
            )
            or parsed["price_value"]
        )
        record = {
            "hotel_name": name,
            "hotel_url": hotel_url,
            "price_value": price_value,
            "rating_text": first_text(container, FIELD_SELECTORS["rating_text"], listing_scope=True) or parsed["rating_text"],
            "review_count_text": first_text(container, FIELD_SELECTORS["review_count_text"], listing_scope=True) or parsed["review_count_text"],
            "star_rating_text": first_text(container, FIELD_SELECTORS["star_rating_text"], listing_scope=True) or parsed["star_rating_text"],
            "crawled_at": utc_now_iso(),
        }
        results.append(record)

    return results


def _listing_card_membership_evidence(locator) -> str:
    """Classify a DOM element against the page's verified listing membership."""
    try:
        script = (
            "(element, config) => ("
            + LISTING_CARD_MEMBERSHIP_CLASSIFIER_JS
            + ")(config)(element)"
        )
        evidence = locator.evaluate(script, LISTING_CARD_MEMBERSHIP_CONFIG)
        return evidence if isinstance(evidence, str) else "unverified"
    except Exception:
        return "unverified"


def extract_detail_fields(page: Page) -> Dict[str, Optional[str]]:
    """Extract fields available on an Agoda hotel detail page."""
    name = first_text(page, ["h1", '[data-selenium="hotel-name"]'])
    review_text = first_text(
        page,
        [
            '[data-testid*="review-score"]',
            '[data-selenium="review-score"]',
            '[class*="ReviewScore"]',
        ],
    )
    star_text = first_attr(page, ['[aria-label*="sao" i]', '[aria-label*="star" i]'], "aria-label")
    display_price_raw = first_text(
        page,
        [
            '[data-selenium="display-price"]',
            '[data-element-name="final-price"]',
            '[data-testid*="price"]',
            '[class*="price" i]',
        ],
    )

    raw_text = ""
    try:
        raw_text = page.locator("body").inner_text(timeout=CLICK_DEFAULT)
    except Exception:
        pass

    rating_text = _parse_review_score(review_text or raw_text)

    price_value = _price_value_from_text(display_price_raw or "") or _price_value_from_text(raw_text)

    return {
        "hotel_name": name,
        "price_value": price_value,
        "rating_text": rating_text,
        "review_count_text": _parse_review_count(review_text or raw_text),
        "star_rating_text": _parse_star_rating(star_text or raw_text),
    }


def extract_page_results(
    page: Page,
    card_selector: str,
    observed_records: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Extract from listing cards and supplement with distinct hotel links."""
    merged: Dict[str, Dict] = {}

    if not _looks_like_city_landing_shell(page, card_selector):
        for record in extract_from_cards(page, card_selector, observed_records):
            merged[_record_key(record)] = record

    for record in extract_from_hotel_links(
        page,
        [*(observed_records or []), *merged.values()],
    ):
        key = _record_key(record)
        existing = merged.get(key)
        if existing is None:
            merged[key] = record
            continue
        for field, value in record.items():
            if not existing.get(field) and value:
                existing[field] = value

    return list(merged.values())


def _looks_like_city_landing_shell(page: Page, card_selector: str) -> bool:
    if "/city/" not in page.url:
        return False
    try:
        return page.locator(card_selector).count() <= 2 and page.locator('a[href*="/hotel/"]').count() > 20
    except Exception:
        return False


def _record_key(record: Dict) -> str:
    hotel_url = record.get("hotel_url")
    if hotel_url:
        return _hotel_url_key(hotel_url)
    return f"name:{(record.get('hotel_name') or '').strip().lower()}"


def _same_observed_hotel(candidate: Dict, observed: Dict) -> bool:
    candidate_url = candidate.get("hotel_url") or candidate.get("canonical_url")
    observed_url = observed.get("hotel_url") or observed.get("canonical_url")
    if not candidate_url:
        return False

    candidate_id = _property_identity(candidate)
    observed_id = _property_identity(observed)
    if candidate_id and observed_id and candidate_id != observed_id:
        return False
    if observed_url and _hotel_url_key(candidate_url) == _hotel_url_key(observed_url):
        return True
    return bool(candidate_id and candidate_id == observed_id)


def _property_identity(record: Dict) -> Optional[str]:
    value = compact_text(record.get("listing_property_id"))
    if value:
        return value
    hotel_url = record.get("hotel_url") or record.get("canonical_url") or ""
    property_ids = [
        value
        for key, value in parse_qsl(urlparse(hotel_url).query, keep_blank_values=True)
        if key.casefold() == "propertyid"
    ]
    return property_ids[0] if len(property_ids) == 1 and property_ids[0].isdigit() else None

