"""Navigation helpers for Agoda direct hotel search crawling."""
import re
import time
from typing import Optional
from urllib.parse import urljoin

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from agoda_crawler.utils.logging import log, log_ignored_error
from agoda_crawler.navigation.urls import (
    build_city_search_urls as _build_city_search_urls,
    normalize_agoda_destination,
    parse_iso_date as _parse_iso_date,
    search_page_urls as _search_page_urls,
    search_url_label as _search_url_label,
    url_targets_page as _url_targets_page,
    with_search_page as _with_search_page,
)
from agoda_crawler.utils.page_helpers import wait_for_cards
from agoda_crawler.extraction.selectors import (
    BROAD_LISTING_CARD_SELECTORS,
    LISTING_CARD_SELECTORS,
    NEXT_PAGE_SELECTORS,
)
from agoda_crawler.config import (
    CARDS_POLL_INTERVAL,
    CARDS_TIMEOUT,
    CARDS_TIMEOUT_RETRY,
    CITY_IDS,
    CLICK_NEXT_PAGE,
    CLICK_SHORT,
    LOAD_PAGE,
    URL_FALLBACK_CARDS_TIMEOUT,
    SEARCH_ATTEMPTS,
)


RESULTS_CHANGE_GRACE_SECONDS = 2.0


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
    Open Agoda hotel results directly from the configured city id.

    Homepage UI flow is intentionally disabled. Add new destinations to
    AGODA_CITY_IDS so searches can go straight to priced hotel listing URLs.
    """
    if not _configured_city_id(destination):
        raise RuntimeError(f"Missing AGODA_CITY_IDS entry for destination: {destination}")

    attempts = max(1, min(max_attempts, 3))
    last_error: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            log(f"Search: preparing direct results ({attempt}/{attempts})")
            direct_result = _run_configured_city_id_search(
                page,
                destination,
                check_in,
                check_out,
                adults=adults,
                rooms=rooms,
                children=children,
            )
            if direct_result:
                return direct_result
        except Exception as exc:
            last_error = exc
            log(f"Search failed: {str(exc).splitlines()[0]}")

    raise RuntimeError("Configured city search did not produce hotel results") from last_error


def _run_configured_city_id_search(
    page: Page,
    destination: str,
    check_in: str,
    check_out: str,
    adults: int = 2,
    rooms: int = 1,
    children: int = 0,
) -> Optional[str]:
    city_id = _configured_city_id(destination)
    if not city_id:
        return None

    search_url = f"https://www.agoda.com/vi-vn/search?city={city_id}"
    try:
        log(f"Search: using configured city id {city_id}")
        return _open_search_url_candidates(
            page,
            search_url,
            destination,
            check_in,
            check_out,
            adults=adults,
            rooms=rooms,
            children=children,
        )
    except Exception as exc:
        log(f"Search: configured city id failed ({str(exc).splitlines()[0]})")
        return None


def _configured_city_id(destination: str) -> Optional[str]:
    normalized_destination = normalize_agoda_destination(destination).casefold()
    return CITY_IDS.get(normalized_destination)


def verify_hotel_results_page(page: Page, timeout_ms: int = CARDS_TIMEOUT) -> str:
    """
    Validate the current page by hotel card presence only.

    URL shape is deliberately not used as an acceptance criterion because Agoda can
    route through tokenized or localized paths. Activities pages do not pass unless
    they render the hotel card selectors below.
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

    return _go_to_next_page_url(page, page_number)


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
    before_signature = _results_signature(page)
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
        log_ignored_error("Next page JS click failed", exc)
        return False
    if not clicked:
        return False
    try:
        _wait_for_results_ready(
            page,
            before_signature=before_signature,
            timeout_ms=CARDS_TIMEOUT_RETRY,
            require_change=True,
        )
    except Exception as exc:
        log_ignored_error("Next page JS card wait failed", exc)
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
            _wait_for_results_ready(page, timeout_ms=CARDS_TIMEOUT_RETRY)
            return True
        except Exception as exc:
            log(f"Page {page_number}: href failed ({str(exc).splitlines()[0]})")
            continue
    return False


