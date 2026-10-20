"""Local Spark behavior tests for Agoda Bronze, Silver, and Gold transforms."""

from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal
from pathlib import Path, PurePosixPath
import sys

import pytest


pytest.importorskip("pyspark", reason="local Spark behavior tests require PySpark")
pytestmark = pytest.mark.spark

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "databricks"))

from agoda_etl import data_quality, gold, silver  # noqa: E402


MANIFEST = {
    "batch_id": "agoda_daily_crawl__local_spark__2026-10-20",
    "airflow_dag_id": "agoda_daily_crawl",
    "airflow_run_id": "local_spark__2026-10-20",
    "airflow_try_number": 1,
}
MANIFEST_PATH = PurePosixPath(
    "/Volumes/agoda/raw/crawler/dag_id=local/batch_id=local/attempt=1/run_manifest.json"
)


def _bronze_row(record_id: str = "record-1", **overrides) -> dict:
    row = {
        "record_id": record_id,
        "hotel_name": "Hotel One",
        "hotel_url": "https://example.test/hotel-one",
        "price_value": "1250000",
        "rating_text": None,
        "review_count_text": None,
        "star_rating_text": None,
        "crawled_at": "2026-10-19 08:30:00",
        "destination": "Da Nang",
        "normalized_destination": "da nang",
        "check_in": "2026-10-22",
        "check_out": "2026-10-23",
        "batch_id": MANIFEST["batch_id"],
        "airflow_dag_id": MANIFEST["airflow_dag_id"],
        "airflow_run_id": MANIFEST["airflow_run_id"],
        "airflow_try_number": 1,
        "source_file_path": "/tmp/hotels.jsonl",
        "manifest_path": str(MANIFEST_PATH),
        "ingested_at": datetime(2026, 10, 19, 8, 31),
        "raw_record_json": '{"hotel_name":"Hotel One"}',
    }
    row.update(overrides)
    return row


def test_price_validation_requires_positive_digits_and_decimal18_capacity(spark_session):
    spark_session.conf.set("spark.sql.ansi.enabled", "false")
    prices = [
        ("valid", "1250000"),
        ("zero", "0"),
        ("negative", "-1250000"),
        ("decimal", "1250000.00"),
        ("separator", "1,250,000"),
        ("currency", "VND 1250000"),
        ("overflow", "1000000000000000000"),
    ]
    bronze = spark_session.createDataFrame(
        [
            _bronze_row(
                record_id=record_id,
                price_value=price,
                rating_text="8.0",
                review_count_text="100",
                star_rating_text="4 stars",
            )
            for record_id, price in prices
        ]
    )

    valid, quarantined = data_quality.validate_silver_records(bronze)

    assert {row.record_id for row in valid.select("record_id").collect()} == {"valid"}
    failures = {row.record_id: row.failed_rules for row in quarantined.collect()}
    assert set(failures) == {record_id for record_id, _ in prices[1:]}
    assert all("invalid_price_value" in rules for rules in failures.values())


@pytest.mark.parametrize("ansi_enabled", [True, False])
def test_timestamp_date_and_optional_metric_validation_is_ansi_safe(
    spark_session, ansi_enabled
):
    spark_session.conf.set("spark.sql.ansi.enabled", str(ansi_enabled).lower())
    bronze = spark_session.createDataFrame(
        [
            _bronze_row(record_id="bad-time", crawled_at="not-a-timestamp"),
            _bronze_row(record_id="bad-date", check_in="2026-99-22"),
            _bronze_row(
                record_id="bad-optional",
                rating_text="not-a-number",
                review_count_text="-12",
                star_rating_text="-2 stars",
            ),
            _bronze_row(record_id="missing-optional"),
        ]
    )

    valid, quarantined = data_quality.validate_silver_records(bronze)

    failures = {row.record_id: row.failed_rules for row in quarantined.collect()}
    assert "invalid_crawled_at" in failures["bad-time"]
    assert "invalid_check_in" in failures["bad-date"]
    values = {row.record_id: row for row in valid.collect()}
    assert set(values) == {"bad-optional", "missing-optional"}
    assert (
        values["bad-optional"].rating_text,
        values["bad-optional"].review_count_text,
        values["bad-optional"].star_rating_text,
    ) == ("0", "0", "0 stars")
    assert (
        values["missing-optional"].rating_text,
        values["missing-optional"].review_count_text,
        values["missing-optional"].star_rating_text,
    ) == (None, None, None)


