"""
Low-level Playwright page helpers: page state, cookie popup, scrolling, card detection.

Extraction helpers (first_text, first_href, …) live in extraction.py — not here.
"""
import time
from typing import Dict

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from agoda_crawler.extraction.selectors import (
    BROAD_LISTING_CARD_SELECTORS,
    COOKIE_BUTTON_SELECTORS,
    LISTING_CARD_SELECTORS,
)
from agoda_crawler.config import (
    CARDS_POLL_INTERVAL,
    CARDS_TIMEOUT,
    CLICK_SHORT,
    WAIT_AFTER_COOKIE,
)


# ---------------------------------------------------------------------------
# Page state
# ---------------------------------------------------------------------------

def is_page_closed(page: Page) -> bool:
    try:
        return page.is_closed()
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Cookie popup
# ---------------------------------------------------------------------------

def handle_cookie_popup(page: Page) -> None:
    for selector in COOKIE_BUTTON_SELECTORS:
        btn = page.locator(selector).first
        if btn.count() == 0:
            continue
        try:
            btn.click(timeout=CLICK_SHORT)
            page.wait_for_timeout(WAIT_AFTER_COOKIE)
            return
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Scrolling & card detection
# ---------------------------------------------------------------------------

def wait_for_cards(page: Page, timeout_ms: int = CARDS_TIMEOUT) -> str:
    """
    Poll until at least one listing-card selector matches.

    Strict Agoda card selectors are preferred. Broad hotel-link selectors are
    checked only near timeout as a fallback for city landing pages.

    Returns the first matching selector string.
    Raises PlaywrightTimeoutError when nothing matches within *timeout_ms*.
    """
    deadline = time.time() + timeout_ms / 1000.0
    fallback_deadline = deadline - min(5.0, max(1.0, timeout_ms / 1000.0 * 0.25))
    last_counts: Dict[str, int] = {}

    while time.time() < deadline:
        if is_page_closed(page):
            raise PlaywrightTimeoutError("Target page closed while waiting for listing cards.")
        matched_selector = _first_matching_selector(page, LISTING_CARD_SELECTORS, last_counts)
        if matched_selector:
            return matched_selector

        if time.time() >= fallback_deadline:
            matched_selector = _first_matching_selector(page, BROAD_LISTING_CARD_SELECTORS, last_counts)
            if matched_selector:
                return matched_selector
        time.sleep(CARDS_POLL_INTERVAL / 1000.0)

    counts_text = ", ".join(f"{k}={v}" for k, v in last_counts.items())
    raise PlaywrightTimeoutError(
        f"Could not find listing cards with known selectors. counts: {counts_text}"
    )


def _first_matching_selector(
    page: Page,
    selectors: list[str],
    last_counts: Dict[str, int],
) -> str | None:
    for selector in selectors:
        try:
            cnt = page.locator(selector).count()
        except Exception:
            cnt = 0
        last_counts[selector] = cnt
        if cnt > 0:
            return selector
    return None