def _activate_pagination_control(page: Page, control: Locator) -> bool:
    if not _is_visible(control) or _is_disabled_control(control):
        return False
    before_signature = _results_signature(page)

    _scroll_pagination_control(control)

    try:
        control.click(timeout=CLICK_NEXT_PAGE)
    except Exception:
        return False

    try:
        _wait_for_results_ready(
            page,
            before_signature=before_signature,
            timeout_ms=CARDS_TIMEOUT_RETRY,
            require_change=True,
        )
    except Exception as exc:
        log_ignored_error("Pagination control card wait failed", exc)
    return True


def _scroll_pagination_control(control: Locator) -> None:
    try:
        control.scroll_into_view_if_needed(timeout=CLICK_SHORT)
        return
    except Exception:
        pass

    try:
        control.evaluate(
            """
            element => element.scrollIntoView({
                block: 'center',
                inline: 'center',
                behavior: 'instant'
            })
            """,
            timeout=CLICK_NEXT_PAGE,
        )
    except Exception as exc:
        log_ignored_error("Pagination control scroll failed", exc)


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


def _go_to_next_page_url(page: Page, next_page_number: int) -> bool:
    for target_url in _search_page_urls(page.url, next_page_number):
        if target_url == page.url:
            continue
        try:
            log(f"Page {next_page_number}: URL fallback")
            page.goto(target_url, wait_until="domcontentloaded", timeout=LOAD_PAGE)
            _wait_for_results_ready(page, timeout_ms=CARDS_TIMEOUT_RETRY)
            return True
        except Exception as exc:
            log(f"Page {next_page_number}: URL fallback failed ({str(exc).splitlines()[0]})")
            continue
    return False


def _is_activities_shell(page: Page) -> bool:
    try:
        html = page.content()
    except Exception:
        return False
    return '"appName":"activities-web"' in html or "cdn-activities" in html


