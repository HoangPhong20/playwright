import sys
from queue import Empty

from agoda_crawler.config import load_dotenv
from main import (
    annotate_record,
    CrawlJobResult,
    build_crawl_jobs,
    has_missing_price,
    iter_stays,
    jobs_for_stay,
    ordered_results,
    parse_args,
    parse_date,
    parse_destinations,
    parse_detail_fields,
)
from agoda_crawler import orchestration
from agoda_crawler.orchestration import (
    actual_worker_count,
    estimated_detail_pressure,
    should_fail_on_missing_price,
)
from agoda_crawler.utils.run_output import project_output_record


def test_parse_args_defaults_to_enrich_all_details(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py"])

    args = parse_args(env={})

    assert args.enrich_details is True
    assert args.max_detail_pages == 0
    assert args.output_dir == "data"
    assert args.max_pages == 10
    assert args.destinations == "Vung Tau,Da Nang,Nha Trang"
    assert args.date_start == "2026-06-01"
    assert args.date_end == "2026-06-30"
    assert not hasattr(args, "nights")
    assert args.workers == 3
    assert args.detail_concurrency == 2
    assert args.enrich_missing_only is True
    assert args.detail_timeout == 30000
    assert args.field_retry_timeout == 1500
    assert args.field_retry_count == 2
    assert args.detail_fields == "price_value,rating_text"
    assert args.max_scroll_rounds == 80
    assert args.stable_rounds == 3
    assert args.scroll_wait_ms == 1000
    assert args.print_records is False


def test_has_missing_price_detects_incomplete_records() -> None:
    assert has_missing_price([{"hotel_name": "A", "price_value": "1000"}]) is False
    assert has_missing_price(
        [{"hotel_name": "A", "hotel_url": "https://www.agoda.com/a/hotel/x.html", "price_value": None}]
    ) is True
    assert has_missing_price([{"hotel_name": "A", "hotel_url": None, "price_value": None}]) is False


def test_coverage_gate_does_not_hard_fail_missing_price_records(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--enrich-details", "--max-detail-pages", "0"],
    )
    assert should_fail_on_missing_price(parse_args(env={})) is False

    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--enrich-details", "--max-detail-pages", "2"],
    )
    assert should_fail_on_missing_price(parse_args(env={})) is False

    monkeypatch.setattr(sys, "argv", ["main.py", "--no-enrich-details"])
    assert should_fail_on_missing_price(parse_args(env={})) is False


def test_annotate_record_adds_job_metadata() -> None:
    record = {"hotel_name": "A"}

    annotated = annotate_record(record, "Vung Tau", "2026-06-10", "2026-06-11")

    assert annotated["destination"] == "Vung Tau"
    assert "normalized_destination" not in annotated
    assert annotated["check_in"] == "2026-06-10"
    assert annotated["check_out"] == "2026-06-11"


def test_parse_detail_fields_accepts_known_fields() -> None:
    assert parse_detail_fields("price_value,image_url") == ("price_value", "image_url")


def test_parse_detail_fields_rejects_unknown_fields() -> None:
    try:
        parse_detail_fields("price_value,bad_field")
    except ValueError as exc:
        assert "bad_field" in str(exc)
    else:
        raise AssertionError("parse_detail_fields should reject unknown fields")


def test_parse_detail_fields_rejects_removed_location_field() -> None:
    try:
        parse_detail_fields("price_value,location_text")
    except ValueError as exc:
        assert "location_text" in str(exc)
    else:
        raise AssertionError("location_text should not be accepted")


def test_parse_detail_fields_rejects_removed_star_rating_field() -> None:
    try:
        parse_detail_fields("price_value,star_rating_text")
    except ValueError as exc:
        assert "star_rating_text" in str(exc)
    else:
        raise AssertionError("star_rating_text should not be accepted")