@pytest.mark.parametrize("ansi_enabled", [True, False])
def test_bronze_jsonl_parsing_preserves_objects_and_deduplicates(
    tmp_path, spark_session, ansi_enabled
):
    spark_session.conf.set("spark.sql.ansi.enabled", str(ansi_enabled).lower())
    object_line = (
        ' { "hotel_name" : 7, "hotel_url" : true, "price_value" : 120000, '
        '"source_only_field" : "ignored" } '
    )
    second_object = '{"hotel_name":"Hotel Two","unmapped":false}'
    empty_object = "{}"
    unknown_only_object = '{"source_only_field":"still an object"}'
    lines = [
        object_line,
        object_line,
        second_object,
        empty_object,
        unknown_only_object,
        '{"hotel_name":',
        '{"hotel_name":"Hotel Three"} trailing',
        "{}{}",
        "{}]{} ",
        '{"hotel_name":"Hotel Four"}]{}',
        '{"hotel_name":"Hotel Five"}}',
        "{} }",
        '{},"extra":1',
        '{"hotel_name":"Hotel Six"},"extra":{}',
        "[]",
        "42",
        '"a scalar"',
        "null",
    ]
    source_file = tmp_path / "hotels.jsonl"
    source_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    file_path = source_file.as_posix()

    valid, quarantined, physical_line_count, invalid_count = data_quality.read_raw_records(
        spark_session, file_path, MANIFEST, MANIFEST_PATH
    )

    assert physical_line_count == len(lines)
    assert invalid_count == 13
    valid_rows = valid.collect()
    assert len(valid_rows) == 4
    first = next(row for row in valid_rows if row.raw_record_json == object_line)
    assert (first.hotel_name, first.hotel_url, first.price_value) == ("7", "true", "120000")
    assert first.raw_record_json == object_line
    assert set(valid.columns).isdisjoint({"source_only_field", "unmapped"})
    assert {row.raw_record_json for row in valid_rows} == {
        object_line, second_object, empty_object, unknown_only_object
    }

    repeated_valid, _, _, _ = data_quality.read_raw_records(
        spark_session, file_path, MANIFEST, MANIFEST_PATH
    )
    ids = {row.record_id for row in valid_rows}
    assert {row.record_id for row in repeated_valid.collect()} == ids
    assert {row.raw_record_json for row in quarantined.collect()} == set(lines[5:])


def test_silver_conversion_returns_typed_values_and_check_in_date(spark_session):
    spark_session.conf.set("spark.sql.ansi.enabled", "true")
    bronze = spark_session.createDataFrame(
        [
            _bronze_row(
                price_value="1250000",
                rating_text="8,7",
                review_count_text="145 reviews",
                star_rating_text="4.5 stars",
            )
        ]
    )
    valid, quarantined = data_quality.validate_silver_records(bronze)
    assert quarantined.count() == 0

    converted = silver.transform_bronze_to_silver(valid)
    row = converted.first()

    assert converted.schema["price_amount"].dataType.simpleString() == "decimal(18,0)"
    assert converted.schema["rating"].dataType.simpleString() == "decimal(3,1)"
    assert converted.schema["review_count"].dataType.simpleString() == "bigint"
    assert converted.schema["star_rating"].dataType.simpleString() == "decimal(2,1)"
    assert converted.schema["check_in_date"].dataType.simpleString() == "date"
    assert row.price_amount == Decimal("1250000")
    assert row.rating == Decimal("8.7")
    assert row.review_count == 145
    assert row.star_rating == Decimal("4.5")
    assert row.check_in_date == date(2026, 10, 22)


def test_gold_summaries_aggregate_complete_history_rows(spark_session):
    history = spark_session.createDataFrame(
        [
            (
                "record-1", date(2026, 10, 22), "Da Nang", "https://example.test/a", "Hotel A",
                Decimal("100"), Decimal("9.0"), 100, Decimal("4.0"), datetime(2026, 10, 19, 8),
            ),
            (
                "record-2", date(2026, 10, 22), "Da Nang", "https://example.test/a", "Hotel A",
                Decimal("200"), Decimal("9.2"), 120, Decimal("4.5"), datetime(2026, 10, 20, 8),
            ),
            (
                "record-3", date(2026, 10, 22), "Da Nang", "https://example.test/b", "Hotel B",
                Decimal("300"), Decimal("7.2"), 300, Decimal("3.0"), datetime(2026, 10, 20, 9),
            ),
        ],
        schema=(
            "record_id string, check_in_date date, destination string, hotel_url string, "
            "hotel_name string, price_amount decimal(18,0), rating decimal(3,1), "
            "review_count long, star_rating decimal(2,1), crawled_at timestamp"
        ),
    )

    hotel = gold.hotel_daily_summary(history).where("hotel_url = 'https://example.test/a'").first()
    destination = gold.destination_daily_summary(history).first()
    rating_buckets = {
        row.rating_bucket: (row.observations, row.avg_price_amount)
        for row in gold.rating_distribution(history).collect()
    }
    star_groups = {
        row.star_rating: (row.observations, row.median_price_amount)
        for row in gold.price_by_star(history).collect()
    }

    assert (hotel.min_price_amount, hotel.avg_price_amount, hotel.max_price_amount) == (
        Decimal("100"), Decimal("150"), Decimal("200")
    )
    assert (hotel.observations, hotel.rating, hotel.review_count, hotel.star_rating) == (
        2, Decimal("9.2"), 120, Decimal("4.5")
    )
    assert (destination.hotel_count, destination.observations) == (2, 3)
    assert (
        destination.avg_price_amount,
        destination.min_price_amount,
        destination.max_price_amount,
        destination.avg_rating,
    ) == (Decimal("200"), Decimal("100"), Decimal("300"), Decimal("8.5"))
    assert rating_buckets == {
        "Excellent (9.0+)": (2, Decimal("150")),
        "Good (7.0-7.9)": (1, Decimal("300")),
    }
    assert star_groups == {
        Decimal("3.0"): (1, Decimal("300")),
        Decimal("4.0"): (1, Decimal("100")),
        Decimal("4.5"): (1, Decimal("200")),
    }
