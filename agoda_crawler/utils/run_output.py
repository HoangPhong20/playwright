"""Output and reporting helpers for Agoda crawl runs."""
from collections import Counter
from pathlib import Path
import threading
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse, urlunparse

from agoda_crawler.jobs import CrawlJobResult
from agoda_crawler.utils import append_jsonl, as_json


FIELDS_TO_CHECK = [
    "hotel_name",
    "hotel_url",
    "price_value",
    "rating_text",
    "review_count_text",
    "star_rating_text",
    "image_url",
]

OUTPUT_RECORD_FIELDS = (
    "hotel_name",
    "hotel_url",
    "price_value",
    "rating_text",
    "review_count_text",
    "star_rating_text",
    "image_url",
    "crawled_at",
    "destination",
    "check_in",
    "check_out",
)
REQUIRED_OUTPUT_FIELDS = (
    "hotel_name",
    "hotel_url",
    "price_value",
    "rating_text",
    "review_count_text",
)


def project_output_record(record: Dict) -> Dict:
    """Return only public crawl fields for JSONL/stdout output."""
    return {field: record.get(field) for field in OUTPUT_RECORD_FIELDS}


def is_publishable_record(record: Dict) -> bool:
    """Return True when a record meets the public output coverage bar."""
    return all(record.get(field) for field in REQUIRED_OUTPUT_FIELDS)


def summarize(records: List[Dict]) -> None:
    total = len(records)
    missing = Counter()
    for rec in records:
        for field in FIELDS_TO_CHECK:
            if not rec.get(field):
                missing[field] += 1

    print("\n=== SUMMARY ===")
    print(f"records={total}")
    if total == 0:
        print("No records found.")
        return

    print("Fields:")
    for field in FIELDS_TO_CHECK:
        miss = missing[field]
        present = total - miss
        present_pct = present * 100.0 / total
        print(f"- {field}: {present}/{total} ({present_pct:.1f}%), missing={miss}")

    likely_detail_page_fields = [
        field for field in FIELDS_TO_CHECK if (missing[field] / total) >= 0.5
    ]
    if likely_detail_page_fields:
        print("Low optional/detail coverage:")
        for field in likely_detail_page_fields:
            print(f"- {field}")
    else:
        print("Listing coverage is sufficient for most fields.")


def print_verification_summary(records: List[Dict], elapsed_seconds: int) -> None:
    detail_attempted = sum(1 for rec in records if rec.get("enrich_status") in {"attempted", "success", "failed"})
    detail_success = sum(1 for rec in records if rec.get("enrich_status") == "success")
    detail_failed = sum(1 for rec in records if rec.get("enrich_status") == "failed")
    scroll_rounds = max((rec.get("_listing_scroll_round") or 0 for rec in records), default=0)
    missing_url = sum(1 for rec in records if not rec.get("hotel_url"))
    missing_price = sum(1 for rec in records if not rec.get("price_value"))
    missing_rating = sum(1 for rec in records if not rec.get("rating_text"))
    records_with_url = sum(1 for rec in records if rec.get("hotel_url"))
    pagination = next((rec.get("_pagination") for rec in records if rec.get("_pagination")), {}) or {}
    timing_summaries: Dict[tuple, Dict] = {}
    for rec in records:
        timing = rec.get("_timing") or {}
        if not timing:
            continue
        key = (
            rec.get("destination") or "",
            rec.get("check_in") or "",
            timing.get("total_seconds", 0),
        )
        timing_summaries.setdefault(key, timing)
    page_unique_record_counts = pagination.get("page_unique_record_counts") or {}
    selected_targets = pagination.get("selected_scroll_targets") or []
    max_visible_dom_cards = pagination.get("max_visible_dom_cards", 0)
    pages_requested = pagination.get("pages_requested", 0)
    pages_requested_label = pages_requested if pages_requested else "all"
    price_present = sum(1 for rec in records if rec.get("price_value"))
    coverage_status = "failed" if missing_price else "success"

    print("Verify:")
    print(f"- seconds={elapsed_seconds}")
    if timing_summaries:
        timing_values = list(timing_summaries.values())
        search_sum = sum(float(item.get("search_seconds") or 0) for item in timing_values)
        listing_sum = sum(float(item.get("listing_seconds") or 0) for item in timing_values)
        detail_sum = sum(float(item.get("detail_seconds") or 0) for item in timing_values)
        total_sum = sum(float(item.get("total_seconds") or 0) for item in timing_values)
        bottleneck = max(
            {
                "search": search_sum,
                "listing": listing_sum,
                "detail": detail_sum,
            },
            key=lambda name: {"search": search_sum, "listing": listing_sum, "detail": detail_sum}[name],
        )
        print(
            "- timing: "
            f"jobs={len(timing_values)} "
            f"search_sum={search_sum:.1f}s "
            f"listing_sum={listing_sum:.1f}s "
            f"detail_sum={detail_sum:.1f}s "
            f"job_total_sum={total_sum:.1f}s "
            f"bottleneck={bottleneck}"
        )
    print(
        f"- pages={pagination.get('pages_collected', 0)}/"
        f"{pages_requested_label} duplicate={pagination.get('duplicate_pages', 0)}"
    )
    if page_unique_record_counts:
        page_counts = ", ".join(
            f"p{page}={count}" for page, count in sorted(page_unique_record_counts.items())
        )
        print(f"- page_records: {page_counts}")
    print(f"- scroll_rounds={scroll_rounds} target={','.join(selected_targets) if selected_targets else ''}")
    print(f"- visible_dom_max={max_visible_dom_cards}")
    print(f"VERIFY_RECORDS_TOTAL={len(records)}")
    print(f"VERIFY_RECORDS_WITH_URL={records_with_url}")
    print(f"VERIFY_RECORDS_MISSING_URL={missing_url}")
    print(f"VERIFY_PRICE_PRESENT={price_present}")
    print(f"VERIFY_MISSING_PRICE={missing_price}")
    print(f"VERIFY_MISSING_RATING={missing_rating}")
    print(f"VERIFY_DETAIL_ATTEMPTED={detail_attempted}")
    print(f"VERIFY_DETAIL_SUCCESS={detail_success}")
    print(f"VERIFY_DETAIL_FAILED={detail_failed}")
    print(f"VERIFY_COVERAGE_STATUS={coverage_status}")


