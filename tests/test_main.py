import sys

import pytest

from agoda_crawler.config import load_config_env, load_dotenv
from agoda_crawler.jobs import (
    CrawlJobResult,
    build_crawl_jobs,
    iter_stays,
    jobs_for_stay,
    ordered_results,
    parse_date,
    parse_destinations,
)
from agoda_crawler.orchestration import parse_detail_fields
from main import parse_args


def test_parse_args_defaults_to_enrich_all_details(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--date", "2026-06-01"])

    args = parse_args(env={})

    assert args.enrich_details is True
    assert args.max_detail_pages == 0
    assert args.output_dir == "data"
    assert args.max_pages == 5
    assert args.destinations == "Vung Tau,Da Nang,Nha Trang,Ho Chi Minh"
    assert args.date == "2026-06-01"
    assert not hasattr(args, "nights")
    assert args.workers == 3
    assert args.detail_concurrency == 2
    assert args.total_detail_concurrency == 3
    assert args.enrich_missing_only is True
    assert args.detail_timeout == 30000
    assert args.field_retry_timeout == 1500
    assert args.field_retry_count == 2
    assert args.detail_fields == "price_value,rating_text,review_count_text"
    assert args.max_scroll_rounds == 80
    assert args.stable_rounds == 3
    assert args.scroll_wait_ms == 1000
    assert args.print_records is False
    assert args.airflow_dag_id is None
    assert args.airflow_run_id is None
    assert args.airflow_try_number == 1


def test_parse_detail_fields_accepts_known_fields() -> None:
    assert parse_detail_fields("price_value,star_rating_text") == ("price_value", "star_rating_text")


def test_parse_detail_fields_rejects_unknown_fields() -> None:
    try:
        parse_detail_fields("price_value,bad_field")
    except ValueError as exc:
        assert "bad_field" in str(exc)
    else:
        raise AssertionError("parse_detail_fields should reject unknown fields")


def test_parse_detail_fields_rejects_removed_fields() -> None:
    for field in ("location_text", "image_url"):
        try:
            parse_detail_fields(field)
        except ValueError as exc:
            assert field in str(exc)
        else:
            raise AssertionError(f"{field} should not be supported")


def test_parse_args_can_disable_detail_enrichment(monkeypatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["main.py", "--date", "2026-06-01", "--no-enrich-details"]
    )

    args = parse_args(env={})

    assert args.enrich_details is False


def test_parse_args_accepts_output_dir(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--date", "2026-06-01", "--output-dir", "data/raw/prod"],
    )

    args = parse_args(env={})

    assert args.output_dir == "data/raw/prod"


def test_parse_args_uses_env_defaults(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--date", "2026-06-01"])

    args = parse_args(
        env={
            "AGODA_DESTINATION": "Da Nang",
            "AGODA_MAX_PAGES": "5",
            "AGODA_HEADLESS": "true",
            "AGODA_OUTPUT_DIR": "data/raw",
            "AGODA_ENRICH_DETAILS": "false",
            "AGODA_WORKERS": "3",
            "AGODA_DETAIL_CONCURRENCY": "3",
            "AGODA_TOTAL_DETAIL_CONCURRENCY": "4",
            "AGODA_DETAIL_TIMEOUT": "20000",
            "AGODA_FIELD_RETRY_TIMEOUT": "1200",
            "AGODA_FIELD_RETRY_COUNT": "1",
            "AGODA_DETAIL_FIELDS": "price_value,star_rating_text",
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
    assert args.total_detail_concurrency == 4
    assert args.detail_timeout == 20000
    assert args.field_retry_timeout == 1200
    assert args.field_retry_count == 1
    assert args.detail_fields == "price_value,star_rating_text"
    assert args.enrich_missing_only is False
    assert args.max_scroll_rounds == 40
    assert args.stable_rounds == 5
    assert args.scroll_wait_ms == 1500


def test_cli_args_override_env_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--date",
            "2026-06-01",
            "--destination",
            "Hue",
            "--max-pages",
            "1",
            "--no-headless",
        ],
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


def test_load_config_env_rejects_unknown_agoda_key(tmp_path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("AGODA_WORKERSS=2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="AGODA_WORKERSS"):
        load_config_env(str(env_path))


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


def test_iter_stays_builds_one_overnight_stay(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--date", "2026-06-01"],
    )

    args = parse_args(env={})

    assert iter_stays(args) == [("2026-06-01", "2026-06-02")]


def test_parse_args_rejects_removed_nights_option(monkeypatch) -> None:
    monkeypatch.setattr(
        sys, "argv", ["main.py", "--date", "2026-06-01", "--nights", "2"]
    )

    try:
        parse_args(env={})
    except SystemExit:
        return

    raise AssertionError("--nights should not be accepted")


@pytest.mark.parametrize(
    "legacy_option", ["--date-start", "--date-end", "--date-s"]
)
def test_parse_args_rejects_removed_date_range_options(
    monkeypatch, legacy_option: str
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "--date", "2026-06-01", legacy_option, "2026-06-01"],
    )

    with pytest.raises(SystemExit):
        parse_args(env={})


def test_build_crawl_jobs_creates_destination_matrix_for_one_date(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--destinations",
            "Vung Tau,Da Nang,Nha Trang",
            "--date",
            "2026-06-01",
        ],
    )

    args = parse_args(env={})
    destinations = parse_destinations(args.destinations, args.destination)
    stays = iter_stays(args)
    jobs = build_crawl_jobs(args, destinations, stays)

    assert len(jobs) == 3
    assert jobs[0].destination == "Vung Tau"
    assert jobs[0].check_in == "2026-06-01"
    assert jobs[0].check_out == "2026-06-02"
    assert jobs[0].output_path.name == "agoda_hotels_2026-06-01.jsonl"
    assert jobs[-1].destination == "Nha Trang"
    assert jobs[-1].check_in == "2026-06-01"


def test_build_crawl_jobs_uses_the_given_run_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "argv", ["main.py", "--date", "2026-06-01"])
    args = parse_args(env={})

    jobs = build_crawl_jobs(
        args,
        ["Vung Tau"],
        [("2026-06-01", "2026-06-02")],
        output_dir=tmp_path / "run_abc",
    )

    assert jobs[0].output_path == tmp_path / "run_abc" / "agoda_hotels_2026-06-01.jsonl"


def test_jobs_for_stay_keeps_one_day_batch(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--destinations",
            "Vung Tau,Da Nang",
            "--date",
            "2026-06-01",
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
        ["main.py", "--date", "2026-06-01", "--destinations", "Vung Tau,Da Nang"],
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
