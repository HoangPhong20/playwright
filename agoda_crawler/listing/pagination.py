"""Pagination state and verification helpers for Agoda result pages."""
from dataclasses import dataclass
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import Page

from agoda_crawler.navigation import go_to_next_page, go_to_results_page
from agoda_crawler.listing.scrolling import scroll_y


@dataclass(frozen=True)
class PaginationState:
    page_number: int
    url: str
    active_page_text: str
    scroll_y_after_navigation: int
    scroll_y_after_crawl: int
    first_hotel_identity: str
    canonical_urls: tuple[str, ...]


def attach_pagination_summary(
    records: List[Dict],
    pages_requested: int,
    pages_collected: int,
    duplicate_pages: int,
    page_unique_url_counts: Dict[int, int],
    page_unique_record_counts: Dict[int, int],
    page_statuses: Dict[int, str],
    page_scroll_summaries: Dict[int, Dict],
) -> None:
    summary = {
        "pages_requested": pages_requested,
        "pages_collected": pages_collected,
        "duplicate_pages": duplicate_pages,
        "page_unique_url_counts": {
            str(page_number): count
            for page_number, count in sorted(page_unique_url_counts.items())
        },
        "page_unique_record_counts": {
            str(page_number): count
            for page_number, count in sorted(page_unique_record_counts.items())
        },
        "page_statuses": {
            str(page_number): status
            for page_number, status in sorted(page_statuses.items())
        },
        "page_scroll_summaries": {
            str(page_number): summary
            for page_number, summary in sorted(page_scroll_summaries.items())
        },
        "max_visible_dom_cards": max(
            (summary.get("max_visible_dom_cards", 0) for summary in page_scroll_summaries.values()),
            default=0,
        ),
        "selected_scroll_targets": sorted(
            {
                summary.get("selected_scroll_target", "")
                for summary in page_scroll_summaries.values()
                if summary.get("selected_scroll_target")
            }
        ),
    }
    for record in records:
        record["_pagination"] = summary


def capture_pagination_state(
    page: Page,
    page_number: int,
    records: Optional[List[Dict]] = None,
    scroll_y_after_navigation: Optional[int] = None,
) -> PaginationState:
    records = records or []
    canonical_urls = tuple(
        sorted(
            {
                record.get("canonical_url")
                or _canonical_hotel_url(record.get("hotel_url") or "")
                for record in records
                if record.get("canonical_url") or record.get("hotel_url")
            }
        )
    )
    first_identity = ""
    for record in records:
        first_identity = (
            record.get("canonical_url")
            or record.get("hotel_url")
            or record.get("hotel_name")
            or ""
        )
        if first_identity:
            break

    return PaginationState(
        page_number=page_number,
        url=page.url,
        active_page_text=active_pagination_text(page),
        scroll_y_after_navigation=(
            scroll_y(page) if scroll_y_after_navigation is None else scroll_y_after_navigation
        ),
        scroll_y_after_crawl=scroll_y(page),
        first_hotel_identity=first_identity,
        canonical_urls=canonical_urls,
    )


def active_pagination_text(page: Page) -> str:
    try:
        value = page.evaluate(
            """
            () => {
                const selectors = [
                    '[aria-current="page"]',
                    '[data-selenium="pagination-text"]',
                    '#paginationPageCount',
                    '[class*="pagination" i] [class*="active" i]',
                    '[data-testid*="pagination" i] [aria-current]'
                ];
                for (const selector of selectors) {
                    const element = document.querySelector(selector);
                    if (!element) continue;
                    const text = (
                        element.innerText ||
                        element.getAttribute('aria-label') ||
                        element.getAttribute('title') ||
                        ''
                    ).replace(/\\s+/g, ' ').trim();
                    if (text) return text;
                }
                return '';
            }
            """
        )
    except Exception:
        return ""
    return str(value or "").strip()


def pagination_change_evidence(
    previous: PaginationState,
    current: PaginationState,
) -> Dict:
    previous_urls = set(previous.canonical_urls)
    current_urls = set(current.canonical_urls)
    url_set_changed = bool(previous_urls and current_urls and previous_urls != current_urls)
    first_hotel_changed = bool(
        previous.first_hotel_identity
        and current.first_hotel_identity
        and previous.first_hotel_identity != current.first_hotel_identity
    )
    signs = {
        "url_changed": previous.url != current.url,
        "active_page_changed": (
            bool(previous.active_page_text)
            and bool(current.active_page_text)
            and previous.active_page_text != current.active_page_text
        ),
        "first_hotel_changed": first_hotel_changed,
        "canonical_url_set_changed": url_set_changed,
        "scroll_reset": current.scroll_y_after_navigation < max(100, previous.scroll_y_after_crawl // 3),
    }
    sign_count = sum(1 for changed in signs.values() if changed)
    content_changed = url_set_changed or first_hotel_changed
    return {
        "signs": signs,
        "sign_count": sign_count,
        "content_changed": content_changed,
        "verified": sign_count >= 2 and content_changed,
        "previous": pagination_state_as_dict(previous),
        "current": pagination_state_as_dict(current),
    }


def pagination_state_as_dict(state: PaginationState) -> Dict:
    return {
        "page_number": state.page_number,
        "url": state.url,
        "active_page_text": state.active_page_text,
        "scroll_y_after_navigation": state.scroll_y_after_navigation,
        "scroll_y_after_crawl": state.scroll_y_after_crawl,
        "first_hotel_identity": state.first_hotel_identity,
        "unique_canonical_url_count": len(state.canonical_urls),
        "canonical_urls": list(state.canonical_urls),
    }


def go_to_verified_page_start(page: Page, target_page: int, prefer_next: bool) -> bool:
    navigated = go_to_results_page(page, target_page, prefer_next=prefer_next)
    if not navigated and prefer_next:
        navigated = go_to_next_page(page, target_page)
    if not navigated:
        return False
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass
    try:
        page.wait_for_timeout(750)
    except Exception:
        pass
    return True


def _canonical_hotel_url(hotel_url: str) -> str:
    parsed = urlparse(hotel_url)
    path = parsed.path.rstrip("/").lower()
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))