def _open_search_url_candidates(
    page: Page,
    search_url: str,
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
            _wait_for_results_ready(page, timeout_ms=URL_FALLBACK_CARDS_TIMEOUT)
            if _is_activities_shell(page):
                raise RuntimeError("Derived URL opened Activities shell")
            return wait_for_cards(page, timeout_ms=URL_FALLBACK_CARDS_TIMEOUT)
        except Exception as exc:
            last_error = exc
            log(f"Search URL {idx}/{len(candidates)} no cards, trying next ({str(exc).splitlines()[0]})")

    raise RuntimeError("No configured city search URL produced hotel results") from last_error


def _wait_for_results_ready(
    page: Page,
    before_signature: Optional[str] = None,
    timeout_ms: int = CARDS_TIMEOUT_RETRY,
    require_change: bool = False,
) -> str:
    """
    Wait for listing cards and, when requested, evidence that results changed.

    Agoda pagination can update by navigation or in-place DOM replacement. This
    polls card selectors and a compact listing signature instead of relying on a
    fixed post-click sleep.
    """
    try:
        page.wait_for_load_state("domcontentloaded", timeout=LOAD_PAGE)
    except PlaywrightTimeoutError:
        pass

    selector = _wait_for_results_function(
        page,
        before_signature=before_signature,
        timeout_ms=timeout_ms,
        require_change=require_change,
    )
    if selector:
        return selector

    selector = _poll_for_results_ready(
        page,
        before_signature=before_signature,
        timeout_ms=min(timeout_ms, CARDS_POLL_INTERVAL),
        require_change=require_change,
    )
    if selector:
        return selector
    return wait_for_cards(page, timeout_ms=timeout_ms)


def _wait_for_results_function(
    page: Page,
    before_signature: Optional[str],
    timeout_ms: int,
    require_change: bool,
) -> Optional[str]:
    selectors = [*LISTING_CARD_SELECTORS, *BROAD_LISTING_CARD_SELECTORS]
    try:
        page.wait_for_function(
            """
            ([selectors, beforeSignature, requireChange, startedAt, graceMs]) => {
                const safeQueryCount = (selector) => {
                    try {
                        return document.querySelectorAll(selector).length;
                    } catch (error) {
                        return 0;
                    }
                };
                const cardSelector = selectors.join(',');
                const cardCount = safeQueryCount(cardSelector);
                if (cardCount <= 0) return false;

                const paginationSelector = [
                    '[aria-current="page"]',
                    '[data-selenium="pagination-text"]',
                    '#paginationPageCount',
                    '[class*="pagination" i] [class*="active" i]'
                ].join(',');
                const hrefs = Array.from(document.querySelectorAll('a[href*="/hotel/"]'))
                    .slice(0, 8)
                    .map((link) => link.href || link.getAttribute('href') || '')
                    .join('|');
                const activeText = Array.from(document.querySelectorAll(paginationSelector))
                    .slice(0, 3)
                    .map((node) => (node.textContent || '').trim())
                    .join('|');
                const signature = [
                    location.href,
                    cardCount,
                    activeText,
                    hrefs
                ].join('::');
                return (
                    !requireChange ||
                    !beforeSignature ||
                    signature !== beforeSignature ||
                    Date.now() - startedAt >= graceMs
                );
            }
            """,
            arg=[
                selectors,
                before_signature or "",
                require_change,
                int(time.time() * 1000),
                int(RESULTS_CHANGE_GRACE_SECONDS * 1000),
            ],
            timeout=timeout_ms,
        )
        return _matching_listing_selector(page)
    except PlaywrightTimeoutError:
        return _matching_listing_selector(page)
    except Exception as exc:
        log_ignored_error("Results wait function failed", exc)
        return None


def _poll_for_results_ready(
    page: Page,
    before_signature: Optional[str],
    timeout_ms: int,
    require_change: bool,
) -> Optional[str]:
    deadline = time.time() + timeout_ms / 1000.0
    cards_seen_at: Optional[float] = None
    last_selector: Optional[str] = None

    while time.time() < deadline:
        selector = _matching_listing_selector(page)
        if selector:
            last_selector = selector
            signature = _results_signature(page)
            changed = before_signature is None or signature != before_signature
            if not require_change or changed:
                return selector
            if cards_seen_at is None:
                cards_seen_at = time.time()
            if time.time() - cards_seen_at >= RESULTS_CHANGE_GRACE_SECONDS:
                return selector
        remaining_ms = int((deadline - time.time()) * 1000)
        if remaining_ms <= 0:
            break
        time.sleep(min(CARDS_POLL_INTERVAL, remaining_ms) / 1000.0)

    return last_selector


def _matching_listing_selector(page: Page) -> Optional[str]:
    for selector in [*LISTING_CARD_SELECTORS, *BROAD_LISTING_CARD_SELECTORS]:
        try:
            if page.locator(selector).count() > 0:
                return selector
        except Exception:
            continue
    return None


def _results_signature(page: Page) -> str:
    try:
        return str(
            page.evaluate(
                """
                () => {
                    const cardSelector = [
                        '[data-selenium="hotel-item"]',
                        '[data-selenium="hotel-item-container"]',
                        '[data-testid="property-card"]',
                        '[data-testid="search-result-card"]',
                        '[data-testid="hotel-card"]',
                        '[data-element-name="property-card"]',
                        '[data-element-name="hotel-item"]',
                        'li[data-selenium="hotel-item"]',
                        'article:has(a[href*="/hotel/"])'
                    ].join(',');
                    const paginationSelector = [
                        '[aria-current="page"]',
                        '[data-selenium="pagination-text"]',
                        '#paginationPageCount',
                        '[class*="pagination" i] [class*="active" i]'
                    ].join(',');
                    const hrefs = Array.from(document.querySelectorAll('a[href*="/hotel/"]'))
                        .slice(0, 8)
                        .map((link) => link.href || link.getAttribute('href') || '')
                        .join('|');
                    const activeText = Array.from(document.querySelectorAll(paginationSelector))
                        .slice(0, 3)
                        .map((node) => (node.textContent || '').trim())
                        .join('|');
                    return [
                        location.href,
                        document.querySelectorAll(cardSelector).length,
                        activeText,
                        hrefs
                    ].join('::');
                }
                """
            )
        )
    except Exception:
        try:
            return page.url
        except Exception:
            return ""


def _is_visible(locator: Locator) -> bool:
    try:
        return locator.count() > 0 and locator.is_visible(timeout=CLICK_SHORT)
    except Exception:
        return False
