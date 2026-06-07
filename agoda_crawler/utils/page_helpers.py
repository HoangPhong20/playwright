"""
Low-level Playwright page helpers: page state, cookie popup, scrolling, card detection.

Extraction helpers (first_text, first_href, …) live in extraction.py — not here.
"""
import time
from typing import Dict

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from agoda_crawler.extraction.selectors import (
    BROAD_LISTING_CARD_SELECTORS,
    LISTING_CARD_SELECTORS,
    PAGE_POPUP_BUTTON_SELECTORS,
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

def handle_page_popups(page: Page, max_popups: int = 3) -> None:
    for _ in range(max(1, max_popups)):
        if not _click_first_popup_button(page):
            return
        try:
            page.wait_for_timeout(WAIT_AFTER_COOKIE)
        except Exception:
            return


def handle_cookie_popup(page: Page) -> None:
    handle_page_popups(page)


def _click_first_popup_button(page: Page) -> bool:
    for selector in PAGE_POPUP_BUTTON_SELECTORS:
        try:
            btn = page.locator(selector).first
            if btn.count() == 0:
                continue
            btn.click(timeout=CLICK_SHORT)
            return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Scrolling & card detection
# ---------------------------------------------------------------------------

def wait_for_cards(page: Page, timeout_ms: int = CARDS_TIMEOUT) -> str:
    """
    Wait until at least one listing-card selector matches.

    Strict Agoda card selectors are preferred. Broad hotel-link selectors are
    checked only near timeout as a fallback for city landing pages.

    Returns the first matching selector string.
    Raises PlaywrightTimeoutError when nothing matches within *timeout_ms*.
    """
    fallback_window_ms = int(min(5_000, max(1_000, timeout_ms * 0.25)))
    strict_timeout_ms = max(0, timeout_ms - fallback_window_ms)
    last_counts: Dict[str, int] = {}

    matched_selector = _wait_for_matching_selector_group(
        page,
        LISTING_CARD_SELECTORS,
        strict_timeout_ms,
        last_counts,
    )
    if matched_selector:
        return matched_selector

    matched_selector = _wait_for_matching_selector_group(
        page,
        BROAD_LISTING_CARD_SELECTORS,
        max(0, timeout_ms - strict_timeout_ms),
        last_counts,
    )
    if matched_selector:
        return matched_selector

    counts_text = ", ".join(f"{k}={v}" for k, v in last_counts.items())
    raise PlaywrightTimeoutError(
        f"Could not find listing cards with known selectors. counts: {counts_text}"
    )


def _wait_for_matching_selector_group(
    page: Page,
    selectors: list[str],
    timeout_ms: int,
    last_counts: Dict[str, int],
) -> str | None:
    if is_page_closed(page):
        raise PlaywrightTimeoutError("Target page closed while waiting for listing cards.")

    matched_selector = _first_matching_selector(page, selectors, last_counts)
    if matched_selector or timeout_ms <= 0:
        return matched_selector

    try:
        page.wait_for_function(
            """
            selectors => selectors.some((selector) => {
                try {
                    return document.querySelectorAll(selector).length > 0;
                } catch (error) {
                    return false;
                }
            })
            """,
            arg=selectors,
            timeout=timeout_ms,
        )
        return _first_matching_selector(page, selectors, last_counts)
    except PlaywrightTimeoutError:
        return _first_matching_selector(page, selectors, last_counts)
    except Exception:
        return _poll_for_matching_selector_group(page, selectors, timeout_ms, last_counts)


def _poll_for_matching_selector_group(
    page: Page,
    selectors: list[str],
    timeout_ms: int,
    last_counts: Dict[str, int],
) -> str | None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if is_page_closed(page):
            raise PlaywrightTimeoutError("Target page closed while waiting for listing cards.")
        matched_selector = _first_matching_selector(page, selectors, last_counts)
        if matched_selector:
            return matched_selector
        remaining_ms = int((deadline - time.time()) * 1000)
        if remaining_ms <= 0:
            break
        time.sleep(min(CARDS_POLL_INTERVAL, remaining_ms) / 1000.0)
    return _first_matching_selector(page, selectors, last_counts)


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
