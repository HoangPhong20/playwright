"""One-time Unity Catalog setup for the Agoda ETL pipeline."""

from __future__ import annotations

from pyspark.sql import SparkSession

from . import config


def _create_table(spark: SparkSession, table: str, columns: str) -> None:
    spark.sql(f"CREATE TABLE IF NOT EXISTS {table} ({columns}) USING DELTA")


def _add_missing_ledger_columns(spark: SparkSession) -> None:
    columns = {
        row["col_name"].lower()
        for row in spark.sql(f"SHOW COLUMNS IN {config.LEDGER_TABLE}").collect()
    }
    if "target_table" not in columns:
        spark.sql(f"ALTER TABLE {config.LEDGER_TABLE} ADD COLUMNS (target_table STRING)")


def run_setup(spark: SparkSession) -> dict:
    """Create the schemas and managed Delta tables required by the daily Job."""
    for schema in (config.RAW_SCHEMA, config.SILVER_SCHEMA, config.GOLD_SCHEMA):
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    _create_table(
        spark,
        config.BRONZE_TABLE,
        """
        record_id STRING, record_hash STRING,
        hotel_name STRING, hotel_url STRING, price_value STRING,
        rating_text STRING, review_count_text STRING, star_rating_text STRING,
        crawled_at STRING, destination STRING, normalized_destination STRING,
        check_in STRING, check_out STRING, batch_id STRING,
        airflow_dag_id STRING, airflow_run_id STRING, airflow_try_number BIGINT,
        source_file_path STRING, manifest_path STRING, ingested_at TIMESTAMP
        """,
    )
    _create_table(
        spark,
        config.LEDGER_TABLE,
        """
        batch_id STRING, file_path STRING, manifest_path STRING, target_table STRING,
        status STRING, started_at TIMESTAMP, loaded_at TIMESTAMP, row_count BIGINT,
        error_message STRING
        """,
    )
    _add_missing_ledger_columns(spark)
    _create_table(
        spark,
        config.SILVER_TABLE,
        """
        record_id STRING, record_hash STRING, hotel_name STRING, hotel_url STRING,
        price_amount DECIMAL(18,0), rating DECIMAL(3,1), review_count BIGINT,
        star_rating DECIMAL(2,1), crawled_at TIMESTAMP, destination STRING,
        normalized_destination STRING, date DATE, batch_id STRING,
        airflow_dag_id STRING, airflow_run_id STRING, airflow_try_number BIGINT,
        source_file_path STRING, manifest_path STRING, bronze_ingested_at TIMESTAMP,
        transformed_at TIMESTAMP
        """,
    )
    _create_table(
        spark,
        config.HOTEL_DAILY_SUMMARY,
        """
        date DATE, destination STRING, hotel_url STRING, hotel_name STRING,
        min_price_amount DECIMAL(18,0), avg_price_amount DECIMAL(18,0),
        max_price_amount DECIMAL(18,0), rating DECIMAL(3,1), review_count BIGINT,
        star_rating DECIMAL(2,1), observations BIGINT, last_crawled_at TIMESTAMP
        """,
    )
    _create_table(
        spark,
        config.DESTINATION_DAILY_SUMMARY,
        """
        date DATE, destination STRING, hotel_count BIGINT,
        avg_price_amount DECIMAL(18,0), min_price_amount DECIMAL(18,0),
        max_price_amount DECIMAL(18,0), avg_rating DECIMAL(3,1), observations BIGINT
        """,
    )
    _create_table(
        spark,
        config.RATING_DISTRIBUTION,
        """
        date DATE, destination STRING, rating_bucket STRING, observations BIGINT,
        avg_price_amount DECIMAL(18,0)
        """,
    )
    _create_table(
        spark,
        config.PRICE_BY_STAR,
        """
        date DATE, destination STRING, star_rating DECIMAL(2,1), observations BIGINT,
        avg_price_amount DECIMAL(18,0), median_price_amount DECIMAL(18,0),
        avg_rating DECIMAL(3,1)
        """,
    )
    return {"status": "success", "tables_ready": len(config.DAILY_JOB_TABLES)}
