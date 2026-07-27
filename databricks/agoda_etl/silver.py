"""Idempotent Bronze-to-Silver transformation for Agoda crawl history."""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType

from . import config, runtime


def transform_bronze_to_silver(bronze_df: DataFrame) -> DataFrame:
    """Type crawler fields and expose one business date derived from check_in."""
    return (
        bronze_df
        .withColumn("date", F.to_date("check_in"))
        .withColumn("price_amount", F.when(F.regexp_replace("price_value", "[^0-9]", "") != "", F.regexp_replace("price_value", "[^0-9]", "")).cast(DecimalType(18, 0)))
        .withColumn("rating", F.when(F.regexp_replace("rating_text", ",", ".") != "", F.regexp_replace("rating_text", ",", ".")).cast(DecimalType(3, 1)))
        .withColumn("review_count", F.when(F.regexp_replace("review_count_text", "[^0-9]", "") != "", F.regexp_replace("review_count_text", "[^0-9]", "")).cast("bigint"))
        .withColumn(
            "star_rating",
            F.when(
                F.regexp_replace(
                    F.regexp_extract("star_rating_text", r"(\d+(?:[.,]\d+)?)", 1), ",", "."
                ) != "",
                F.regexp_replace(
                    F.regexp_extract("star_rating_text", r"(\d+(?:[.,]\d+)?)", 1), ",", "."
                )
            ).cast(DecimalType(2, 1)),
        )
        .withColumn("crawled_at", F.to_timestamp("crawled_at"))
        .withColumn("bronze_ingested_at", F.col("ingested_at"))
        .withColumn("transformed_at", F.current_timestamp())
        .select(
            "record_id", "record_hash", "hotel_name", "hotel_url", "price_amount", "rating",
            "review_count", "star_rating", "crawled_at", "destination", "normalized_destination",
            "date", "batch_id", "airflow_dag_id", "airflow_run_id", "airflow_try_number",
            "source_file_path", "manifest_path", "bronze_ingested_at", "transformed_at",
        )
    )


def run_silver_transformation(spark: SparkSession, manifest_path: str) -> dict:
    """Transform exactly one manifest batch without overwriting Silver history."""
    manifest, _, source_files = runtime.read_completed_manifest(spark, manifest_path)
    runtime.require_tables(spark, config.BRONZE_TABLE, config.SILVER_TABLE)
    bronze_batch = (
        spark.table(config.BRONZE_TABLE)
        .where(F.col("batch_id") == manifest["batch_id"])
        .where(F.col("source_file_path").isin(source_files))
    )
    if bronze_batch.limit(1).count() == 0:
        raise ValueError("No Bronze records found for this manifest; run Bronze ingestion first")

    stage = transform_bronze_to_silver(bronze_batch)
    record_count = stage.count()
    stage.createOrReplaceTempView("agoda_silver_stage")
    spark.sql(
        f"""
        MERGE INTO {config.SILVER_TABLE} AS target
        USING agoda_silver_stage AS source
        ON target.record_id = source.record_id
        WHEN NOT MATCHED THEN INSERT *
        """
    )
    return {
        "status": "success", "batch_id": manifest["batch_id"],
        "records_transformed": record_count, "files_processed": len(source_files),
    }