def test_parse_args_can_disable_detail_enrichment(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--no-enrich-details"])

    args = parse_args(env={})

    assert args.enrich_details is False


def test_parse_args_accepts_output_dir(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--output-dir", "data/raw/prod"])

    args = parse_args(env={})

    assert args.output_dir == "data/raw/prod"


def test_parse_args_uses_env_defaults(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py"])

    args = parse_args(
        env={
            "AGODA_DESTINATION": "Da Nang",
            "AGODA_MAX_PAGES": "5",
            "AGODA_HEADLESS": "true",
            "AGODA_OUTPUT_DIR": "data/raw",
            "AGODA_ENRICH_DETAILS": "false",
            "AGODA_WORKERS": "3",
            "AGODA_DETAIL_CONCURRENCY": "3",
            "AGODA_DETAIL_TIMEOUT": "20000",
            "AGODA_FIELD_RETRY_TIMEOUT": "1200",
            "AGODA_FIELD_RETRY_COUNT": "1",
            "AGODA_DETAIL_FIELDS": "price_value,image_url",
            "AGODA_ENRICH_MISSING_ONLY": "false",
            "AGODA_MAX_SCROLL_ROUNDS": "40",
            "AGODA_STABLE_ROUNDS": "5",
            "AGODA_SCROLL_WAIT_MS": "1500",
        }
    )

    assert args.destination == "Da Nang"
    assert args.max_pages == 5
    assert args.headless is True
    assert args.output_dir == "data/raw"
    assert args.enrich_details is False
    assert args.workers == 3
    assert args.detail_concurrency == 3
    assert args.detail_timeout == 20000
    assert args.field_retry_timeout == 1200
    assert args.field_retry_count == 1
    assert args.detail_fields == "price_value,image_url"
    assert args.enrich_missing_only is False
    assert args.max_scroll_rounds == 40
    assert args.stable_rounds == 5
    assert args.scroll_wait_ms == 1500


def test_cli_args_override_env_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--destination", "Hue", "--max-pages", "1", "--no-headless"],
    )

    args = parse_args(env={"AGODA_DESTINATION": "Da Nang", "AGODA_MAX_PAGES": "5", "AGODA_HEADLESS": "true"})

    assert args.destination == "Hue"
    assert args.max_pages == 1
    assert args.headless is False


def test_load_dotenv_reads_key_value_file(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "# crawler config",
                "AGODA_DESTINATION=\"Vung Tau\"",
                "AGODA_MAX_PAGES=2",
                "export AGODA_HEADLESS=true",
            ]
        ),
        encoding="utf-8",
    )

    values = load_dotenv(str(env_path))

    assert values["AGODA_DESTINATION"] == "Vung Tau"
    assert values["AGODA_MAX_PAGES"] == "2"
    assert values["AGODA_HEADLESS"] == "true"


def test_parse_destinations_splits_comma_separated_values() -> None:
    assert parse_destinations("Vung Tau, Da Nang,Nha Trang", "Hue") == [
        "Vung Tau",
        "Da Nang",
        "Nha Trang",
    ]
    assert parse_destinations("", "Hue") == ["Hue"]


def test_parse_date_accepts_iso_and_vietnamese_format() -> None:
    assert parse_date("2026-06-01").isoformat() == "2026-06-01"
    assert parse_date("01/06/2026").isoformat() == "2026-06-01"


def test_iter_stays_builds_one_file_per_check_in_day(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--date-start", "2026-06-01", "--date-end", "2026-06-03"],
    )

    args = parse_args(env={})

    assert iter_stays(args) == [
        ("2026-06-01", "2026-06-02"),
        ("2026-06-02", "2026-06-03"),
        ("2026-06-03", "2026-06-04"),
    ]


def test_parse_args_rejects_removed_nights_option(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--nights", "2"])

    try:
        parse_args(env={})
    except SystemExit:
        return

    raise AssertionError("--nights should not be accepted")


def test_build_crawl_jobs_creates_destination_date_matrix(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--destinations",
            "Vung Tau,Da Nang,Nha Trang",
            "--date-start",
            "2026-06-01",
            "--date-end",
            "2026-06-30",
        ],
    )

    args = parse_args(env={})
    destinations = parse_destinations(args.destinations, args.destination)
    stays = iter_stays(args)
    jobs = build_crawl_jobs(args, destinations, stays)

    assert len(jobs) == 90
    assert jobs[0].destination == "Vung Tau"
    assert jobs[0].check_in == "2026-06-01"
    assert jobs[0].check_out == "2026-06-02"
    assert jobs[0].output_path.name == "agoda_hotels_2026-06-01.jsonl"
    assert jobs[-1].destination == "Nha Trang"
    assert jobs[-1].check_in == "2026-06-30"


