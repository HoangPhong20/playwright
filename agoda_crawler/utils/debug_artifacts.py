"""Debug artifact writers for Agoda crawler runs."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Dict, Optional

from playwright.sync_api import Page

from agoda_crawler.config import SAVE_DEBUG_ARTIFACTS
from agoda_crawler.listing.collection import ListingCollectionMetrics
from agoda_crawler.utils.logging import exception_message, log


_DEBUG_CONTEXT: ContextVar[tuple[str, str, str] | None] = ContextVar(
    "debug_context",
    default=None,
)


@contextmanager
def debug_run_context(run_id: str, destination: str, check_in: str):
    token = _DEBUG_CONTEXT.set((run_id, destination, check_in))
    try:
        yield
    finally:
        _DEBUG_CONTEXT.reset(token)


def debug_directory(category: str) -> Path:
    context = _DEBUG_CONTEXT.get()
    if context is None:
        return Path("debug") / category
    run_id, destination, check_in = context
    destination_slug = re.sub(r"[^a-z0-9]+", "-", destination.lower()).strip("-") or "unknown"
    return Path("debug") / run_id / destination_slug / check_in / category


def save_membership_diagnostics(
    page_number: int,
    diagnostics: Dict[str, Any],
    *,
    attempt_kind: str = "crawl",
) -> Path:
    """Write page-scoped membership counters and a bounded URL sample."""
    safe_kind = re.sub(r"[^a-z0-9_-]+", "-", attempt_kind.lower()).strip("-_") or "crawl"
    sample_urls = [
        value[:500]
        for value in diagnostics.get("sample_urls", [])
        if isinstance(value, str) and value
    ][:25]
    report: Dict[str, Any] = {
        "page_number": page_number,
        "attempt_kind": safe_kind,
        "embedded_candidates_seen": int(diagnostics.get("embedded_candidates_seen", 0)),
        "embedded_nonmember_unique": int(diagnostics.get("embedded_nonmember_unique", 0)),
        "embedded_unmatched_at_end": int(diagnostics.get("embedded_unmatched_at_end", 0)),
        "sample_urls": sample_urls,
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    debug_dir = debug_directory("membership")
    debug_dir.mkdir(parents=True, exist_ok=True)
    report_path = debug_dir / f"page_{page_number}_{safe_kind}_{timestamp}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report_path


def save_listing_debug_artifacts(
    page: Page,
    page_number: int,
    metrics: ListingCollectionMetrics,
) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_dir = debug_directory("listing_errors")
    debug_dir.mkdir(parents=True, exist_ok=True)
    base_path = debug_dir / f"page_{page_number}_{timestamp}"
    report_path = base_path.with_suffix(".json")
    html_path = base_path.with_suffix(".html")
    png_path = base_path.with_suffix(".png")

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


def update_page_debug_status(page_number: int, status: str, evidence: Optional[Dict] = None) -> None:
    if status == "collected":
        return
    metrics_path = debug_directory("pagination_errors") / f"page_{page_number}_metrics.json"
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
    debug_dir = debug_directory("pagination_errors")
    debug_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = debug_dir / f"page_{page_number}_metrics.json"
    html_path = debug_dir / f"page_{page_number}.html"
    png_path = debug_dir / f"page_{page_number}.png"
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
            report["html_error"] = exception_message(exc)
        try:
            page.screenshot(path=str(png_path), full_page=True, timeout=10_000)
        except Exception as exc:
            report["screenshot_error"] = exception_message(exc)
    metrics_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
