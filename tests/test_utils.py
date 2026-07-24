import json
from concurrent.futures import ThreadPoolExecutor

from agoda_crawler.utils import append_jsonl
from agoda_crawler.utils.logging import log_ignored_error, log_prefix
from agoda_crawler.utils.run_output import (
    is_publishable_record,
    optional_coverage_status,
    print_verification_summary,
    project_output_record,
)


def test_append_jsonl_is_thread_safe(tmp_path) -> None:
    output_path = tmp_path / "output.jsonl"
    records = [{"index": index} for index in range(100)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda record: append_jsonl(output_path, record), records))

    lines = output_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == len(records)
    assert sorted(json.loads(line)["index"] for line in lines) == list(range(100))


def test_log_ignored_error_includes_context_type_and_prefix(capsys) -> None:
    with log_prefix("job-1"):
        log_ignored_error("Scroll failed", ValueError("bad state\nmore detail"))

    captured = capsys.readouterr()

    assert captured.out == "[job-1] Scroll failed: ignored ValueError: bad state\n"


def test_project_output_record_removes_debug_fields() -> None:
    record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/demo.html",
        "price_value": "1000000",
        "rating_text": "8.5",
        "review_count_text": "120",
        "star_rating_text": "4 stars",
        "crawled_at": "2026-06-03T00:00:00+00:00",
        "destination": "Vung Tau",
        "normalized_destination": "Vung Tau",
        "check_in": "2026-06-10",
        "check_out": "2026-06-11",
        "canonical_url": "https://www.agoda.com/demo/hotel/demo.html",
        "candidate_urls": ["https://www.agoda.com/demo/hotel/demo.html?cid=1"],
        "_listing_scroll_round": 12,
        "_pagination": {"pages_collected": 2},
        "_timing": {"total_seconds": 10},
    }

    output = project_output_record(record)

    assert list(output) == [
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
    ]
    assert "canonical_url" not in output
    assert "candidate_urls" not in output
    assert "_listing_scroll_round" not in output
    assert "_pagination" not in output
    assert "_timing" not in output


def test_only_name_url_and_price_are_required_for_public_output() -> None:
    record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/demo.html",
        "price_value": "1000000",
    }

    assert is_publishable_record(record) is True
    for required_field in ("hotel_name", "hotel_url", "price_value"):
        incomplete = dict(record)
        incomplete[required_field] = None
        assert is_publishable_record(incomplete) is False


def test_optional_coverage_requires_strictly_more_than_threshold() -> None:
    records = [
        {
            "hotel_name": f"Hotel {index}",
            "hotel_url": f"https://www.agoda.com/hotel/{index}.html",
            "price_value": "1000000",
            "rating_text": "8.5" if index < 9 else None,
            "review_count_text": "120" if index < 9 else None,
            "star_rating_text": "4 stars" if index < 9 else None,
        }
        for index in range(10)
    ]

    status, coverage = optional_coverage_status(records, minimum_coverage=90.0)

    assert coverage == {
        "rating_text": 90.0,
        "review_count_text": 90.0,
        "star_rating_text": 90.0,
    }
    assert status == "warning"


def test_verification_summary_labels_unlimited_pages_as_all(capsys) -> None:
    records = [
        {
            "hotel_name": "Demo Hotel",
            "hotel_url": "https://www.agoda.com/demo/hotel/demo.html",
            "price_value": "1000000",
            "rating_text": "8.5",
            "_pagination": {
                "pages_requested": 0,
                "pages_collected": 2,
                "duplicate_pages": 1,
            },
        }
    ]

    print_verification_summary(
        records,
        elapsed_seconds=10,
        discarded_records=[{"hotel_name": None, "missing_required_fields": ["hotel_name"]}],
    )

    captured = capsys.readouterr()
    assert "- pages=2/all duplicate=1" in captured.out
    assert "VERIFY_OPTIONAL_COVERAGE_STATUS=warning" in captured.out
    assert "VERIFY_DISCARDED_RECORDS=1" in captured.out
    assert "VERIFY_COVERAGE_STATUS=warning" in captured.out
