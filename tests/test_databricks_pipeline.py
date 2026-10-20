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
from agoda_etl import config  # noqa: E402


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


def test_bootstrap_retains_check_in_date_migration() -> None:
    project_root = Path(__file__).parents[1]
    bootstrap_source = (project_root / "databricks" / "agoda_etl" / "bootstrap.py").read_text(encoding="utf-8")

    assert "delta.columnMapping.mode' = 'name" in bootstrap_source
    assert "RENAME COLUMN date TO check_in_date" in bootstrap_source


def test_data_quality_contract_and_operational_tables_are_declared() -> None:
    assert config.CONTRACT_VERSION == "1.1.0"
    assert config.CONTRACT["validation_layer"] == "silver"
    assert config.CONTRACT["fields"]["price_value"]["format"] == "positive_price"
    assert config.CONTRACT["cross_field_rules"] == ["check_out_after_check_in"]
    assert config.QUARANTINE_TABLE == "agoda.raw.agoda_hotel_quarantine"
    assert config.AUDIT_TABLE == "agoda.raw.agoda_pipeline_audit"


def test_manifest_exposes_expected_record_count_per_output_file() -> None:
    manifest_path = "/Volumes/agoda/raw/crawler/dag_id=agoda_daily_crawl/batch_id=manual/attempt=1/run_manifest.json"
    assert utils.manifest_output_record_counts(complete_manifest(), manifest_path) == {
        "/Volumes/agoda/raw/crawler/dag_id=agoda_daily_crawl/batch_id=manual/attempt=1/agoda_hotels_2026-08-16.jsonl": 3
    }


MANIFEST_PATH = (
    "/Volumes/agoda/raw/crawler/dag_id=agoda_daily_crawl/"
    "batch_id=manual/attempt=1/run_manifest.json"
)


def _manifest_with_job_fields(job_fields: dict) -> dict:
    return {**complete_manifest(), **job_fields}


def test_etl_manifest_accepts_shared_early_end_job(representative_job_manifest_fields):
    manifest = _manifest_with_job_fields(representative_job_manifest_fields)

    assert utils.manifest_output_record_counts(manifest, MANIFEST_PATH) == {
        "/Volumes/agoda/raw/crawler/dag_id=agoda_daily_crawl/"
        "batch_id=manual/attempt=1/agoda_hotels_2026-08-16.jsonl": 3
    }


def test_etl_manifest_accepts_unlimited_page_count(representative_job_manifest_fields):
    job = representative_job_manifest_fields["jobs"][0]
    job["pages_requested"] = 0
    manifest = _manifest_with_job_fields(representative_job_manifest_fields)

    assert utils.manifest_output_record_counts(manifest, MANIFEST_PATH)


def test_etl_manifest_preserves_legacy_manifests_without_jobs():
    assert utils.manifest_output_record_counts(complete_manifest(), MANIFEST_PATH)


@pytest.mark.parametrize(
    "job_change, message",
    [
        (lambda fields: fields.update(jobs=[]), "per-job outcomes"),
        (lambda fields: fields.update(jobs=[None]), "job outcome"),
        (
            lambda fields: fields["jobs"][0].update(destination=""),
            "job identity",
        ),
        (
            lambda fields: fields["jobs"][0].update(destination=42),
            "job identity",
        ),
        (
            lambda fields: fields["jobs"][0].update(status="incomplete"),
            "status",
        ),
        (
            lambda fields: fields["jobs"][0].update(status="failed"),
            "status",
        ),
        (
            lambda fields: fields["jobs"][0].update(stop_reason="low_new_records"),
            "stop reason",
        ),
        (
            lambda fields: fields["jobs"][0].update(stop_reason="max_pages_reached"),
            "page limit",
        ),
        (
            lambda fields: fields["jobs"][0].update(
                pages_requested=1,
                pages_collected=1,
                stop_reason="end_of_results",
            ),
            "conflicting stop reason",
        ),
        (
            lambda fields: fields["jobs"][0].update(page_statuses={}),
            "page statuses",
        ),
        (
            lambda fields: fields["jobs"][0].update(
                page_statuses={"1": "collected", "2": "collected"}
            ),
            "page statuses",
        ),
        (
            lambda fields: fields["jobs"][0].update(pages_requested=True),
            "page counts",
        ),
        (
            lambda fields: fields["jobs"][0].update(pages_collected=True),
            "page counts",
        ),
        (
            lambda fields: fields["jobs"][0].update(pages_requested=-1),
            "page counts",
        ),
        (
            lambda fields: fields["jobs"][0].update(pages_collected=0),
            "page counts",
        ),
        (
            lambda fields: fields["jobs"][0].update(pages_collected=6),
            "upper bound",
        ),
    ],
)
def test_etl_manifest_rejects_invalid_job_outcomes(
    representative_job_manifest_fields, job_change, message
):
    job_change(representative_job_manifest_fields)
    manifest = _manifest_with_job_fields(representative_job_manifest_fields)

    with pytest.raises(ValueError, match=message):
        utils.manifest_output_record_counts(manifest, MANIFEST_PATH)


@pytest.mark.parametrize(
    "planned_change, outcome_change",
    [
        (
            lambda fields: fields["destinations"].append("Da Nang"),
            None,
        ),
        (
            None,
            lambda fields: fields["jobs"].append(dict(fields["jobs"][0])),
        ),
    ],
)
def test_etl_manifest_requires_exact_planned_job_multiset(
    representative_job_manifest_fields, planned_change, outcome_change
):
    if planned_change is not None:
        planned_change(representative_job_manifest_fields)
    if outcome_change is not None:
        outcome_change(representative_job_manifest_fields)
    manifest = _manifest_with_job_fields(representative_job_manifest_fields)

    with pytest.raises(ValueError, match="do not match planned jobs"):
        utils.manifest_output_record_counts(manifest, MANIFEST_PATH)


@pytest.mark.parametrize(
    "field, value, message",
    [
        ("airflow_try_number", True, "airflow_try_number"),
        ("stays", [{"output_file": "x.jsonl", "publishable_records": True}], "publishable"),
    ],
)
def test_etl_manifest_rejects_boolean_positive_integers(field, value, message):
    manifest = complete_manifest()
    manifest[field] = value

    with pytest.raises(ValueError, match=message):
        utils.manifest_output_record_counts(manifest, MANIFEST_PATH)
