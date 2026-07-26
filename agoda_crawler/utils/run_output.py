"""Output and reporting helpers for Agoda crawl runs."""
from collections import Counter
from pathlib import Path
from typing import Dict, List

from agoda_crawler.config import MIN_OPTIONAL_COVERAGE
from agoda_crawler.jobs import CrawlJobResult
from agoda_crawler.utils import append_jsonl, as_json


FIELDS_TO_CHECK = [
    "hotel_name",
    "hotel_url",
    "price_value",
    "rating_text",
    "review_count_text",
    "star_rating_text",
]

OUTPUT_RECORD_FIELDS = (
    "hotel_name",
    "hotel_url",
    "price_value",
    "rating_text",
    "review_count_text",
    "star_rating_text",
    "crawled_at",
    "destination",
    "normalized_destination",
    "check_in",
    "check_out",
    "batch_id",
    "airflow_dag_id",
    "airflow_run_id",
    "airflow_try_number",
)
REQUIRED_OUTPUT_FIELDS = (
    "hotel_name",
    "hotel_url",
    "price_value",
)
OPTIONAL_COVERAGE_FIELDS = ("rating_text", "review_count_text", "star_rating_text")


def project_output_record(record: Dict) -> Dict:
    """Return only public crawl fields for JSONL/stdout output."""
    return {field: record.get(field) for field in OUTPUT_RECORD_FIELDS}


def is_publishable_record(record: Dict) -> bool:
    """Return True when a record meets the public output coverage bar."""
    return all(record.get(field) for field in REQUIRED_OUTPUT_FIELDS)


def missing_required_fields(record: Dict) -> tuple[str, ...]:
    return tuple(field for field in REQUIRED_OUTPUT_FIELDS if not record.get(field))


def field_coverage_percentage(records: List[Dict], field: str) -> float:
    if not records:
        return 0.0
    present = sum(1 for record in records if record.get(field))
    return present * 100.0 / len(records)


def optional_coverage_status(
    records: List[Dict],
    minimum_coverage: float = MIN_OPTIONAL_COVERAGE,
) -> tuple[str, Dict[str, float]]:
    coverage = {
        field: field_coverage_percentage(records, field)
        for field in OPTIONAL_COVERAGE_FIELDS
    }
    status = "success" if all(value > minimum_coverage for value in coverage.values()) else "warning"
    return status, coverage


def summarize(records: List[Dict], minimum_optional_coverage: float = MIN_OPTIONAL_COVERAGE) -> None:
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

    optional_status, optional_coverage = optional_coverage_status(records, minimum_optional_coverage)
    if optional_status == "warning":
        print(f"Optional coverage warning: each field must be > {minimum_optional_coverage:.1f}%")
        for field, coverage in optional_coverage.items():
            if coverage <= minimum_optional_coverage:
                print(f"- {field}: {coverage:.1f}%")
    else:
        print(f"Optional coverage rule passed: each field is > {minimum_optional_coverage:.1f}%.")


def print_verification_summary(
    records: List[Dict],
    elapsed_seconds: int,
    discarded_records: List[Dict] | None = None,
    minimum_optional_coverage: float = MIN_OPTIONAL_COVERAGE,
) -> None:
    discarded_records = discarded_records or []
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
    optional_status, optional_coverage = optional_coverage_status(records, minimum_optional_coverage)
    coverage_status = "warning" if discarded_records else "success"

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
    print(f"- discarded_records={len(discarded_records)}")
    print(f"VERIFY_RECORDS_TOTAL={len(records)}")
    print(f"VERIFY_RECORDS_WITH_URL={records_with_url}")
    print(f"VERIFY_RECORDS_MISSING_URL={missing_url}")
    print(f"VERIFY_PRICE_PRESENT={price_present}")
    print(f"VERIFY_MISSING_PRICE={missing_price}")
    print(f"VERIFY_MISSING_RATING={missing_rating}")
    print(f"VERIFY_DETAIL_ATTEMPTED={detail_attempted}")
    print(f"VERIFY_DETAIL_SUCCESS={detail_success}")
    print(f"VERIFY_DETAIL_FAILED={detail_failed}")
    print(f"VERIFY_RATING_COVERAGE={optional_coverage['rating_text']:.1f}")
    print(f"VERIFY_REVIEW_COUNT_COVERAGE={optional_coverage['review_count_text']:.1f}")
    print(f"VERIFY_STAR_RATING_COVERAGE={optional_coverage['star_rating_text']:.1f}")
    print(f"VERIFY_OPTIONAL_COVERAGE_STATUS={optional_status}")
    print(f"VERIFY_DISCARDED_RECORDS={len(discarded_records)}")
    print(f"VERIFY_COVERAGE_STATUS={coverage_status}")


def write_crawl_results(results: List[CrawlJobResult]) -> None:
    for result in results:
        for record in result.records:
            if not is_publishable_record(record):
                continue
            append_jsonl(result.job.output_path, project_output_record(record))


def write_latest_outputs(records: List[Dict], debug_dir: Path | None = None) -> None:
    """Write diagnostic records without mixing separate crawler runs."""
    target_dir = debug_dir or Path("debug")
    partial_debug_path = target_dir / "partial_missing_url_records.json"
    missing_price_debug_path = target_dir / "missing_price_records.json"
    discarded_debug_path = target_dir / "discarded_records.json"
    partial_debug_path.parent.mkdir(parents=True, exist_ok=True)
    partial_debug_records = []
    missing_price_records = []
    discarded_records = []
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
        missing_required = missing_required_fields(record)
        if missing_required:
            discarded_records.append(
                {
                    "hotel_name": record.get("hotel_name"),
                    "hotel_url": record.get("hotel_url"),
                    "price_value": record.get("price_value"),
                    "missing_required_fields": list(missing_required),
                    "collect_status": record.get("collect_status"),
                    "enrich_status": record.get("enrich_status"),
                    "enrich_error": record.get("enrich_error"),
                    "card_text_preview": record.get("card_text_preview"),
                }
            )
    _write_error_debug_json(partial_debug_path, partial_debug_records)
    _write_error_debug_json(missing_price_debug_path, missing_price_records)
    _write_error_debug_json(discarded_debug_path, discarded_records)


def _write_error_debug_json(path: Path, records: List[Dict]) -> None:
    if records:
        path.write_text(as_json(records), encoding="utf-8")
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
