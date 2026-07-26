"""Navigation helpers for Agoda UI-driven hotel crawling."""
import re
import time
from typing import Iterable, Optional
from urllib.parse import urljoin

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from agoda_crawler.utils.logging import log, log_ignored_error
from agoda_crawler.navigation.urls import (
    build_city_search_urls as _build_city_search_urls,
    destination_pattern as _destination_pattern,
    find_city_search_url as _find_city_search_url,
    normalize_agoda_destination,
    parse_iso_date as _parse_iso_date,
    search_url_label as _search_url_label,
    url_targets_page as _url_targets_page,
)
from agoda_crawler.utils.page_helpers import handle_cookie_popup, wait_for_cards
from agoda_crawler.extraction.selectors import (
    DESTINATION_INPUT_SELECTORS,
    NEXT_PAGE_SELECTORS,
)
from agoda_crawler.config import (
    CARDS_TIMEOUT,
    CARDS_TIMEOUT_RETRY,
    CLICK_DEFAULT,
    CLICK_NEXT_PAGE,
    CLICK_SHORT,
    LOAD_HOMEPAGE,
    LOAD_PAGE,
    URL_FALLBACK_CARDS_TIMEOUT,
    SEARCH_ATTEMPTS,
    SEARCH_LISTING_READY_TIMEOUT,
    SEARCH_READY_TIMEOUT,
    WAIT_AFTER_NAV,
    WAIT_AFTER_SEARCH,
    WAIT_STABLE_LOAD_TIMEOUT,
    WAIT_STABLE_SETTLE,
)


AGODA_HOMEPAGE_URL = "https://www.agoda.com/"
HOTEL_TAB_SELECTORS = [
    'button:has-text("Hotels")',
    'a:has-text("Hotels")',
    '[role="tab"]:has-text("Hotels")',
    'span:has-text("Hotels")',
    'button:has-text("Stays")',
    'a:has-text("Stays")',
    '[role="tab"]:has-text("Stays")',
    'span:has-text("Stays")',
    'button:has-text("Accommodations")',
    'a:has-text("Accommodations")',
    '[role="tab"]:has-text("Accommodations")',
    'span:has-text("Accommodations")',
    'button:has-text("Ch\u1ed7 \u1edf")',
    'a:has-text("Ch\u1ed7 \u1edf")',
    '[role="tab"]:has-text("Ch\u1ed7 \u1edf")',
    'span:has-text("Ch\u1ed7 \u1edf")',
    'button:has-text("Kh\u00e1ch s\u1ea1n")',
    'a:has-text("Kh\u00e1ch s\u1ea1n")',
    '[role="tab"]:has-text("Kh\u00e1ch s\u1ea1n")',
    'span:has-text("Kh\u00e1ch s\u1ea1n")',
]

NON_HOTEL_MODE_TEXT = re.compile(
    (
        r"\b(activities|flights|packages|cars|airport transfers)\b"
        r"|ho\u1ea1t \u0111\u1ed9ng|m\u00e1y bay|ph\u01b0\u01a1ng ti\u1ec7n"
    ),
    re.I,
)

# UI flow diagram:
# 1. Open Agoda homepage and wait until the shell is interactive.
# 2. Force hotel mode by clicking the Hotels tab before touching the search box.
# 3. Click and fill the destination field; do not submit from the input.
# 4. Wait for autocomplete and select a real suggestion.
# 5. Open the date picker and select check-in/check-out by UI controls.
# 6. Click the visible Search button and wait for navigation/rendering to settle.
# 7. Accept only a page that contains hotel listing cards.
# Retry: derive a dated `/search` URL from the city landing page because it
# exposes paginated priced listing cards. City landing pages are deliberately
# not accepted as crawl results because they only expose a partial hotel set.
def search_hotels_via_ui(
    page: Page,
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
    max_attempts: int = SEARCH_ATTEMPTS,
) -> str:
    """
    Run Agoda search using homepage UI actions and return the card selector.

    Agoda's current headless homepage submit can route city searches to
    Activities. Use the hotel city landing page only to derive a stable search
    URL, then require that URL to render hotel listing cards.
    """
    attempts = max(1, min(max_attempts, 3))
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            log(f"Search: preparing results ({attempt}/{attempts})")
            return _run_city_landing_url_search(
                page,
                destination,
                check_in,
                check_out,
                adults=adults,
                rooms=rooms,
                children=children,
            )
        except Exception as exc:
            last_error = exc
            log(f"Search failed: {str(exc).splitlines()[0]}")

    raise RuntimeError("Not hotel results page") from last_error


