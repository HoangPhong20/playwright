"""Trigger one Databricks Job for the exact crawler manifest uploaded by Airflow."""

from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
from typing import Any

from agoda_crawler.run_context import RunContext
from agoda_crawler.run_manifest import completed_manifest_path, validate_manifest
from agoda_crawler.uc_volume import remote_attempt_directory, validated_volume_root


def idempotency_token(airflow_dag_id: str, airflow_run_id: str) -> str:
    """Return one stable token for all retries of this Airflow DAG run."""
    value = f"{airflow_dag_id}\x1f{airflow_run_id}\x1ftrigger_databricks_job"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_receipt(path: Path, run_context: RunContext) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Upload receipt does not exist: {path}. Run upload_to_uc_volume first."
        )
    receipt = json.loads(path.read_text(encoding="utf-8"))
    expected = run_context.record_metadata()
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ValueError(
                f"Upload receipt {field} is {receipt.get(field)!r}, expected {value!r}"
            )
    return receipt


def uploaded_manifest_path(
    output_dir: Path,
    airflow_dag_id: str,
    airflow_run_id: str,
    volume_path: str,
) -> tuple[str, RunContext]:
    """Resolve the immutable remote manifest selected by the upload receipt."""
    batch_context = RunContext(airflow_dag_id, airflow_run_id, 1)
    local_manifest, run_context = completed_manifest_path(output_dir, batch_context)
    validate_manifest(local_manifest, run_context)
    receipt = _read_receipt(local_manifest.parent / "upload_receipt.json", run_context)

    expected_directory = remote_attempt_directory(
        validated_volume_root(volume_path), run_context
    )
    receipt_directory = PurePosixPath(str(receipt.get("volume_path", "")))
    if receipt_directory != expected_directory:
        raise ValueError(
            "Upload receipt volume_path does not match the expected crawler attempt"
        )

    manifest_path = receipt_directory / "run_manifest.json"
    uploaded_files = receipt.get("files")
    if not isinstance(uploaded_files, list) or not any(
        isinstance(item, dict) and item.get("remote_path") == str(manifest_path)
        for item in uploaded_files
    ):
        raise ValueError("Upload receipt does not confirm that run_manifest.json was uploaded")
    return str(manifest_path), run_context


def _result_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def trigger_databricks_job(
    output_dir: Path,
    airflow_dag_id: str,
    airflow_run_id: str,
    volume_path: str,
    job_id: int,
    timeout_seconds: int,
    workspace_client: Any | None = None,
) -> dict[str, Any]:
    """Submit and wait for the Databricks Job that consumes this manifest."""
    if job_id < 1:
        raise ValueError("DATABRICKS_JOB_ID must be a positive integer")
    if timeout_seconds < 1:
        raise ValueError("DATABRICKS_JOB_TIMEOUT_SECONDS must be at least 1")

    manifest_path, run_context = uploaded_manifest_path(
        output_dir, airflow_dag_id, airflow_run_id, volume_path
    )
    if workspace_client is None:
        host = os.environ.get("DATABRICKS_HOST", "").strip()
        token = os.environ.get("DATABRICKS_TOKEN", "").strip()
        if not host or not token:
            raise ValueError("DATABRICKS_HOST and DATABRICKS_TOKEN must be configured")
        from databricks.sdk import WorkspaceClient

        workspace_client = WorkspaceClient(host=host, token=token)

    waiter = workspace_client.jobs.run_now(
        job_id=job_id,
        job_parameters={"manifest_path": manifest_path},
        idempotency_token=idempotency_token(airflow_dag_id, airflow_run_id),
    )
    submitted_run_id = getattr(getattr(waiter, "response", None), "run_id", None)
    completed_run = waiter.result(timeout=timedelta(seconds=timeout_seconds))
    result_state = _result_value(getattr(getattr(completed_run, "state", None), "result_state", None))
    if result_state != "SUCCESS":
        state_message = getattr(getattr(completed_run, "state", None), "state_message", "")
        raise RuntimeError(
            "Databricks Job did not succeed: "
            f"run_id={getattr(completed_run, 'run_id', submitted_run_id)} "
            f"result_state={result_state!r} message={state_message!r}"
        )
    return {
        "job_id": job_id,
        "databricks_run_id": getattr(completed_run, "run_id", submitted_run_id),
        "manifest_path": manifest_path,
        "batch_id": run_context.batch_id,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--airflow-dag-id", required=True)
    parser.add_argument("--airflow-run-id", required=True)
    parser.add_argument(
        "--volume-path", default=os.environ.get("DATABRICKS_UC_VOLUME_PATH", "")
    )
    parser.add_argument(
        "--job-id", type=int, default=int(os.environ.get("DATABRICKS_JOB_ID", "0"))
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.environ.get("DATABRICKS_JOB_TIMEOUT_SECONDS", "3600")),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = trigger_databricks_job(
            args.output_dir,
            args.airflow_dag_id,
            args.airflow_run_id,
            args.volume_path,
            args.job_id,
            args.timeout_seconds,
        )
    except Exception as error:
        print(f"TRIGGER_DATABRICKS_JOB=failed: {error}", file=sys.stderr)
        return 1
    print(
        "TRIGGER_DATABRICKS_JOB=success "
        f"job_id={result['job_id']} run_id={result['databricks_run_id']} "
        f"batch_id={result['batch_id']} manifest_path={result['manifest_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
