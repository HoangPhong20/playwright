"""Debug artifact writers for Agoda crawler runs."""
from contextlib import contextmanager
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from playwright.sync_api import Page

from agoda_crawler.config import SAVE_DEBUG_ARTIFACTS
from agoda_crawler.utils import utc_now_iso
from agoda_crawler.listing.collection import ListingCollectionMetrics
from agoda_crawler.utils.page_helpers import listing_selector_counts
from agoda_crawler.utils.logging import log


_state = threading.local()


ZERO_CARD_KEYWORDS = (
    "captcha",
    "robot",
    "verify",
    "access denied",
    "unusual traffic",
    "activities",
    "no properties",
    "sold out",
    "loading",
    "hotel",
    "property",
    "0 kết quả",
    "0 cơ sở lưu trú",
    "không thể tìm thấy",
    "đã tìm thấy 0",
)


@contextmanager
def debug_output_context(debug_dir: Optional[Path]) -> Iterator[None]:
    previous = getattr(_state, "debug_dir", None)
    _state.debug_dir = debug_dir
    try:
        yield
    finally:
        _state.debug_dir = previous


def current_debug_output_dir(default: str = "debug") -> Path:
    debug_dir = getattr(_state, "debug_dir", None)
    return Path(debug_dir) if debug_dir else Path(default)


def _debug_path(category: str, filename: str, default: str = "debug") -> Path:
    path = current_debug_output_dir(default) / category / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_listing_debug_artifacts(
    page: Page,
    page_number: int,
    metrics: ListingCollectionMetrics,
) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = _debug_path("logs", f"listing_page_{page_number}_{timestamp}.json")
    html_path = _debug_path("html", f"listing_page_{page_number}_{timestamp}.html")
    png_path = _debug_path("screenshots", f"listing_page_{page_number}_{timestamp}.png")

    report = {
        "page_number": page_number,
        "url": page.url,
        "metrics": metrics.as_dict(),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        page.screenshot(path=str(png_path), full_page=True, timeout=10_000)
    except Exception:
        pass
    log(f"Listing debug saved: {report_path}")


def save_listing_zero_cards_artifacts(
    page: Page,
    destination: str,
    check_in: str,
    check_out: str,
    context: Optional[Dict] = None,
) -> Dict:
    """Save diagnostics for a loaded search page with zero listing cards."""
    report = listing_zero_cards_report(
        page,
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        context=context,
    )
    if not SAVE_DEBUG_ARTIFACTS:
        return report

    html_path = _debug_path("html", "listing_zero_cards.html", default="data/debug/docker_phase2")
    png_path = _debug_path("screenshots", "listing_zero_cards.png", default="data/debug/docker_phase2")
    body_path = _debug_path("logs", "listing_zero_cards_body.txt", default="data/debug/docker_phase2")
    meta_path = _debug_path("logs", "listing_zero_cards_meta.json", default="data/debug/docker_phase2")

    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        report["html_error"] = str(exc).splitlines()[0]
    try:
        body_path.write_text(report.get("body_preview") or "", encoding="utf-8")
    except Exception as exc:
        report["body_error"] = str(exc).splitlines()[0]
    try:
        page.screenshot(path=str(png_path), full_page=True, timeout=10_000)
    except Exception as exc:
        report["screenshot_error"] = str(exc).splitlines()[0]
    meta_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Listing zero-card debug saved: {meta_path}")
    return report


def listing_zero_cards_report(
    page: Page,
    destination: str,
    check_in: str,
    check_out: str,
    context: Optional[Dict] = None,
) -> Dict:
    body_preview = _body_text_preview(page)
    body_lower = body_preview.casefold()
    return {
        "current_url": _safe_page_url(page),
        "page_title": _safe_page_title(page),
        "destination": destination,
        "check_in": check_in,
        "check_out": check_out,
        "timestamp": utc_now_iso(),
        "viewport": _safe_viewport(page),
        "user_agent": _safe_user_agent(page),
        "selector_counts": listing_selector_counts(page),
        "detected_keywords": [
            keyword for keyword in ZERO_CARD_KEYWORDS if keyword in body_lower
        ],
        "is_activities_url": "/activities/" in _safe_page_url(page).casefold(),
        "body_preview": body_preview,
        "context": context or {},
    }


def _safe_page_url(page: Page) -> str:
    try:
        return page.url
    except Exception:
        return ""


def _safe_page_title(page: Page) -> str:
    try:
        return page.title()
    except Exception:
        return ""


def _safe_viewport(page: Page) -> Optional[Dict]:
    try:
        return page.viewport_size
    except Exception:
        return None


def _safe_user_agent(page: Page) -> str:
    try:
        return str(page.evaluate("() => navigator.userAgent") or "")
    except Exception:
        return ""


def _body_text_preview(page: Page, max_chars: int = 4_000) -> str:
    try:
        text = page.locator("body").inner_text(timeout=2_000)
    except Exception:
        text = ""
    return text[:max_chars]


def save_final_listing_artifacts(
    page: Page,
    page_number: int,
    metrics: ListingCollectionMetrics,
    scroll_rounds: int,
    scroll_metrics: List[Dict],
    selected_scroll_target: str,
) -> None:
    return


def update_page_debug_status(page_number: int, status: str, evidence: Optional[Dict] = None) -> None:
    if status == "collected":
        return
    metrics_path = _debug_path("logs", f"pagination_page_{page_number}_metrics.json")
    if metrics_path.exists():
        try:
            report = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            report = {"page_number": page_number}
    else:
        report = {"page_number": page_number}
    report["pagination_status"] = status
    if evidence is not None:
        report["pagination_evidence"] = evidence
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def save_pagination_page_artifacts(
    page: Page,
    page_number: int,
    status: str,
    evidence: Optional[Dict] = None,
) -> None:
    if status == "collected":
        return
    metrics_path = _debug_path("logs", f"pagination_page_{page_number}_metrics.json")
    html_path = _debug_path("html", f"pagination_page_{page_number}.html")
    png_path = _debug_path("screenshots", f"pagination_page_{page_number}.png")
    report = {
        "page_number": page_number,
        "pagination_status": status,
        "url": page.url,
    }
    if evidence is not None:
        report["pagination_evidence"] = evidence
    if SAVE_DEBUG_ARTIFACTS:
        try:
            html_path.write_text(page.content(), encoding="utf-8")
        except Exception as exc:
            report["html_error"] = str(exc).splitlines()[0]
        try:
            page.screenshot(path=str(png_path), full_page=True, timeout=10_000)
        except Exception as exc:
            report["screenshot_error"] = str(exc).splitlines()[0]
    metrics_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
