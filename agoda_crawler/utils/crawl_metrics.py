"""Timing and coverage helpers for crawl records."""
import time
from typing import Dict, List


def elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 2)


def format_seconds(seconds: float) -> str:
    return f"{seconds:.1f}s"


def timing_bottleneck(timing: Dict[str, float]) -> str:
    candidates = {
        key: timing.get(key, 0.0)
        for key in ("search_seconds", "listing_seconds", "detail_seconds")
    }
    if not candidates:
        return "unknown"
    return max(candidates, key=candidates.get).replace("_seconds", "")


def attach_timing_summary(records: List[Dict], timing: Dict[str, float]) -> None:
    summary = {
        "search_seconds": timing.get("search_seconds", 0.0),
        "listing_seconds": timing.get("listing_seconds", 0.0),
        "detail_seconds": timing.get("detail_seconds", 0.0),
        "total_seconds": timing.get("total_seconds", 0.0),
        "bottleneck": timing_bottleneck(timing),
    }
    for record in records:
        record["_timing"] = summary


def mark_price_coverage_status(records: List[Dict]) -> None:
    for record in records:
        if record.get("price_value"):
            record["price_status"] = "present"
        elif not record.get("hotel_url"):
            record["price_status"] = "missing_no_url"
        elif record.get("enrich_status") == "failed":
            record["price_status"] = "missing_after_detail_retry"
        elif record.get("enrich_status") == "skipped":
            record["price_status"] = "missing_enrich_skipped"
        else:
            record["price_status"] = "missing_after_listing"
