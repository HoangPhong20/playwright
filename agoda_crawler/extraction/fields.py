"""
Extraction logic: pull structured hotel data out of listing cards.

Element helpers (first_text, first_href, â€¦) live here because they are only
needed for data extraction and depend on FIELD_SELECTORS.
"""
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

from playwright.sync_api import Page

from agoda_crawler.extraction.parsers import (
    ascii_text as _ascii_text,
    canonicalize_price_value as _canonicalize_price_value,
    hotel_url_key as _hotel_url_key,
    name_from_hotel_url as _name_from_hotel_url,
    parse_review_count as _parse_review_count,
    parse_review_score as _parse_review_score,
    parse_textual_fallback as _parse_textual_fallback,
    price_value_from_text as _price_value_from_text,
    raw_snippet as _raw_snippet,
)
from agoda_crawler.extraction.selectors import FIELD_SELECTORS
from agoda_crawler.config import CARD_SCROLL_TIMEOUT, CLICK_DEFAULT, FIELD_SELECTOR_TIMEOUT
from agoda_crawler.utils import compact_text, utc_now_iso


# ---------------------------------------------------------------------------
# Element-level helpers
# ---------------------------------------------------------------------------

def first_text(root, selectors: List[str]) -> Optional[str]:
    for selector in selectors:
        locator = root.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            text = compact_text(locator.inner_text(timeout=FIELD_SELECTOR_TIMEOUT))
        except Exception:
            continue
        if text:
            return text
    return None


def first_href(root, selectors: List[str], base_url: str) -> Optional[str]:
    for selector in selectors:
        locator = root.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            href = locator.get_attribute("href", timeout=FIELD_SELECTOR_TIMEOUT)
        except Exception:
            continue
        if href:
            return urljoin(base_url, href)
    return None


def first_attr(root, selectors: List[str], attr: str) -> Optional[str]:
    for selector in selectors:
        locator = root.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            value = locator.get_attribute(attr, timeout=FIELD_SELECTOR_TIMEOUT)
        except Exception:
            value = None
        value = compact_text(value)
        if value:
            return value
    return None


def first_image_src(root, selectors: List[str], base_url: str) -> Optional[str]:
    for selector in selectors:
        locator = root.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            src = (
                locator.get_attribute("src", timeout=FIELD_SELECTOR_TIMEOUT)
                or locator.get_attribute("data-src", timeout=FIELD_SELECTOR_TIMEOUT)
            )
        except Exception:
            continue
        if src:
            return urljoin(base_url, src)
    return None


# ---------------------------------------------------------------------------
# Card-level extraction
# ---------------------------------------------------------------------------

def _extract_card(card, page_url: str, page_number: int) -> Optional[Dict]:
    """Extract one hotel record from a listing-card locator. Returns None if no name found."""
    hotel_name = (
        first_text(card, FIELD_SELECTORS["hotel_name"])
        or first_attr(card, FIELD_SELECTORS["hotel_link"], "aria-label")
        or first_attr(card, FIELD_SELECTORS["hotel_link"], "title")
    )
    if not hotel_name:
        return None

    raw_text = card.inner_text(timeout=CLICK_DEFAULT)
    raw_snippet = _raw_snippet(raw_text)
    parsed = _parse_textual_fallback(raw_snippet)

    price_value = (
        _price_value_from_text(first_text(card, FIELD_SELECTORS["price_value"]) or "")
        or parsed["price_value"]
    )
    rating_text = first_text(card, FIELD_SELECTORS["rating_text"]) or parsed["rating_text"]
    review_count_text = first_text(card, FIELD_SELECTORS["review_count_text"]) or parsed["review_count_text"]

    return {
        "hotel_name": hotel_name,
        "hotel_url": first_href(card, FIELD_SELECTORS["hotel_link"], page_url),
        "price_value": price_value,
        "rating_text": rating_text,
        "review_count_text": review_count_text,
        "image_url": first_image_src(card, FIELD_SELECTORS["image_url"], page_url),
        "crawled_at": utc_now_iso(),
    }


def _empty_record(name: Optional[str], url: Optional[str], page_number: int) -> Dict:
    """Minimal record used by the link-based fallback extractor."""
    return {
        "hotel_name": name,
        "hotel_url": url,
        "price_value": None,
        "rating_text": None,
        "review_count_text": None,
        "image_url": None,
        "crawled_at": utc_now_iso(),
    }


