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


def _add_approved_bronze_columns(spark: SparkSession) -> None:
    """Apply nullable contract additions to Bronze without accepting unknown input."""
    columns = {
        row["col_name"].lower()
        for row in spark.sql(f"SHOW COLUMNS IN {config.BRONZE_TABLE}").collect()
    }
    for column in config.BUSINESS_OUTPUT_COLUMNS:
        if column.lower() not in columns:
            if config.CONTRACT["fields"][column]["required"]:
                raise ValueError(
                    f"Adding required contract field {column!r} needs an explicit table migration"
                )
            spark.sql(f"ALTER TABLE {config.BRONZE_TABLE} ADD COLUMNS ({column} STRING)")


def _add_missing_columns(spark: SparkSession, table: str, definitions: dict[str, str]) -> None:
    columns = {row["col_name"].lower() for row in spark.sql(f"SHOW COLUMNS IN {table}").collect()}
    for name, data_type in definitions.items():
        if name.lower() not in columns:
            spark.sql(f"ALTER TABLE {table} ADD COLUMNS ({name} {data_type})")


def _rename_legacy_date_column(spark: SparkSession, table: str) -> None:
    """Migrate the ambiguous legacy business-date column once, if present."""
    columns = {
        row["col_name"].lower()
        for row in spark.sql(f"SHOW COLUMNS IN {table}").collect()
    }
    if "date" in columns and "check_in_date" not in columns:
        # Delta requires name-based column mapping before a physical column
        # rename.  Apply it only to legacy tables that actually need this
        # migration, so newly created tables keep their default protocol.
        spark.sql(
            f"ALTER TABLE {table} SET TBLPROPERTIES "
            "('delta.columnMapping.mode' = 'name')"
        )
        spark.sql(f"ALTER TABLE {table} RENAME COLUMN date TO check_in_date")


def run_setup(spark: SparkSession) -> dict:
    """Create the schemas and managed Delta tables required by the daily Job."""
    for schema in (config.RAW_SCHEMA, config.SILVER_SCHEMA, config.GOLD_SCHEMA):
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    _create_table(
        spark,
        config.BRONZE_TABLE,
        """
        record_id STRING,
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
    _add_approved_bronze_columns(spark)
    _add_missing_columns(spark, config.BRONZE_TABLE, {"raw_record_json": "STRING"})
    _create_table(
        spark,
        config.QUARANTINE_TABLE,
        """
        record_id STRING, batch_id STRING, airflow_dag_id STRING, airflow_run_id STRING,
        airflow_try_number BIGINT, source_file_path STRING, manifest_path STRING,
        raw_record_json STRING, failed_rules ARRAY<STRING>, failure_reason STRING,
        quarantine_layer STRING,
        quarantined_at TIMESTAMP
        """,
    )
    _add_missing_columns(spark, config.QUARANTINE_TABLE, {"quarantine_layer": "STRING"})
    _create_table(
        spark,
        config.AUDIT_TABLE,
        """
        batch_id STRING, airflow_dag_id STRING, airflow_run_id STRING,
        airflow_try_number BIGINT, layer STRING, contract_version STRING, status STRING,
        input_records BIGINT, output_records BIGINT, quarantined_records BIGINT,
        error_message STRING, completed_at TIMESTAMP
        """,
    )
    _create_table(
        spark,
        config.SILVER_TABLE,
        """
        record_id STRING, hotel_name STRING, hotel_url STRING,
        price_amount DECIMAL(18,0), rating DECIMAL(3,1), review_count BIGINT,
        star_rating DECIMAL(2,1), crawled_at TIMESTAMP, destination STRING,
        normalized_destination STRING, check_in_date DATE, batch_id STRING,
        airflow_dag_id STRING, airflow_run_id STRING, airflow_try_number BIGINT,
        source_file_path STRING, manifest_path STRING, bronze_ingested_at TIMESTAMP,
        transformed_at TIMESTAMP
        """,
    )
    _create_table(
        spark,
        config.HOTEL_DAILY_SUMMARY,
        """
        check_in_date DATE, destination STRING, hotel_url STRING, hotel_name STRING,
        min_price_amount DECIMAL(18,0), avg_price_amount DECIMAL(18,0),
        max_price_amount DECIMAL(18,0), rating DECIMAL(3,1), review_count BIGINT,
        star_rating DECIMAL(2,1), observations BIGINT, last_crawled_at TIMESTAMP
        """,
    )
    _create_table(
        spark,
        config.DESTINATION_DAILY_SUMMARY,
        """
        check_in_date DATE, destination STRING, hotel_count BIGINT,
        avg_price_amount DECIMAL(18,0), min_price_amount DECIMAL(18,0),
        max_price_amount DECIMAL(18,0), avg_rating DECIMAL(3,1), observations BIGINT
        """,
    )
    _create_table(
        spark,
        config.RATING_DISTRIBUTION,
        """
        check_in_date DATE, destination STRING, rating_bucket STRING, observations BIGINT,
        avg_price_amount DECIMAL(18,0)
        """,
    )
    _create_table(
        spark,
        config.PRICE_BY_STAR,
        """
        check_in_date DATE, destination STRING, star_rating DECIMAL(2,1), observations BIGINT,
        avg_price_amount DECIMAL(18,0), median_price_amount DECIMAL(18,0),
        avg_rating DECIMAL(3,1)
        """,
    )
    for table in (
        config.SILVER_TABLE,
        config.HOTEL_DAILY_SUMMARY,
        config.DESTINATION_DAILY_SUMMARY,
        config.RATING_DISTRIBUTION,
        config.PRICE_BY_STAR,
    ):
        _rename_legacy_date_column(spark, table)

    return {"status": "success", "tables_ready": len(config.DAILY_JOB_TABLES)}
