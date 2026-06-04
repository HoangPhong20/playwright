"""Scrolling helpers for Agoda listing pages."""
from dataclasses import dataclass

from playwright.sync_api import Page

from agoda_crawler.config import (
    LAZY_NETWORK_IDLE_TIMEOUT,
    LAZY_SETTLE_WAIT,
    SCROLL_USE_PAGEDOWN,
    SCROLL_VIEWPORT_PERCENT,
    SCROLL_WHEEL_DELTA,
)
from agoda_crawler.utils.logging import log_ignored_error


@dataclass(frozen=True)
class ScrollAdvance:
    moved: bool
    target: str
    scroll_y: int
    scroll_height: int
    client_height: int


def scroll_y(page: Page) -> int:
    try:
        return int(page.evaluate("() => Math.round(window.scrollY || 0)"))
    except Exception:
        return 0


def visible_result_count(page: Page, card_selector: str) -> int:
    counts = []
    for selector in (card_selector, 'a[href*="/hotel/"]'):
        try:
            counts.append(page.locator(selector).count())
        except Exception:
            counts.append(0)
    return max(counts)


def advance_results_scroll(page: Page) -> ScrollAdvance:
    advance = scroll_dom_containers(page)
    if advance.moved:
        return advance

    try:
        page.mouse.wheel(0, SCROLL_WHEEL_DELTA)
    except Exception as exc:
        log_ignored_error("Listing mouse wheel scroll failed", exc)
    if SCROLL_USE_PAGEDOWN:
        try:
            page.keyboard.press("PageDown")
        except Exception as exc:
            log_ignored_error("Listing PageDown scroll failed", exc)
    fallback = scroll_target_state(page)
    return ScrollAdvance(
        moved=fallback.scroll_y != advance.scroll_y,
        target=fallback.target or advance.target,
        scroll_y=fallback.scroll_y,
        scroll_height=fallback.scroll_height,
        client_height=fallback.client_height,
    )


def scroll_dom_containers(page: Page) -> ScrollAdvance:
    try:
        result = page.evaluate(
            """
            viewportPercent => {
                const viewportStep = Math.max(
                    500,
                    Math.floor(window.innerHeight * viewportPercent / 100)
                );
                const labelFor = (element, index) => {
                    if (!element) return 'window';
                    const id = element.id ? `#${element.id}` : '';
                    const selenium = element.getAttribute('data-selenium');
                    const testid = element.getAttribute('data-testid');
                    const attr = selenium ? `[data-selenium="${selenium}"]` : (testid ? `[data-testid="${testid}"]` : '');
                    const cls = (element.className && typeof element.className === 'string')
                        ? '.' + element.className.trim().split(/\\s+/).slice(0, 2).join('.')
                        : '';
                    return `${element.tagName.toLowerCase()}${id}${attr || cls}:candidate-${index}`;
                };
                const hotelSelector = [
                    '[data-selenium="hotel-item"]',
                    '[data-testid="property-card"]',
                    '[data-element-name="property-card"]',
                    'a[href*="/hotel/"]'
                ].join(',');
                const containers = Array.from(document.querySelectorAll('body *'))
                    .map((element, index) => {
                        const style = window.getComputedStyle(element);
                        const overflowY = style.overflowY;
                        const canScroll = element.scrollHeight > element.clientHeight + 100;
                        const hasHotel = Boolean(element.querySelector(hotelSelector));
                        const cardCount = hasHotel ? element.querySelectorAll(hotelSelector).length : 0;
                        const range = element.scrollHeight - element.clientHeight;
                        return { element, index, overflowY, canScroll, hasHotel, cardCount, range };
                    })
                    .filter((item) => (
                        item.canScroll &&
                        item.hasHotel &&
                        ['auto', 'scroll', 'overlay'].includes(item.overflowY)
                    ))
                    .sort((left, right) => {
                        if (right.cardCount !== left.cardCount) return right.cardCount - left.cardCount;
                        return right.range - left.range;
                    });

                const targetItem = containers[0];
                if (targetItem) {
                    const target = targetItem.element;
                    const before = target.scrollTop;
                    const maxTop = Math.max(0, target.scrollHeight - target.clientHeight);
                    target.scrollTop = Math.min(before + viewportStep, maxTop);
                    return {
                        moved: target.scrollTop !== before,
                        target: labelFor(target, targetItem.index),
                        scrollY: Math.round(target.scrollTop),
                        scrollHeight: Math.round(target.scrollHeight),
                        clientHeight: Math.round(target.clientHeight),
                    };
                }

                const scrollingElement = document.scrollingElement || document.documentElement;
                const beforeWindowY = window.scrollY || scrollingElement.scrollTop || 0;
                const maxWindowY = Math.max(0, scrollingElement.scrollHeight - window.innerHeight);
                window.scrollTo(0, Math.min(beforeWindowY + viewportStep, maxWindowY));
                const afterWindowY = window.scrollY || scrollingElement.scrollTop || 0;
                return {
                    moved: afterWindowY !== beforeWindowY,
                    target: 'window',
                    scrollY: Math.round(afterWindowY),
                    scrollHeight: Math.round(scrollingElement.scrollHeight),
                    clientHeight: Math.round(window.innerHeight),
                };
            }
            """,
            SCROLL_VIEWPORT_PERCENT,
        )
        return ScrollAdvance(
            moved=bool(result.get("moved")),
            target=str(result.get("target") or "window"),
            scroll_y=int(result.get("scrollY") or 0),
            scroll_height=int(result.get("scrollHeight") or 0),
            client_height=int(result.get("clientHeight") or 0),
        )
    except Exception as exc:
        log_ignored_error("Listing container scroll failed", exc)
        return ScrollAdvance(False, "unknown", scroll_y(page), 0, 0)


def scroll_target_state(page: Page) -> ScrollAdvance:
    try:
        result = page.evaluate(
            """
            () => {
                const scrollingElement = document.scrollingElement || document.documentElement;
                return {
                    target: 'window',
                    scrollY: Math.round(window.scrollY || scrollingElement.scrollTop || 0),
                    scrollHeight: Math.round(scrollingElement.scrollHeight || 0),
                    clientHeight: Math.round(window.innerHeight || scrollingElement.clientHeight || 0),
                };
            }
            """
        )
        return ScrollAdvance(
            moved=False,
            target=str(result.get("target") or "window"),
            scroll_y=int(result.get("scrollY") or 0),
            scroll_height=int(result.get("scrollHeight") or 0),
            client_height=int(result.get("clientHeight") or 0),
        )
    except Exception as exc:
        log_ignored_error("Listing scroll state failed", exc)
        return ScrollAdvance(False, "unknown", scroll_y(page), 0, 0)


def wait_for_lazy_results(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=LAZY_NETWORK_IDLE_TIMEOUT)
    except Exception:
        pass
    page.wait_for_timeout(LAZY_SETTLE_WAIT)