def verify_hotel_results_page(page: Page, timeout_ms: int = CARDS_TIMEOUT) -> str:
    """
    Validate the current page by hotel card presence only.

    URL shape is deliberately not used as an acceptance criterion because Agoda can
    route through tokenized or localized paths. Activities/homepage pages do not
    pass unless they render the hotel card selectors below.
    """
    if _is_activities_shell(page):
        raise RuntimeError("Not hotel results page")

    try:
        return wait_for_cards(page, timeout_ms=timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError("Not hotel results page") from exc


def go_to_next_page(page: Page, next_page_number: Optional[int] = None) -> bool:
    if next_page_number is None:
        return _click_next_page_control(page)
    return go_to_results_page(page, next_page_number, prefer_next=True)


def go_to_results_page(
    page: Page,
    page_number: int,
    prefer_next: bool = False,
) -> bool:
    if prefer_next and _click_next_page_control(page):
        return True

    if _click_page_number_control(page, page_number):
        return True

    if _open_next_page_link(page, page_number):
        return True

    log(
        "Pagination transition failed: "
        f"page={page_number} reason=no_usable_control_or_agoda_href"
    )
    return False


def _click_next_page_control(page: Page) -> bool:
    for selector in NEXT_PAGE_SELECTORS:
        controls = page.locator(selector)
        try:
            count = min(controls.count(), 5)
        except Exception:
            count = 0
        for index in range(count):
            if _activate_pagination_control(page, controls.nth(index)):
                return True
    return _click_next_page_control_with_js(page)


def _click_next_page_control_with_js(page: Page) -> bool:
    try:
        clicked = page.evaluate(
            """
            () => {
                const selectors = [
                    '#paginationNext',
                    '[data-selenium="pagination-next-btn"]',
                    'button[id*="paginationNext" i]',
                    'button[data-element-name*="pagination-next" i]'
                ];
                for (const selector of selectors) {
                    const button = document.querySelector(selector);
                    if (!button) continue;
                    if (button.disabled || button.getAttribute('aria-disabled') === 'true') continue;
                    button.scrollIntoView({ block: 'center', inline: 'center' });
                    button.click();
                    return true;
                }
                return false;
            }
            """
        )
    except Exception as exc:
        log_ignored_error("Pagination transition failed reason=js_click_error", exc)
        return False
    if not clicked:
        return False
    try:
        page.wait_for_load_state("domcontentloaded", timeout=LOAD_PAGE)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(WAIT_AFTER_NAV)
    try:
        wait_for_cards(page, timeout_ms=CARDS_TIMEOUT_RETRY)
    except Exception as exc:
        log_ignored_error("Pagination transition failed reason=js_cards_not_ready", exc)
    return True


def _click_page_number_control(page: Page, page_number: int) -> bool:
    candidates = page.locator(
        ",".join(
            [
                "nav a",
                "nav button",
                '[role="navigation"] a',
                '[role="navigation"] button',
                '[class*="pagination" i] a',
                '[class*="pagination" i] button',
                '[data-selenium*="pagination" i] a',
                '[data-selenium*="pagination" i] button',
                'a[aria-label*="page" i]',
                'button[aria-label*="page" i]',
                'a[aria-label*="trang" i]',
                'button[aria-label*="trang" i]',
            ]
        )
    )
    try:
        count = min(candidates.count(), 80)
    except Exception:
        return False

    for index in range(count):
        candidate = candidates.nth(index)
        if not _is_target_page_control(candidate, page_number):
            continue
        if _activate_pagination_control(page, candidate):
            return True
    return False


def _open_next_page_link(page: Page, page_number: int) -> bool:
    links = page.locator('a[href*="/search"]')
    try:
        count = min(links.count(), 120)
    except Exception:
        return False

    for index in range(count):
        link = links.nth(index)
        try:
            href = link.get_attribute("href", timeout=CLICK_SHORT)
        except Exception:
            continue
        if not href:
            continue
        target_url = urljoin(page.url, href)
        if not _url_targets_page(target_url, page_number):
            continue
        try:
            log(f"Page {page_number}: opening href")
            page.goto(target_url, wait_until="domcontentloaded", timeout=LOAD_PAGE)
            _wait_until_stable(page)
            page.wait_for_timeout(WAIT_AFTER_NAV)
            wait_for_cards(page, timeout_ms=CARDS_TIMEOUT_RETRY)
            return True
        except Exception as exc:
            log(
                "Pagination transition failed: "
                f"page={page_number} reason=href_navigation_error "
                f"error={str(exc).splitlines()[0]}"
            )
            continue
    return False


def _activate_pagination_control(page: Page, control: Locator) -> bool:
    if not _is_visible(control) or _is_disabled_control(control):
        return False

    try:
        control.scroll_into_view_if_needed(timeout=CLICK_SHORT)
    except Exception as exc:
        log_ignored_error("Pagination transition failed reason=control_scroll_error", exc)

    try:
        control.click(timeout=CLICK_NEXT_PAGE)
    except Exception as exc:
        log_ignored_error("Pagination transition failed reason=control_click_error", exc)
        return False

    try:
        page.wait_for_load_state("domcontentloaded", timeout=LOAD_PAGE)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(WAIT_AFTER_NAV)

    try:
        wait_for_cards(page, timeout_ms=CARDS_TIMEOUT_RETRY)
    except Exception as exc:
        log_ignored_error("Pagination transition failed reason=cards_not_ready", exc)
    return True


def _is_target_page_control(control: Locator, page_number: int) -> bool:
    expected = str(page_number)
    values = []
    try:
        values.append(control.inner_text(timeout=CLICK_SHORT))
    except Exception:
        pass
    for attr in ("aria-label", "title", "data-page", "data-page-number"):
        try:
            value = control.get_attribute(attr, timeout=CLICK_SHORT)
        except Exception:
            value = None
        if value:
            values.append(value)

    for value in values:
        normalized = normalize_agoda_destination(value).strip().lower()
        if normalized == expected:
            return True
        if re.search(rf"\b(?:page|trang)\s*{re.escape(expected)}\b", normalized):
            return True
    return False


def _is_disabled_control(control: Locator) -> bool:
    try:
        if control.is_disabled(timeout=CLICK_SHORT):
            return True
    except Exception:
        pass

    for attr in ("aria-disabled", "disabled"):
        try:
            value = control.get_attribute(attr, timeout=CLICK_SHORT)
        except Exception:
            value = None
        if value and value.lower() not in {"false", "0"}:
            return True

    try:
        class_name = control.get_attribute("class", timeout=CLICK_SHORT) or ""
    except Exception:
        class_name = ""
    return bool(re.search(r"\b(disabled|inactive)\b", class_name, re.I))


def _run_city_landing_url_search(
    page: Page,
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
) -> str:
    _open_homepage(page)
    handle_cookie_popup(page)
    _force_hotel_mode_or_continue(page)
    _click_destination_landing_card(page, destination)
    handle_cookie_popup(page)
    return _open_ui_derived_city_search_url(
        page,
        destination,
        check_in,
        check_out,
        adults=adults,
        rooms=rooms,
        children=children,
    )


def _force_hotel_mode_or_continue(page: Page) -> None:
    try:
        _force_hotel_mode(page)
    except RuntimeError as exc:
        if "Cannot find Hotels tab" not in str(exc):
            raise
        log("Search: Hotels tab not found; trying city landing fallback")


def _open_homepage(page: Page) -> None:
    page.goto(AGODA_HOMEPAGE_URL, wait_until="domcontentloaded", timeout=LOAD_HOMEPAGE)
    _wait_until_stable(page)


def _wait_until_stable(page: Page) -> None:
    try:
        page.wait_for_load_state("load", timeout=WAIT_STABLE_LOAD_TIMEOUT)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(WAIT_STABLE_SETTLE)


def _force_hotel_mode(page: Page) -> None:
    hotel_tab = _find_hotel_tab(page, timeout_ms=8_000)
    if hotel_tab is None:
        raise RuntimeError("Cannot find Hotels tab on Agoda homepage")

    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=LOAD_PAGE):
            hotel_tab.click(timeout=CLICK_DEFAULT)
    except PlaywrightTimeoutError:
        pass
    _wait_until_stable(page)
    page.wait_for_timeout(700)
    _reject_activities_shell(page)

    destination_input = _find_destination_input(page, timeout_ms=SEARCH_READY_TIMEOUT)
    if destination_input is None:
        raise RuntimeError("Hotel mode did not expose the destination search input")

    _reject_active_non_hotel_mode(page)