def is_partial_record(record: Dict) -> bool:
    if record.get("collect_status") and record.get("collect_status") != "ok":
        return True
    return not is_publishable_record(record)


class CrawlResultWriter:
    """Append publishable records once for a crawl job."""

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self._written_keys: set[str] = set()
        self._lock = threading.Lock()

    def write_records(self, records: Iterable[Dict]) -> int:
        written = 0
        for record in records:
            if not is_publishable_record(record):
                continue
            identity = output_record_identity(record)
            with self._lock:
                if identity in self._written_keys:
                    continue
                append_jsonl(self.output_path, project_output_record(record))
                self._written_keys.add(identity)
                written += 1
        return written

    def write_result(self, result: CrawlJobResult) -> int:
        return self.write_records(result.records)


def output_record_identity(record: Dict) -> str:
    """Return a stable output identity used only to avoid append duplicates."""
    hotel_url = record.get("canonical_url") or _normalized_output_url(record.get("hotel_url") or "")
    context = (
        record.get("destination") or "",
        record.get("check_in") or "",
        record.get("check_out") or "",
    )
    return "|".join((*context, hotel_url or record.get("hotel_url") or ""))


def _normalized_output_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value.strip().lower()
    path = parsed.path.rstrip("/").lower()
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", "", ""))


def write_crawl_result(result: CrawlJobResult, writer: Optional[CrawlResultWriter] = None) -> int:
    """Append publishable records for one finished crawl job."""
    active_writer = writer or CrawlResultWriter(result.job.output_path)
    return active_writer.write_result(result)


def write_crawl_results(results: List[CrawlJobResult]) -> None:
    for result in results:
        write_crawl_result(result)


def write_latest_outputs(records: List[Dict]) -> None:
    partial_debug_path = Path("debug/partial_missing_url_records.json")
    missing_price_debug_path = Path("debug/missing_price_records.json")
    partial_debug_path.parent.mkdir(parents=True, exist_ok=True)
    partial_debug_records = []
    missing_price_records = []
    for record in records:
        if not record.get("hotel_url"):
            partial_debug_records.append(
                {
                    "hotel_name": record.get("hotel_name"),
                    "card_text_preview": record.get("card_text_preview"),
                    "outer_html_preview": record.get("outer_html_preview"),
                    "available_anchor_hrefs": record.get("available_anchor_hrefs") or [],
                    "raw_candidate_urls": record.get("raw_candidate_urls") or [],
                    "url_sources": record.get("url_sources") or [],
                    "selector": record.get("card_source"),
                    "property_id": record.get("listing_property_id"),
                    "card_source": {
                        "tag": record.get("card_tag"),
                        "data_selenium": record.get("card_data_selenium"),
                        "data_testid": record.get("card_data_testid"),
                    },
                }
            )
        if not record.get("price_value"):
            missing_price_records.append(
                {
                    "hotel_name": record.get("hotel_name"),
                    "hotel_url": record.get("hotel_url"),
                    "canonical_url": record.get("canonical_url"),
                    "property_id": record.get("listing_property_id"),
                    "price_status": record.get("price_status"),
                    "enrich_status": record.get("enrich_status"),
                    "enrich_error": record.get("enrich_error"),
                    "collect_status": record.get("collect_status"),
                    "listing_text_snippet": record.get("listing_text_snippet"),
                    "card_text_preview": record.get("card_text_preview"),
                    "available_anchor_hrefs": record.get("available_anchor_hrefs") or [],
                    "raw_candidate_urls": record.get("raw_candidate_urls") or [],
                    "url_sources": record.get("url_sources") or [],
                    "selector": record.get("card_source"),
                }
            )
    _write_error_debug_json(partial_debug_path, partial_debug_records)
    _write_error_debug_json(missing_price_debug_path, missing_price_records)


def _write_error_debug_json(path: Path, records: List[Dict]) -> None:
    if records:
        path.write_text(as_json(records), encoding="utf-8")
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def has_missing_price(records: List[Dict]) -> bool:
    publishable_candidates = [record for record in records if record.get("hotel_url")]
    return any(not record.get("price_value") for record in publishable_candidates)
