import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "databricks" / "agoda_etl" / "utils.py"
SPEC = importlib.util.spec_from_file_location("agoda_etl_utils", MODULE_PATH)
utils = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(utils)

CONFIG_PATH = Path(__file__).parents[1] / "databricks" / "agoda_etl" / "config.py"
CONFIG_SPEC = importlib.util.spec_from_file_location("agoda_etl_config", CONFIG_PATH)
config = importlib.util.module_from_spec(CONFIG_SPEC)
assert CONFIG_SPEC.loader is not None
CONFIG_SPEC.loader.exec_module(config)


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