def _reject_activities_shell(page: Page) -> None:
    if _is_activities_shell(page):
        raise RuntimeError("Activities shell is active after selecting hotel mode")


def _is_activities_shell(page: Page) -> bool:
    try:
        html = page.content()
    except Exception:
        return False
    return '"appName":"activities-web"' in html or "cdn-activities" in html


def _find_hotel_tab(page: Page, timeout_ms: int) -> Optional[Locator]:
    deadline = time.time() + timeout_ms / 1000.0
    exact_text = re.compile(
        r"^(Hotels|Stays|Accommodations|Ch\u1ed7 \u1edf|Kh\u00e1ch s\u1ea1n)$",
        re.I,
    )

    while time.time() < deadline:
        for locator in (
            page.get_by_role("tab", name=exact_text).first,
            page.get_by_role("button", name=exact_text).first,
            page.get_by_text(exact_text).first,
        ):
            if _is_visible(locator):
                return locator

        locator = _first_visible(page, HOTEL_TAB_SELECTORS, timeout_ms=500)
        if locator is not None:
            text = _safe_text(locator)
            if exact_text.search(text):
                return locator
        time.sleep(0.2)

    return None


def _reject_active_non_hotel_mode(page: Page) -> None:
    tabs = page.locator("[role='tab'][aria-selected='true'], [aria-current='page']")
    for idx in range(tabs.count()):
        try:
            text = tabs.nth(idx).inner_text(timeout=CLICK_SHORT)
        except Exception:
            continue
        if NON_HOTEL_MODE_TEXT.search(text):
            raise RuntimeError(f"Non-hotel tab is active: {text}")


