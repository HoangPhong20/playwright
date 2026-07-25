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
    return manifest_path


def test_validate_manifest_accepts_expected_batch_and_output(tmp_path):
    manifest_path = write_manifest(tmp_path)

    result = validate_latest_run.validate_manifest(manifest_path, RUN_CONTEXT)

    assert result["batch_id"] == RUN_CONTEXT.batch_id
    assert result["publishable_records"] == 1


def test_expected_manifest_path_is_scoped_to_batch_and_attempt(tmp_path):
    path = validate_latest_run.expected_manifest_path(tmp_path, RUN_CONTEXT)

    assert path == RUN_CONTEXT.output_directory(tmp_path) / "run_manifest.json"
    assert "attempt=1" in path.as_posix()


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