def test_jobs_for_stay_keeps_one_day_batch(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--destinations",
            "Vung Tau,Da Nang",
            "--date-start",
            "2026-06-01",
            "--date-end",
            "2026-06-02",
        ],
    )

    args = parse_args(env={})
    destinations = parse_destinations(args.destinations, args.destination)
    jobs = build_crawl_jobs(args, destinations, iter_stays(args))

    stay_jobs = jobs_for_stay(jobs, "2026-06-01")

    assert [job.destination for job in stay_jobs] == ["Vung Tau", "Da Nang"]
    assert {job.check_in for job in stay_jobs} == {"2026-06-01"}
    assert {job.output_path.name for job in stay_jobs} == {
        "agoda_hotels_2026-06-01.jsonl"
    }


def test_ordered_results_restores_destination_order(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--destinations", "Vung Tau,Da Nang"],
    )

    args = parse_args(env={})
    destinations = parse_destinations(args.destinations, args.destination)
    jobs = build_crawl_jobs(args, destinations, [("2026-06-01", "2026-06-02")])
    results = [
        CrawlJobResult(job=jobs[1], records=[]),
        CrawlJobResult(job=jobs[0], records=[]),
    ]

    assert [result.job.destination for result in ordered_results(jobs, results)] == [
        "Vung Tau",
        "Da Nang",
    ]


def test_actual_worker_count_caps_requested_workers_to_jobs() -> None:
    assert actual_worker_count(5, 3) == 3
    assert actual_worker_count(5, 9) == 5
    assert actual_worker_count(0, 3) == 1
    assert actual_worker_count(3, 0) == 0


def test_run_crawl_job_keeps_incomplete_records_as_partial_output(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py"])
    args = parse_args(env={})
    job = orchestration.CrawlJob(
        "Vung Tau",
        "2026-06-10",
        "2026-06-11",
        tmp_path / "out.jsonl",
    )

    def fake_crawl(*_args, **_kwargs):
        return [
            {
                "hotel_name": "Complete Hotel",
                "hotel_url": "https://www.agoda.com/complete.html",
                "price_value": "1000000",
                "rating_text": "8.5",
            },
            {
                "hotel_name": "Missing Price",
                "hotel_url": "https://www.agoda.com/missing-price.html",
                "price_value": None,
                "rating_text": "8.0",
            },
        ]

    monkeypatch.setattr(orchestration, "crawl_agoda_search_with_browser", fake_crawl)

    result = orchestration.run_crawl_job_with_browser(None, job, args)

    assert [record["hotel_name"] for record in result.records] == [
        "Complete Hotel",
        "Missing Price",
    ]
    assert project_output_record(result.records[0])["crawl_status"] == "success"
    assert project_output_record(result.records[1])["crawl_status"] == "partial"
    assert project_output_record(result.records[1])["error_reason"] == "missing_price"
    assert [record["hotel_name"] for record in result.debug_records or []] == [
        "Complete Hotel",
        "Missing Price",
    ]


def test_estimated_detail_pressure_uses_actual_workers_and_detail_concurrency() -> None:
    assert estimated_detail_pressure(3, 5, True) == 15
    assert estimated_detail_pressure(3, 5, False) == 0


def test_run_crawl_jobs_uses_dynamic_queue_and_restores_order(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--destinations", "A,B,C"])
    args = parse_args(env={})
    jobs = build_crawl_jobs(args, ["A", "B", "C"], [("2026-06-01", "2026-06-02")])

    def fake_worker(job_queue, _args, _write_output):
        results = []
        while True:
            try:
                job = job_queue.get_nowait()
            except Empty:
                break
            try:
                results.insert(0, CrawlJobResult(job=job, records=[]))
            finally:
                job_queue.task_done()
        return results

    monkeypatch.setattr(orchestration, "run_crawl_job_worker", fake_worker)

    results = orchestration.run_crawl_jobs(jobs, args, worker_count=2, write_output=False)

    assert [result.job.destination for result in results] == ["A", "B", "C"]