def _click_destination_landing_card(page: Page, destination: str) -> None:
    destination_pattern = _destination_pattern(destination)
    candidates = page.locator("a, button, [role='link']")

    deadline = time.time() + 10
    while time.time() < deadline:
        for idx in range(candidates.count()):
            candidate = candidates.nth(idx)
            if not _is_visible(candidate):
                continue
            text = normalize_agoda_destination(_safe_text(candidate))
            if not destination_pattern.search(text):
                continue
            if len(text) > 120:
                continue
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=LOAD_PAGE):
                    candidate.click(timeout=CLICK_DEFAULT)
                _wait_until_stable(page)
                return
            except PlaywrightTimeoutError:
                _wait_until_stable(page)
                return
            except Exception:
                continue
        time.sleep(0.3)

    raise RuntimeError(f"Cannot find visible destination landing card: {destination}")


def _open_ui_derived_city_search_url(
    page: Page,
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
) -> str:
    check_in_date = _parse_iso_date(check_in, "check-in")
    check_out_date = _parse_iso_date(check_out, "check-out")
    if check_out_date <= check_in_date:
        raise ValueError("check_out must be after check_in")

    search_url = _find_city_search_url(page)
    if search_url is None:
        raise RuntimeError("Cannot derive hotel search URL from city landing page")

    candidates = _build_city_search_urls(
        search_url,
            destination=destination,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            adults=adults,
            rooms=rooms,
            children=children,
        )
    last_error: Optional[Exception] = None
    for idx, target_url in enumerate(candidates, start=1):
        try:
            log(f"Search URL {idx}/{len(candidates)}: {_search_url_label(target_url)}")
            page.goto(target_url, wait_until="domcontentloaded", timeout=LOAD_PAGE)
            _wait_until_stable(page)
            page.wait_for_timeout(WAIT_AFTER_SEARCH)
            if _is_activities_shell(page):
                raise RuntimeError("Derived URL opened Activities shell")
            try:
                return wait_for_cards(page, timeout_ms=SEARCH_LISTING_READY_TIMEOUT)
            except PlaywrightTimeoutError:
                return wait_for_cards(page, timeout_ms=URL_FALLBACK_CARDS_TIMEOUT)
        except Exception as exc:
            last_error = exc
            log(f"Search URL {idx}/{len(candidates)} no cards, trying next ({str(exc).splitlines()[0]})")

    raise RuntimeError("No UI-derived city search URL produced hotel results") from last_error

def _find_destination_input(page: Page, timeout_ms: int) -> Optional[Locator]:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        locator = _first_visible(page, DESTINATION_INPUT_SELECTORS, timeout_ms=500)
        if locator is not None:
            return locator
        time.sleep(0.2)
    return None


def _first_visible(page: Page, selectors: Iterable[str], timeout_ms: int) -> Optional[Locator]:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        for selector in selectors:
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            try:
                if locator.is_visible(timeout=CLICK_SHORT):
                    return locator
            except Exception:
                continue
        time.sleep(0.2)
    return None


def _is_visible(locator: Locator) -> bool:
    try:
        return locator.count() > 0 and locator.is_visible(timeout=CLICK_SHORT)
    except Exception:
        return False


def _safe_text(locator: Locator) -> str:
    try:
        return locator.inner_text(timeout=CLICK_SHORT).strip()
    except Exception:
        return ""
