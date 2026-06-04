"""Debug artifact writers for Agoda crawler runs."""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from playwright.sync_api import Page

from agoda_crawler.config import SAVE_DEBUG_ARTIFACTS
from agoda_crawler.listing.collection import ListingCollectionMetrics
from agoda_crawler.utils.logging import log


def save_listing_debug_artifacts(
    page: Page,
    page_number: int,
    metrics: ListingCollectionMetrics,
) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_dir = Path("debug/listing_errors")
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
    metrics_path = Path("debug/pagination_errors") / f"page_{page_number}_metrics.json"
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
    debug_dir = Path("debug/pagination_errors")
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
            report["html_error"] = str(exc).splitlines()[0]
        try:
            page.screenshot(path=str(png_path), full_page=True, timeout=10_000)
        except Exception as exc:
            report["screenshot_error"] = str(exc).splitlines()[0]
    metrics_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
