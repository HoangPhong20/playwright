"""Shared Unity Catalog configuration for the Agoda ETL pipeline."""

CATALOG = "agoda"
RAW_SCHEMA = f"{CATALOG}.raw"
SILVER_SCHEMA = f"{CATALOG}.silver"
GOLD_SCHEMA = f"{CATALOG}.gold"

VOLUME_ROOT = "/Volumes/agoda/raw/crawler"

BRONZE_TABLE = f"{RAW_SCHEMA}.agoda_hotels_bronze"
LEDGER_TABLE = f"{RAW_SCHEMA}.agoda_ingestion_ledger"
SILVER_TABLE = f"{SILVER_SCHEMA}.agoda_hotels_history"

HOTEL_DAILY_SUMMARY = f"{GOLD_SCHEMA}.agoda_hotel_daily_summary"
DESTINATION_DAILY_SUMMARY = f"{GOLD_SCHEMA}.agoda_destination_daily_summary"
RATING_DISTRIBUTION = f"{GOLD_SCHEMA}.agoda_rating_distribution"
PRICE_BY_STAR = f"{GOLD_SCHEMA}.agoda_price_by_star"

GOLD_TABLES = (
    HOTEL_DAILY_SUMMARY,
    DESTINATION_DAILY_SUMMARY,
    RATING_DISTRIBUTION,
    PRICE_BY_STAR,
)

DAILY_JOB_TABLES = (
    BRONZE_TABLE,
    LEDGER_TABLE,
    SILVER_TABLE,
    *GOLD_TABLES,
)

BUSINESS_OUTPUT_COLUMNS = (
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
)

AIRFLOW_METADATA_COLUMNS = (
    "batch_id",
    "airflow_dag_id",
    "airflow_run_id",
    "airflow_try_number",
)

OUTPUT_COLUMNS = (*BUSINESS_OUTPUT_COLUMNS, *AIRFLOW_METADATA_COLUMNS)
