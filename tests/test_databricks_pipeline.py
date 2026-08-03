import importlib.util
from pathlib import Path
import sys

import pytest


MODULE_PATH = Path(__file__).parents[1] / "databricks" / "agoda_etl" / "utils.py"
SPEC = importlib.util.spec_from_file_location("agoda_etl_utils", MODULE_PATH)
utils = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(utils)

PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "databricks"))
from agoda_etl import config


def complete_manifest() -> dict:
    return {
        "status": "complete",
        "batch_id": "agoda_daily_crawl__manual__2026-07-26T08:17:03+00:00",
        "airflow_dag_id": "agoda_daily_crawl",
        "airflow_run_id": "manual__2026-07-26T08:17:03+00:00",
        "airflow_try_number": 1,
        "stays": [{"output_file": "agoda_hotels_2026-08-16.jsonl", "publishable_records": 3}],
    }


def test_manifest_output_files_uses_only_declared_filenames() -> None:
    manifest_path = "/Volumes/agoda/raw/crawler/dag_id=agoda_daily_crawl/batch_id=manual/attempt=1/run_manifest.json"
    assert utils.manifest_output_files(complete_manifest(), manifest_path) == [
        "/Volumes/agoda/raw/crawler/dag_id=agoda_daily_crawl/batch_id=manual/attempt=1/agoda_hotels_2026-08-16.jsonl"
    ]


def test_manifest_validation_rejects_unsafe_or_incomplete_inputs() -> None:
    with pytest.raises(ValueError, match="under"):
        utils.validate_manifest_path("/Volumes/other/raw/crawler/run_manifest.json", "/Volumes/agoda/raw/crawler")
    manifest = complete_manifest()
    manifest["stays"][0]["output_file"] = "../another.jsonl"
    with pytest.raises(ValueError, match="filename"):
        utils.manifest_output_files(manifest, "/Volumes/agoda/raw/crawler/dag_id=agoda/attempt=1/run_manifest.json")


def test_manifest_validation_rejects_non_integer_publishable_record_count() -> None:
    manifest = complete_manifest()
    manifest["stays"][0]["publishable_records"] = "3"
    with pytest.raises(ValueError, match="publishable"):
        utils.manifest_output_files(manifest, "/Volumes/agoda/raw/crawler/dag_id=agoda/attempt=1/run_manifest.json")


def test_bronze_input_schema_contract_excludes_airflow_metadata() -> None:
    metadata = {"batch_id", "airflow_dag_id", "airflow_run_id", "airflow_try_number"}
    assert metadata.isdisjoint(config.BUSINESS_OUTPUT_COLUMNS)
    assert metadata.issubset(config.OUTPUT_COLUMNS)


def test_silver_and_gold_use_an_explicit_check_in_date() -> None:
    project_root = Path(__file__).parents[1]
    silver_source = (project_root / "databricks" / "agoda_etl" / "silver.py").read_text(encoding="utf-8")
    gold_source = (project_root / "databricks" / "agoda_etl" / "gold.py").read_text(encoding="utf-8")
    bootstrap_source = (project_root / "databricks" / "agoda_etl" / "bootstrap.py").read_text(encoding="utf-8")

    assert 'withColumn("check_in_date", F.to_date("check_in"))' in silver_source
    assert 'groupBy("check_in_date", "destination")' in gold_source
    assert "RENAME COLUMN date TO check_in_date" in bootstrap_source


def test_data_quality_contract_and_operational_tables_are_declared() -> None:
    project_root = Path(__file__).parents[1]
    contract_path = project_root / "databricks" / "contracts" / "agoda_hotel.yaml"
    quality_source = (project_root / "databricks" / "agoda_etl" / "data_quality.py").read_text(encoding="utf-8")
    bootstrap_source = (project_root / "databricks" / "agoda_etl" / "bootstrap.py").read_text(encoding="utf-8")

    assert contract_path.is_file()
    assert "version:" in contract_path.read_text(encoding="utf-8")
    assert "validate_source_schema" in quality_source
    assert "check_out_not_after_check_in" in quality_source
    assert "QUARANTINE_TABLE" in bootstrap_source
    assert "AUDIT_TABLE" in bootstrap_source


def test_bronze_retry_skips_a_fully_loaded_batch() -> None:
    project_root = Path(__file__).parents[1]
    bronze_source = (project_root / "databricks" / "agoda_etl" / "bronze.py").read_text(encoding="utf-8")

    assert "if skipped_files == len(source_files):" in bronze_source
    assert '"files_loaded": 0, "files_skipped": skipped_files' in bronze_source
    assert "Bronze ingestion already complete" in bronze_source
