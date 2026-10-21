"""Timing and coverage helpers for crawl records."""
import time
from typing import Dict, List


_MAX_JOB_METRICS = {"scroll_rounds_max", "slot_wait_seconds_max"}


def elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 2)


def format_seconds(seconds: float) -> str:
    return f"{seconds:.1f}s"


def aggregate_scroll_metrics(attempt_metrics: List[Dict]) -> Dict[str, int]:
    """Aggregate scroll work across page collections and pagination probes."""
    total_rounds = 0
    max_rounds = 0
    total_actions = 0
    for metrics in attempt_metrics:
        rounds = metrics.get("scroll_rounds_total", metrics.get("scroll_rounds", 0))
        max_rounds = max(
            max_rounds,
            metrics.get("scroll_rounds_max", metrics.get("scroll_rounds", 0)),
        )
        total_rounds += rounds
        total_actions += metrics.get("scroll_actions", 0)
    return {
        "scroll_rounds_total": total_rounds,
        "scroll_rounds_max": max_rounds,
        "scroll_actions": total_actions,
    }


def aggregate_job_metrics(job_metrics: List[Dict]) -> Dict:
    """Sum per-job metrics except explicitly max-aggregated values."""
    totals: Dict = {}
    for metrics in job_metrics:
        for key, value in metrics.items():
            if value is None:
                continue
            if key in _MAX_JOB_METRICS:
                totals[key] = max(totals.get(key, value), value)
            else:
                totals[key] = totals.get(key, 0) + value
    return totals


def timing_bottleneck(timing: Dict[str, float]) -> str:
    candidates = {
        key: timing.get(key, 0.0)
        for key in ("search_seconds", "listing_seconds", "detail_seconds")
    }
    if not candidates:
        return "unknown"
    return max(candidates, key=lambda metric: candidates[metric]).replace(
        "_seconds", ""
    )


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