def extract_fast_hotel_links(page: Page, page_number: int) -> List[Dict]:
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
                    const container = anchor.closest("article, li, div");
                    const img = container ? container.querySelector("img") : null;
                    const imageUrl = img ? (img.currentSrc || img.src || img.getAttribute("data-src") || "") : "";
                    return { href, text, imageUrl };
                })
                .filter((row) => row.href)
            """
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

        record = _empty_record(name, hotel_url, page_number)
        record["image_url"] = urljoin(page.url, row["imageUrl"]) if row.get("imageUrl") else None
        results.append(record)

    return results


# ---------------------------------------------------------------------------
# Page-level extraction
# ---------------------------------------------------------------------------

def extract_from_cards(page: Page, card_selector: str, page_number: int) -> List[Dict]:
    """Extract all hotel records from listing cards on the current page."""
    cards = page.locator(card_selector)
    results = []
    for idx in range(cards.count()):
        card = cards.nth(idx)
        _scroll_card_into_view(card)
        record = _extract_card(card, page.url, page_number)
        if record:
            results.append(record)
    return results


def _scroll_card_into_view(card) -> None:
    try:
        card.scroll_into_view_if_needed(timeout=CARD_SCROLL_TIMEOUT)
    except Exception:
        pass


def extract_from_hotel_links(page: Page, page_number: int) -> List[Dict]:
    """
    Fallback extractor: collect hotel links when card selectors yield nothing.
    Attempts to enrich fields from the nearest parent container.
    """
    links = page.locator('a[href*="/hotel/"]')
    results: List[Dict] = []
    seen_urls: set = set()

    for idx in range(links.count()):
        a = links.nth(idx)
        try:
            href = a.get_attribute("href", timeout=1000)
        except Exception:
            continue
        if not href:
            continue

        hotel_url = urljoin(page.url, href)
        hotel_key = _hotel_url_key(hotel_url)
        if hotel_key in seen_urls:
            continue
        seen_urls.add(hotel_key)

        try:
            name = compact_text(a.inner_text(timeout=1000))
        except Exception:
            name = ""
        if not name:
            name = compact_text(a.get_attribute("aria-label", timeout=1000))
        if not name:
            name = compact_text(a.get_attribute("title", timeout=1000))
        if not name:
            continue

        if "/city/" in page.url:
            results.append(_empty_record(name, hotel_url, page_number))
            continue

        container = a.locator("xpath=ancestor::article[1]").first
        if container.count() == 0:
            container = a.locator("xpath=ancestor::*[self::div or self::li][1]").first

        if container.count() == 0:
            results.append(_empty_record(name, hotel_url, page_number))
            continue

        try:
            raw_text = container.inner_text(timeout=CLICK_DEFAULT)
        except Exception:
            raw_text = None

        raw_snippet = _raw_snippet(raw_text)
        parsed = _parse_textual_fallback(raw_snippet)
        price_value = (
            _price_value_from_text(first_text(container, FIELD_SELECTORS["price_value"]) or "")
            or parsed["price_value"]
        )
        record = {
            "hotel_name": name,
            "hotel_url": hotel_url,
            "price_value": price_value,
            "rating_text": first_text(container, FIELD_SELECTORS["rating_text"]) or parsed["rating_text"],
            "review_count_text": first_text(container, FIELD_SELECTORS["review_count_text"]) or parsed["review_count_text"],
            "image_url": first_image_src(container, FIELD_SELECTORS["image_url"], page.url),
            "crawled_at": utc_now_iso(),
        }
        results.append(record)

    return results


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

    image_url = _first_detail_image(page)
    rating_text = _parse_review_score(review_text or raw_text)

    price_value = (
        _price_value_from_text(display_price_raw or "")
        or _price_value_from_text(raw_text)
        or _price_from_detail_scripts(page)
    )

    return {
        "hotel_name": name,
        "price_value": price_value,
        "rating_text": rating_text,
        "review_count_text": _parse_review_count(review_text or raw_text),
        "image_url": image_url,
    }


def _first_detail_image(page: Page) -> Optional[str]:
    images = page.locator("img")
    try:
        count = min(images.count(), 80)
    except Exception:
        return None

    fallback: Optional[str] = None
    for idx in range(count):
        img = images.nth(idx)
        try:
            src = img.get_attribute("src", timeout=1000) or img.get_attribute("data-src", timeout=1000)
        except Exception:
            continue
        if not src:
            continue
        src = urljoin(page.url, src)
        lowered = src.lower()
        if "logo" in lowered or "flag" in lowered:
            continue
        if "hotelimages" in lowered:
            return src
        if fallback is None and ("pix" in lowered or "agoda.net" in lowered):
            fallback = src
    return fallback


def _price_from_detail_scripts(page: Page) -> Optional[str]:
    try:
        script_texts = page.evaluate(
            """
            () => Array.from(document.scripts)
                .map((script) => script.textContent || '')
                .filter((text) => /price/i.test(text))
                .slice(0, 80)
            """
        )
    except Exception:
        script_texts = None

    if isinstance(script_texts, list):
        for text in script_texts:
            price_value = _price_from_json_like_text(str(text or ""))
            if price_value:
                return price_value
        return None

    scripts = page.locator("script")
    try:
        count = min(scripts.count(), 80)
    except Exception:
        return None

    for idx in range(count):
        script = scripts.nth(idx)
        try:
            text = script.inner_text(timeout=FIELD_SELECTOR_TIMEOUT)
        except Exception:
            continue
        price_value = _price_from_json_like_text(text or "")
        if price_value:
            return price_value
    return None


def _price_from_json_like_text(text: str) -> Optional[str]:
    if not text or "price" not in text.lower():
        return None

    price_key = (
        r"(?:displayPrice|display_price|finalPrice|final_price|roomPrice|"
        r"room_price|averagePrice|average_price|priceValue|price_value|price)"
    )
    patterns = [
        rf'"{price_key}"\s*:\s*"([^"]+)"',
        rf'"{price_key}"\s*:\s*(\d{{4,}}(?:\.\d+)?)',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            raw_value = match.group(1)
            parsed = _price_value_from_text(raw_value) or _canonicalize_price_value(f"VND {raw_value}")
            if parsed:
                return parsed
    return None


def extract_page_results(page: Page, card_selector: str, page_number: int) -> List[Dict]:
    """Extract from listing cards and supplement with distinct hotel links."""
    merged: Dict[str, Dict] = {}

    if not _looks_like_city_landing_shell(page, card_selector):
        for record in extract_from_cards(page, card_selector, page_number):
            merged[_record_key(record)] = record

    for record in extract_from_hotel_links(page, page_number):
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

