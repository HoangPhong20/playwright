"""Schema and record-quality validation at the Bronze ingress boundary."""

from __future__ import annotations

from pathlib import PurePosixPath

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from . import config, schemas


class SchemaContractError(ValueError):
    """Raised when a source JSONL schema differs from the approved contract."""


def validate_source_schema(spark: SparkSession, file_path: str) -> None:
    """Reject missing, unknown, or non-string source fields before ingestion."""
    actual = {field.name: field.dataType.simpleString() for field in spark.read.json(file_path).schema.fields}
    expected = set(config.BUSINESS_OUTPUT_COLUMNS)
    missing = sorted(expected - set(actual))
    unknown = sorted(set(actual) - expected)
    incompatible = sorted(
        name for name, data_type in actual.items()
        if name in expected and data_type not in {"string", "void"}
    )
    if missing or unknown or incompatible:
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        if incompatible:
            details.append(f"non_string={','.join(incompatible)}")
        raise SchemaContractError("source schema does not match agoda_hotel contract: " + "; ".join(details))


def read_and_validate(
    spark: SparkSession,
    file_path: str,
    manifest: dict,
    manifest_path: PurePosixPath,
) -> tuple[DataFrame, DataFrame, int, int]:
    """Return valid Bronze rows, quarantine rows, total count, and invalid count."""
    validate_source_schema(spark, file_path)
    source = spark.read.schema(schemas.CRAWLER_OUTPUT_SCHEMA).json(file_path)
    payload = [F.coalesce(F.col(column).cast("string"), F.lit("")) for column in config.BUSINESS_OUTPUT_COLUMNS]
    staged = (
        source.select(
            *[F.col(column) for column in config.BUSINESS_OUTPUT_COLUMNS],
            F.lit(manifest["batch_id"]).alias("batch_id"),
            F.lit(manifest["airflow_dag_id"]).alias("airflow_dag_id"),
            F.lit(manifest["airflow_run_id"]).alias("airflow_run_id"),
            F.lit(manifest["airflow_try_number"]).cast("long").alias("airflow_try_number"),
            F.lit(file_path).alias("source_file_path"),
            F.lit(str(manifest_path)).alias("manifest_path"),
            F.sha2(F.concat_ws("\u001f", *payload), 256).alias("record_hash"),
            F.current_timestamp().alias("ingested_at"),
        )
        .withColumn(
            "record_id",
            F.sha2(F.concat_ws("\u001f", "batch_id", "source_file_path", "record_hash"), 256),
        )
    )
    non_blank = lambda name: F.col(name).isNotNull() & (F.length(F.trim(F.col(name))) > 0)
    digits = lambda name: F.regexp_replace(F.col(name), "[^0-9]", "")
    decimal_text = lambda name: F.regexp_replace(F.col(name), ",", ".")
    star_text = F.regexp_replace(F.regexp_extract("star_rating_text", r"(\d+(?:[.,]\d+)?)", 1), ",", ".")
    failures = [
        F.when(~non_blank("hotel_name"), F.lit("required_hotel_name")),
        F.when(~non_blank("hotel_url"), F.lit("required_hotel_url")),
        F.when(non_blank("hotel_url") & ~F.col("hotel_url").rlike(r"^https?://"), F.lit("invalid_hotel_url")),
        F.when(~non_blank("price_value"), F.lit("required_price_value")),
        F.when(non_blank("price_value") & ((digits("price_value") == "") | (digits("price_value").cast("decimal(18,0)") <= 0)), F.lit("invalid_price_value")),
        F.when(~non_blank("crawled_at") | F.to_timestamp("crawled_at").isNull(), F.lit("invalid_crawled_at")),
        F.when(~non_blank("destination"), F.lit("required_destination")),
        F.when(~non_blank("normalized_destination"), F.lit("required_normalized_destination")),
        F.when(~non_blank("check_in") | F.to_date("check_in").isNull(), F.lit("invalid_check_in")),
        F.when(~non_blank("check_out") | F.to_date("check_out").isNull(), F.lit("invalid_check_out")),
        F.when((F.to_date("check_in").isNotNull()) & (F.to_date("check_out").isNotNull()) & (F.to_date("check_out") <= F.to_date("check_in")), F.lit("check_out_not_after_check_in")),
        F.when(non_blank("rating_text") & ((decimal_text("rating_text").cast("decimal(3,1)").isNull()) | (decimal_text("rating_text").cast("decimal(3,1)") < 0) | (decimal_text("rating_text").cast("decimal(3,1)") > 10)), F.lit("invalid_rating")),
        F.when(non_blank("review_count_text") & ((digits("review_count_text") == "") | (digits("review_count_text").cast("bigint") < 0)), F.lit("invalid_review_count")),
        F.when(non_blank("star_rating_text") & ((star_text == "") | (star_text.cast("decimal(2,1)") < 0) | (star_text.cast("decimal(2,1)") > 5)), F.lit("invalid_star_rating")),
    ]
    failure_arrays = [
        F.when(rule.isNotNull(), F.array(rule)).otherwise(F.array())
        for rule in failures
    ]
    staged = staged.withColumn("failed_rules", F.flatten(F.array(*failure_arrays)))
    duplicate_count = F.count("*").over(Window.partitionBy("record_id"))
    staged = staged.withColumn(
        "failed_rules",
        F.when(duplicate_count > 1, F.array_union("failed_rules", F.array(F.lit("duplicate_record_id"))))
        .otherwise(F.col("failed_rules")),
    ).withColumn("raw_record_json", F.to_json(F.struct(*[F.col(column) for column in config.BUSINESS_OUTPUT_COLUMNS])))
    invalid = staged.where(F.size("failed_rules") > 0)
    valid = staged.where(F.size("failed_rules") == 0).drop("failed_rules", "raw_record_json")
    quarantined = invalid.select(
        "record_id", "batch_id", "airflow_dag_id", "airflow_run_id", "airflow_try_number",
        "source_file_path", "manifest_path", "raw_record_json", "failed_rules",
        F.concat_ws(";", "failed_rules").alias("failure_reason"),
        F.current_timestamp().alias("quarantined_at"),
    ).dropDuplicates(["record_id"])
    return valid, quarantined, staged.count(), invalid.count()
