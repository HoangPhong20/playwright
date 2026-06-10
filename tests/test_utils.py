import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from agoda_crawler.jobs import CrawlJob, CrawlJobResult
from agoda_crawler.utils import append_jsonl, utc_now_iso
from agoda_crawler.utils.logging import log_ignored_error, log_prefix
from agoda_crawler.utils.run_output import (
    CrawlResultWriter,
    crawl_status,
    error_reason,
    is_incremental_publishable_record,
    is_output_record,
    is_publishable_record,
    print_verification_summary,
    project_output_record,
    write_crawl_result,
)


def test_append_jsonl_is_thread_safe(tmp_path) -> None:
    output_path = tmp_path / "output.jsonl"
    records = [{"index": index} for index in range(100)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda record: append_jsonl(output_path, record), records))

    lines = output_path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == len(records)
    assert sorted(json.loads(line)["index"] for line in lines) == list(range(100))


def test_utc_now_iso_uses_seconds_precision_without_timezone_suffix() -> None:
    value = utc_now_iso()

    datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    assert "." not in value
    assert "+" not in value


def test_crawl_result_writer_skips_final_duplicate_after_early_write(tmp_path) -> None:
    output_path = tmp_path / "output.jsonl"
    writer = CrawlResultWriter(output_path)
    early_record = _publishable_record(image_url=None)
    final_record = _publishable_record(image_url="https://images.example/demo.jpg")
    job = CrawlJob("Vung Tau", "2026-06-10", "2026-06-11", output_path)

    assert writer.write_records([early_record]) == 1
    assert write_crawl_result(CrawlJobResult(job, [final_record]), writer) == 0

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["image_url"] is None


def test_crawl_result_writer_writes_partial_record_with_missing_price(tmp_path) -> None:
    output_path = tmp_path / "output.jsonl"
    writer = CrawlResultWriter(output_path)
    missing_price = _publishable_record(price_value=None)
    job = CrawlJob("Vung Tau", "2026-06-10", "2026-06-11", output_path)

    assert writer.write_records([missing_price]) == 1
    assert write_crawl_result(CrawlJobResult(job, [missing_price]), writer) == 0

    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    output = json.loads(lines[0])
    assert output["crawl_status"] == "partial"
    assert output["error_reason"] == "missing_price"


def test_publish_requires_price_and_rating_but_not_review() -> None:
    missing_price = _publishable_record(price_value=None)
    missing_rating = _publishable_record(rating_text=None)
    missing_review = _publishable_record(review_count_text=None)
    missing_image = _publishable_record(image_url=None)
    complete = _publishable_record(image_url="https://images.example/demo.jpg")

    assert is_publishable_record(missing_price) is False
    assert is_publishable_record(missing_rating) is False
    assert is_publishable_record(missing_review) is True
    assert is_publishable_record(missing_image) is True
    assert is_output_record(missing_price) is True
    assert crawl_status(complete) == "success"
    assert crawl_status(missing_price) == "partial"
    assert error_reason(missing_price) == "missing_price"
    assert is_incremental_publishable_record(missing_price) is False
    assert is_incremental_publishable_record(missing_review) is False
    assert is_incremental_publishable_record(missing_image) is False
    assert is_incremental_publishable_record(complete) is True


def test_log_ignored_error_includes_context_type_and_prefix(capsys) -> None:
    with log_prefix("job-1"):
        log_ignored_error("Scroll failed", ValueError("bad state\nmore detail"))

    captured = capsys.readouterr()

    assert captured.out == "[job-1] Scroll failed: ignored ValueError: bad state\n"


def _publishable_record(**overrides):
    record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/demo.html?cid=1",
        "canonical_url": "https://www.agoda.com/demo/hotel/demo.html",
        "price_value": "1000000",
        "rating_text": "8.5",
        "review_count_text": "120",
        "image_url": None,
        "crawled_at": "2026-06-03T00:00:00",
        "destination": "Vung Tau",
        "check_in": "2026-06-10",
        "check_out": "2026-06-11",
    }
    record.update(overrides)
    return record


def test_project_output_record_removes_debug_fields() -> None:
    record = {
        "hotel_name": "Demo Hotel",
        "hotel_url": "https://www.agoda.com/demo/hotel/demo.html",
        "price_value": "1000000",
        "rating_text": "8.5",
        "review_count_text": "120",
        "location_text": "legacy value",
        "image_url": "https://images.example/demo.jpg",
        "crawled_at": "2026-06-03T00:00:00",
        "destination": "Vung Tau",
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
        "image_url",
        "crawled_at",
        "destination",
        "check_in",
        "check_out",
        "crawl_status",
        "error_reason",
    ]
    assert output["crawl_status"] == "success"
    assert output["error_reason"] is None
    assert "canonical_url" not in output
    assert "candidate_urls" not in output
    assert "location_text" not in output
    assert "_listing_scroll_round" not in output
    assert "_pagination" not in output
    assert "_timing" not in output


def test_verification_summary_labels_unlimited_pages_as_all(capsys) -> None:
    records = [
        {
            "hotel_name": "Demo Hotel",
            "hotel_url": "https://www.agoda.com/demo/hotel/demo.html",
            "price_value": "1000000",
            "rating_text": "8.5",
            "review_count_text": "120",
            "image_url": "https://images.example/demo.jpg",
            "_pagination": {
                "pages_requested": 0,
                "pages_collected": 2,
                "duplicate_pages": 1,
            },
        }
    ]

    print_verification_summary(records, elapsed_seconds=10)

    captured = capsys.readouterr()
    assert "- pages=2/all duplicate=1" in captured.out
    assert "VERIFY_MISSING_NAME=0" in captured.out
    assert "VERIFY_OPTIONAL_MIN_COVERAGE=100.0" in captured.out
