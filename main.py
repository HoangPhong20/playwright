"""CLI entrypoint for the Agoda crawler."""
import argparse
from typing import Dict, Optional

from agoda_crawler.config import DEFAULT_LOCALE, env_bool, env_int, load_config_env
from agoda_crawler.orchestration import (
    DEFAULT_DATE_END,
    DEFAULT_DATE_START,
    DEFAULT_DESTINATION,
    DEFAULT_DESTINATIONS,
    DEFAULT_DETAIL_CONCURRENCY,
    DEFAULT_DETAIL_FIELDS,
    DEFAULT_DETAIL_TIMEOUT,
    DEFAULT_FIELD_RETRY_COUNT,
    DEFAULT_FIELD_RETRY_TIMEOUT,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_SCROLL_ROUNDS,
    DEFAULT_SCROLL_WAIT_MS,
    DEFAULT_STABLE_ROUNDS,
    DEFAULT_WORKERS,
    CrawlJob,
    CrawlJobResult,
    annotate_record,
    build_crawl_jobs,
    has_missing_price,
    iter_stays,
    jobs_for_stay,
    ordered_results,
    parse_date,
    parse_destinations,
    parse_detail_fields,
    run_from_args,
)


def parse_args(env: Optional[Dict[str, str]] = None) -> argparse.Namespace:
    config = load_config_env() if env is None else env
    parser = argparse.ArgumentParser(description="Agoda search POC crawler (Playwright sync API)")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=env_int(config, "AGODA_MAX_PAGES", DEFAULT_MAX_PAGES),
        help="Max result pages to crawl; 0 means all pages",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=env_bool(config, "AGODA_HEADLESS", False),
        help="Run browser in headless mode",
    )
    parser.add_argument("--destination", default=config.get("AGODA_DESTINATION", DEFAULT_DESTINATION), help="Destination text (e.g. Vung Tau)")
    parser.add_argument(
        "--destinations",
        default=config.get("AGODA_DESTINATIONS", DEFAULT_DESTINATIONS),
        help="Comma-separated destinations for batch crawl",
    )
    parser.add_argument("--check-in", default=config.get("AGODA_CHECK_IN", "2026-06-10"), help="Check-in date YYYY-MM-DD")
    parser.add_argument("--check-out", default=config.get("AGODA_CHECK_OUT", "2026-06-11"), help="Check-out date YYYY-MM-DD")
    parser.add_argument("--date-start", default=config.get("AGODA_DATE_START", DEFAULT_DATE_START), help="First check-in date for batch crawl")
    parser.add_argument("--date-end", default=config.get("AGODA_DATE_END", DEFAULT_DATE_END), help="Last check-in date for batch crawl")
    parser.add_argument("--adults", type=int, default=env_int(config, "AGODA_ADULTS", 2), help="Number of adults")
    parser.add_argument("--rooms", type=int, default=env_int(config, "AGODA_ROOMS", 1), help="Number of rooms")
    parser.add_argument("--children", type=int, default=env_int(config, "AGODA_CHILDREN", 0), help="Number of children")
    parser.add_argument("--locale", default=config.get("AGODA_LOCALE", DEFAULT_LOCALE), help="Agoda locale, e.g. en-us or vi-vn")
    parser.add_argument("--output-dir", default=config.get("AGODA_OUTPUT_DIR", "data"), help="Directory for dated JSONL output")
    parser.add_argument(
        "--enrich-details",
        action=argparse.BooleanOptionalAction,
        default=env_bool(config, "AGODA_ENRICH_DETAILS", True),
        help="Open hotel detail pages to fill missing fields",
    )
    parser.add_argument(
        "--max-detail-pages",
        type=int,
        default=env_int(config, "AGODA_MAX_DETAIL_PAGES", 0),
        help="Maximum detail pages to enrich; 0 means all hotels",
    )
    parser.add_argument(
        "--enrich-missing-only",
        action=argparse.BooleanOptionalAction,
        default=env_bool(config, "AGODA_ENRICH_MISSING_ONLY", True),
        help="Only open detail pages for hotels missing price or critical fields",
    )
    parser.add_argument(
        "--detail-timeout",
        type=int,
        default=env_int(config, "AGODA_DETAIL_TIMEOUT", DEFAULT_DETAIL_TIMEOUT),
        help="Detail page load/navigation timeout in milliseconds",
    )
    parser.add_argument(
        "--field-retry-timeout",
        type=int,
        default=env_int(config, "AGODA_FIELD_RETRY_TIMEOUT", DEFAULT_FIELD_RETRY_TIMEOUT),
        help="Per-field detail retry wait timeout in milliseconds",
    )
    parser.add_argument(
        "--field-retry-count",
        type=int,
        default=env_int(config, "AGODA_FIELD_RETRY_COUNT", DEFAULT_FIELD_RETRY_COUNT),
        help="Retry count for missing detail fields after the detail page loads",
    )
    parser.add_argument(
        "--detail-fields",
        default=config.get("AGODA_DETAIL_FIELDS", DEFAULT_DETAIL_FIELDS),
        help="Comma-separated fields that should trigger detail enrichment when missing",
    )
    parser.add_argument(
        "--max-scroll-rounds",
        type=int,
        default=env_int(config, "AGODA_MAX_SCROLL_ROUNDS", DEFAULT_MAX_SCROLL_ROUNDS),
        help="Maximum scroll/load rounds per result page in complete mode",
    )
    parser.add_argument(
        "--stable-rounds",
        type=int,
        default=env_int(config, "AGODA_STABLE_ROUNDS", DEFAULT_STABLE_ROUNDS),
        help="Stop after this many rounds without new unique records",
    )
    parser.add_argument(
        "--scroll-wait-ms",
        type=int,
        default=env_int(config, "AGODA_SCROLL_WAIT_MS", DEFAULT_SCROLL_WAIT_MS),
        help="Wait time after each listing scroll in milliseconds",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=env_int(config, "AGODA_WORKERS", DEFAULT_WORKERS),
        help="Parallel crawl workers; each worker reuses one browser",
    )
    parser.add_argument(
        "--detail-concurrency",
        type=int,
        default=env_int(config, "AGODA_DETAIL_CONCURRENCY", DEFAULT_DETAIL_CONCURRENCY),
        help="Parallel detail pages per crawl job",
    )
    parser.add_argument(
        "--print-records",
        action=argparse.BooleanOptionalAction,
        default=env_bool(config, "AGODA_PRINT_RECORDS", False),
        help="Print each crawled JSON record to stdout",
    )
    return parser.parse_args()


def main() -> None:
    run_from_args(parse_args())


if __name__ == "__main__":
    main()
