"""Raw Bronze parsing and contract-driven Silver quality validation."""

from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F

from . import config, schemas


def _non_blank(name: str) -> Column:
    return F.col(name).isNotNull() & (F.length(F.trim(F.col(name))) > 0)


def _format_failure(name: str, format_name: str) -> Column:
    """Return a null-or-reason expression for one YAML-declared format."""
    digits = F.regexp_replace(F.col(name), "[^0-9]", "")
    decimal_text = F.regexp_replace(F.col(name), ",", ".")
    if format_name == "uri":
        invalid = ~F.col(name).rlike(r"^https?://")
    elif format_name == "positive_price":
        invalid = (digits == "") | (digits.cast("decimal(18,0)") <= 0)
    elif format_name == "timestamp":
        invalid = F.to_timestamp(name).isNull()
    elif format_name == "date":
        invalid = F.to_date(name).isNull()
    elif format_name == "rating_0_10":
        value = decimal_text.cast("decimal(3,1)")
        invalid = value.isNull() | (value < 0) | (value > 10)
    elif format_name == "non_negative_integer":
        value = digits.cast("bigint")
        invalid = (digits == "") | value.isNull() | (value < 0)
    elif format_name == "star_rating_0_5":
        text = F.regexp_replace(F.regexp_extract(name, r"(\d+(?:[.,]\d+)?)", 1), ",", ".")
        value = text.cast("decimal(2,1)")
        invalid = (text == "") | value.isNull() | (value < 0) | (value > 5)
    else:  # Guarded by contract.load_contract; retained for direct unit-test safety.
        raise ValueError(f"Unsupported contract format: {format_name}")
    return F.when(_non_blank(name) & invalid, F.lit(f"invalid_{name}"))


def _semantic_failure_rules() -> list[Column]:
    """Build Silver rules from the versioned YAML contract, not a parallel list."""
    failures: list[Column] = []
    for name, definition in config.CONTRACT["fields"].items():
        if definition["required"]:
            failures.append(F.when(~_non_blank(name), F.lit(f"required_{name}")))
        format_name = definition.get("format")
        if format_name:
            failures.append(_format_failure(name, format_name))
    for rule in config.CONTRACT.get("cross_field_rules", []):
        if rule == "check_out_after_check_in":
            failures.append(
                F.when(
                    F.to_date("check_in").isNotNull()
                    & F.to_date("check_out").isNotNull()
                    & (F.to_date("check_out") <= F.to_date("check_in")),
                    F.lit("check_out_not_after_check_in"),
                )
            )
        else:  # Guarded by contract.load_contract.
            raise ValueError(f"Unsupported cross-field contract rule: {rule}")
    return failures


def _with_failure_rules(frame: DataFrame) -> DataFrame:
    failure_arrays = [
        F.when(rule.isNotNull(), F.array(rule)).otherwise(F.array())
        for rule in _semantic_failure_rules()
    ]
    return frame.withColumn("failed_rules", F.flatten(F.array(*failure_arrays)))


def _default_invalid_optional_metrics(frame: DataFrame) -> DataFrame:
    """Replace malformed optional metrics with neutral values before validation."""
    rating_text = F.regexp_replace(F.col("rating_text"), ",", ".")
    rating_value = rating_text.cast("decimal(3,1)")
    invalid_rating = _non_blank("rating_text") & (
        rating_value.isNull() | (rating_value < 0) | (rating_value > 10)
    )

    review_digits = F.regexp_replace(F.col("review_count_text"), "[^0-9]", "")
    review_value = review_digits.cast("bigint")
    invalid_review_count = _non_blank("review_count_text") & (
        (review_digits == "") | review_value.isNull() | (review_value < 0)
    )

    star_text = F.regexp_replace(
        F.regexp_extract("star_rating_text", r"(\d+(?:[.,]\d+)?)", 1), ",", "."
    )
    star_value = star_text.cast("decimal(2,1)")
    invalid_star_rating = _non_blank("star_rating_text") & (
        (star_text == "") | star_value.isNull() | (star_value < 0) | (star_value > 5)
    )

    return (
        frame
        .withColumn("rating_text", F.when(invalid_rating, F.lit("0")).otherwise(F.col("rating_text")))
        .withColumn(
            "review_count_text",
            F.when(invalid_review_count, F.lit("0")).otherwise(F.col("review_count_text")),
        )
        .withColumn(
            "star_rating_text",
            F.when(invalid_star_rating, F.lit("0 stars")).otherwise(F.col("star_rating_text")),
        )
    )


