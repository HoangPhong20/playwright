"""Validate completed crawler manifests for downstream tasks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agoda_crawler.run_context import RunContext


def expected_manifest_path(output_dir: Path, run_context: RunContext) -> Path:
    return run_context.output_directory(output_dir) / "run_manifest.json"


def completed_manifest_path(
    output_dir: Path, batch_context: RunContext
) -> tuple[Path, RunContext]:
    """Resolve the crawler attempt selected by its completion pointer."""
    pointer_path = batch_context.completion_pointer_path(output_dir)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    expected_batch = batch_context.batch_id
    if pointer.get("batch_id") != expected_batch:
        raise ValueError(
            f"Completion pointer batch_id is {pointer.get('batch_id')!r}, "
            f"expected {expected_batch!r}"
        )
    if pointer.get("airflow_dag_id") != batch_context.airflow_dag_id:
        raise ValueError("Completion pointer belongs to another Airflow DAG")
    if pointer.get("airflow_run_id") != batch_context.airflow_run_id:
        raise ValueError("Completion pointer belongs to another Airflow run")
    attempt = pointer.get("airflow_try_number")
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("Completion pointer has an invalid crawler attempt")

    completed_context = RunContext(
        batch_context.airflow_dag_id,
        batch_context.airflow_run_id,
        attempt,
    )
    expected_path = expected_manifest_path(output_dir, completed_context)
    declared_path = Path(str(pointer.get("manifest_path", "")))
    if declared_path != expected_path:
        raise ValueError("Completion pointer manifest path is outside its crawler attempt")
    return expected_path, completed_context


def validate_manifest(manifest_path: Path, run_context: RunContext) -> dict[str, Any]:
    """Validate a complete manifest and the non-empty JSONL files it declares."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise ValueError(f"Run status is {manifest.get('status')!r}, expected 'complete'")
    expected_metadata = run_context.record_metadata()
    for field in (
        "airflow_dag_id",
        "airflow_run_id",
        "airflow_try_number",
        "batch_id",
    ):
        expected_value = expected_metadata[field]
        if manifest.get(field) != expected_value:
            raise ValueError(
                f"Manifest {field} is {manifest.get(field)!r}, expected {expected_value!r}"
            )

    stays = manifest.get("stays")
    if not isinstance(stays, list) or not stays:
        raise ValueError("Run manifest has no completed stays")

    publishable_records = sum(
        int(stay.get("publishable_records", 0))
        for stay in stays
        if isinstance(stay, dict)
    )
    if publishable_records < 1:
        raise ValueError("Run completed without publishable records")

    missing_outputs = []
    for stay in stays:
        if not isinstance(stay, dict):
            continue
        output_path = Path(str(stay.get("output_path", "")))
        if not output_path.is_file() or output_path.stat().st_size == 0:
            missing_outputs.append(str(output_path))
    if missing_outputs:
        raise ValueError("Missing or empty JSONL output: " + ", ".join(missing_outputs))

    return {
        "manifest_path": str(manifest_path),
        "batch_id": manifest.get("batch_id"),
        "publishable_records": publishable_records,
    }
