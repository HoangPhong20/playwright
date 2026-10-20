import importlib.util
import json
from pathlib import Path

import pytest

from agoda_crawler.run_context import RunContext


MODULE_PATH = Path(__file__).parents[1] / "airflow" / "scripts" / "validate_latest_run.py"
SPEC = importlib.util.spec_from_file_location("validate_latest_run", MODULE_PATH)
validate_latest_run = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validate_latest_run)


RUN_CONTEXT = RunContext(
    airflow_dag_id="agoda_daily_crawl",
    airflow_run_id="manual__2026-07-25T08:00:00+07:00",
    airflow_try_number=1,
)


def write_manifest(tmp_path: Path, **overrides) -> Path:
    run_dir = RUN_CONTEXT.output_directory(tmp_path)
    run_dir.mkdir(parents=True)
    output_path = run_dir / "agoda_hotels_2026-08-15.jsonl"
    output_path.write_text('{"hotel_name":"Example"}\n', encoding="utf-8")
    manifest = {
        "run_id": RUN_CONTEXT.airflow_run_id,
        "status": "complete",
        **RUN_CONTEXT.record_metadata(),
        "stays": [
            {
                "publishable_records": 1,
                "output_path": str(output_path),
            }
        ],
    }
    manifest.update(overrides)
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    pointer = {
        **RUN_CONTEXT.record_metadata(),
        "manifest_path": str(manifest_path),
    }
    RUN_CONTEXT.completion_pointer_path(tmp_path).write_text(
        json.dumps(pointer), encoding="utf-8"
    )
    return manifest_path


def test_validate_manifest_accepts_expected_batch_and_output(tmp_path):
    manifest_path = write_manifest(tmp_path)

    result = validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)

    assert result["batch_id"] == RUN_CONTEXT.batch_id
    assert result["publishable_records"] == 1


def test_validate_manifest_accepts_explicit_end_before_page_upper_bound(
    tmp_path, representative_job_manifest_fields
):
    manifest_path = write_manifest(
        tmp_path, **representative_job_manifest_fields
    )

    result = validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)

    assert result["publishable_records"] == 1


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda job: job.update(status="incomplete", stop_reason="low_new_records"), "status"),
        (lambda job: job.update(stop_reason="max_pages_reached"), "page limit"),
    ],
)
def test_validate_manifest_rejects_incomplete_or_conflicting_job_outcomes(
    tmp_path, representative_job_manifest_fields, mutation, message
):
    job = dict(representative_job_manifest_fields["jobs"][0])
    mutation(job)
    manifest_data = {
        **representative_job_manifest_fields,
        "jobs": [job],
    }
    manifest_path = write_manifest(tmp_path, **manifest_data)

    with pytest.raises(ValueError, match=message):
        validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)


def test_validate_manifest_rejects_missing_planned_job_outcome(
    tmp_path, representative_job_manifest_fields
):
    manifest_data = representative_job_manifest_fields
    manifest_data["destinations"].append("Da Nang")
    manifest_path = write_manifest(tmp_path, **manifest_data)

    with pytest.raises(ValueError, match="do not match planned jobs"):
        validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)


def test_validate_manifest_rejects_inconsistent_collected_page_statuses(
    tmp_path, representative_job_manifest_fields
):
    job = dict(representative_job_manifest_fields["jobs"][0])
    job["pages_collected"] = 2
    manifest_path = write_manifest(
        tmp_path,
        **{**representative_job_manifest_fields, "jobs": [job]},
    )

    with pytest.raises(ValueError, match="page statuses"):
        validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)


def test_validate_manifest_rejects_duplicate_job_outcomes(
    tmp_path, representative_job_manifest_fields
):
    job = representative_job_manifest_fields["jobs"][0]
    manifest_path = write_manifest(
        tmp_path,
        **{
            **representative_job_manifest_fields,
            "jobs": [job, dict(job)],
        },
    )

    with pytest.raises(ValueError, match="do not match planned jobs"):
        validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)


@pytest.mark.parametrize(
    "job_change, message",
    [
        (lambda job: job.update(destination=42), "invalid job identity"),
        (lambda job: job.update(status="failed"), "status"),
        (
            lambda job: job.update(
                pages_requested=1,
                pages_collected=1,
                stop_reason="end_of_results",
            ),
            "conflicting stop reason",
        ),
        (
            lambda job: job.update(
                page_statuses={"1": "collected", "2": "collected"}
            ),
            "page statuses",
        ),
    ],
)
def test_validate_manifest_rejects_invalid_job_outcomes(
    tmp_path, representative_job_manifest_fields, job_change, message
):
    job = dict(representative_job_manifest_fields["jobs"][0])
    job_change(job)
    manifest_path = write_manifest(
        tmp_path,
        **{**representative_job_manifest_fields, "jobs": [job]},
    )

    with pytest.raises(ValueError, match=message):
        validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)


def test_validate_manifest_rejects_boolean_try_number(tmp_path):
    manifest_path = write_manifest(tmp_path, airflow_try_number=True)

    with pytest.raises(ValueError, match="airflow_try_number"):
        validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)


def test_expected_manifest_path_is_scoped_to_batch_and_attempt(tmp_path):
    path = validate_latest_run.expected_manifest_path(tmp_path, RUN_CONTEXT)

    assert path == RUN_CONTEXT.output_directory(tmp_path) / "run_manifest.json"
    assert "attempt=1" in path.as_posix()


def test_completed_manifest_path_uses_crawler_attempt_pointer(tmp_path):
    manifest_path = write_manifest(tmp_path)
    batch_context = RunContext(RUN_CONTEXT.airflow_dag_id, RUN_CONTEXT.airflow_run_id, 1)

    path, resolved_context = validate_latest_run.completed_manifest_path(
        tmp_path, batch_context
    )

    assert path == manifest_path
    assert resolved_context == RUN_CONTEXT


def test_validate_manifest_rejects_other_airflow_run(tmp_path):
    manifest_path = write_manifest(tmp_path)
    other_context = RunContext("agoda_daily_crawl", "manual__other", 1)

    with pytest.raises(ValueError, match="airflow_run_id"):
        validate_latest_run.validate_manifest(manifest_path, other_context)


def test_validate_manifest_rejects_missing_publishable_records(tmp_path):
    manifest_path = write_manifest(
        tmp_path,
        stays=[{"publishable_records": 0, "output_path": "unused.jsonl"}],
    )

    with pytest.raises(ValueError, match="without publishable records"):
        validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)


@pytest.mark.parametrize("boolean_count", [True, False])
def test_validate_manifest_rejects_boolean_publishable_counts(
    tmp_path, boolean_count
):
    output_path = (
        RUN_CONTEXT.output_directory(tmp_path) / "agoda_hotels_2026-08-15.jsonl"
    )
    manifest_path = write_manifest(
        tmp_path,
        stays=[
            {"publishable_records": boolean_count, "output_path": str(output_path)},
            {"publishable_records": 1, "output_path": str(output_path)},
        ],
    )

    with pytest.raises(ValueError, match="invalid publishable record count"):
        validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)