def read_raw_records(
    spark: SparkSession,
    file_path: str,
    manifest: dict,
    manifest_path: PurePosixPath,
) -> tuple[DataFrame, DataFrame, int, int]:
    """Read JSONL permissively for Bronze and preserve every original line.

    Unknown fields and scalar representation changes are accepted. Only a line
    that is not a JSON object is quarantined at this boundary.
    """
    lines = spark.read.text(file_path).withColumnRenamed("value", "raw_record_json")
    parsed = (
        lines
        .withColumn("record", F.from_json("raw_record_json", schemas.CRAWLER_OUTPUT_SCHEMA))
        .withColumn("is_json_object", F.col("record").isNotNull())
    )
    base = (
        parsed.select(
            "raw_record_json", "record.*",
            F.lit(manifest["batch_id"]).alias("batch_id"),
            F.lit(manifest["airflow_dag_id"]).alias("airflow_dag_id"),
            F.lit(manifest["airflow_run_id"]).alias("airflow_run_id"),
            F.lit(manifest["airflow_try_number"]).cast("long").alias("airflow_try_number"),
            F.lit(file_path).alias("source_file_path"),
            F.lit(str(manifest_path)).alias("manifest_path"),
            F.current_timestamp().alias("ingested_at"),
            "is_json_object",
        )
        .withColumn(
            "record_id",
            F.sha2(
                F.concat_ws(
                    "\u001f",
                    "batch_id",
                    "source_file_path",
                    "raw_record_json",
                ),
                256,
            ),
        )
    )
    valid = (
        base.where("is_json_object")
        .drop("is_json_object")
        .select(
            "record_id", *config.BUSINESS_OUTPUT_COLUMNS,
            *config.AIRFLOW_METADATA_COLUMNS, "source_file_path", "manifest_path",
            "ingested_at", "raw_record_json",
        )
        .dropDuplicates(["record_id"])
    )
    quarantined = (
        base.where("NOT is_json_object")
        .select(
            "record_id", "batch_id", "airflow_dag_id", "airflow_run_id", "airflow_try_number",
            "source_file_path", "manifest_path", "raw_record_json",
            F.array(F.lit("malformed_json")).alias("failed_rules"),
            F.lit("malformed_json").alias("failure_reason"),
            F.lit("bronze").alias("quarantine_layer"),
            F.current_timestamp().alias("quarantined_at"),
        )
        .dropDuplicates(["record_id"])
    )
    return valid, quarantined, base.count(), quarantined.count()


def validate_silver_records(bronze: DataFrame) -> tuple[DataFrame, DataFrame]:
    """Apply YAML business rules after the raw record is safely in Bronze."""
    staged = _with_failure_rules(_default_invalid_optional_metrics(bronze))
    invalid = staged.where(F.size("failed_rules") > 0)
    valid = staged.where(F.size("failed_rules") == 0).drop("failed_rules")
    quarantined = invalid.select(
        "record_id", "batch_id", "airflow_dag_id", "airflow_run_id", "airflow_try_number",
        "source_file_path", "manifest_path", "raw_record_json", "failed_rules",
        F.concat_ws(";", "failed_rules").alias("failure_reason"),
        F.lit("silver").alias("quarantine_layer"),
        F.current_timestamp().alias("quarantined_at"),
    ).dropDuplicates(["record_id"])
    return valid, quarantined


def upsert_quarantine(spark: SparkSession, quarantined: DataFrame) -> None:
    view_name = f"agoda_quarantine_stage_{uuid.uuid4().hex}"
    quarantined.createOrReplaceTempView(view_name)
    spark.sql(
        f"""
        MERGE INTO {config.QUARANTINE_TABLE} AS target
        USING {view_name} AS source
        ON target.record_id = source.record_id
        WHEN MATCHED THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
        """
    )


def exceeds_invalid_threshold(input_records: int, invalid_records: int) -> bool:
    return (
        invalid_records > config.MAX_INVALID_RECORDS
        or invalid_records / input_records > config.MAX_INVALID_RATIO
    )
