"""Shared Unity Catalog configuration for the Agoda ETL pipeline."""

from .contract import CONTRACT, CONTRACT_FIELDS

CATALOG = "agoda"
RAW_SCHEMA = f"{CATALOG}.raw"
SILVER_SCHEMA = f"{CATALOG}.silver"
GOLD_SCHEMA = f"{CATALOG}.gold"

VOLUME_ROOT = "/Volumes/agoda/raw/crawler"

BRONZE_TABLE = f"{RAW_SCHEMA}.agoda_hotels_bronze"
LEDGER_TABLE = f"{RAW_SCHEMA}.agoda_ingestion_ledger"
QUARANTINE_TABLE = f"{RAW_SCHEMA}.agoda_hotel_quarantine"
AUDIT_TABLE = f"{RAW_SCHEMA}.agoda_pipeline_audit"
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
    QUARANTINE_TABLE,
    AUDIT_TABLE,
    SILVER_TABLE,
    *GOLD_TABLES,
)

BUSINESS_OUTPUT_COLUMNS = CONTRACT_FIELDS
CONTRACT_VERSION = CONTRACT["version"]

MAX_INVALID_RECORDS = 200
MAX_INVALID_RATIO = 0.10

AIRFLOW_METADATA_COLUMNS = (
    "batch_id",
    "airflow_dag_id",
    "airflow_run_id",
    "airflow_try_number",
)

OUTPUT_COLUMNS = (*BUSINESS_OUTPUT_COLUMNS, *AIRFLOW_METADATA_COLUMNS)
