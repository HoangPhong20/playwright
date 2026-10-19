"""Validate completed crawler manifests for downstream tasks."""

from __future__ import annotations

import json
from collections import Counter
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

    if "jobs" in manifest:
        jobs = manifest["jobs"]
        if not isinstance(jobs, list) or not jobs:
            raise ValueError("Run manifest has no per-job outcomes")
        successful_stop_reasons = {"max_pages_reached", "end_of_results"}
        actual_jobs: Counter[tuple[str, str, str]] = Counter()
        for job in jobs:
            if not isinstance(job, dict):
                raise ValueError("Run manifest has an invalid job outcome")
            destination = job.get("destination")
            check_in = job.get("check_in")
            check_out = job.get("check_out")
            if (
                not isinstance(destination, str)
                or not destination
                or not isinstance(check_in, str)
                or not check_in
                or not isinstance(check_out, str)
                or not check_out
            ):
                raise ValueError("Run manifest has an invalid job identity")
            actual_jobs[(destination, check_in, check_out)] += 1
            pages_requested = job.get("pages_requested")
            pages_collected = job.get("pages_collected")
            if (
                not isinstance(pages_requested, int)
                or isinstance(pages_requested, bool)
                or pages_requested < 0
                or not isinstance(pages_collected, int)
                or isinstance(pages_collected, bool)
                or pages_collected < 1
            ):
                raise ValueError("Run manifest has invalid per-job page counts")
            if pages_requested and pages_collected > pages_requested:
                raise ValueError("A job collected more pages than its requested upper bound")
            if job.get("status") != "complete":
                raise ValueError(
                    f"Job {destination!r} status is {job.get('status')!r}, expected 'complete'"
                )
            if job.get("stop_reason") not in successful_stop_reasons:
                raise ValueError(f"Job {destination!r} has an incomplete stop reason")
            if job.get("stop_reason") == "max_pages_reached" and (
                pages_requested == 0 or pages_collected != pages_requested
            ):
                raise ValueError(f"Job {destination!r} did not reach its requested page limit")
            page_statuses = job.get("page_statuses")
            if (
                not isinstance(page_statuses, dict)
                or set(page_statuses) != {str(page) for page in range(1, pages_collected + 1)}
            ):
                raise ValueError(f"Job {destination!r} has invalid page statuses")
            if any(status != "collected" for status in page_statuses.values()):
                raise ValueError(f"Job {destination!r} has incomplete page statuses")
            if (
                job.get("stop_reason") == "end_of_results"
                and pages_requested > 0
                and pages_collected == pages_requested
            ):
                raise ValueError(f"Job {destination!r} has a conflicting stop reason")

        destinations = manifest.get("destinations")
        planned_stays = manifest.get("planned_stays")
        if isinstance(destinations, list) and isinstance(planned_stays, list):
            expected_jobs: Counter[tuple[str, str, str]] = Counter()
            for destination in destinations:
                if not isinstance(destination, str) or not destination:
                    raise ValueError("Run manifest has an invalid destination")
                for stay in planned_stays:
                    if not isinstance(stay, dict):
                        raise ValueError("Run manifest has an invalid planned stay")
                    check_in = stay.get("check_in")
                    check_out = stay.get("check_out")
                    if (
                        not isinstance(check_in, str)
                        or not check_in
                        or not isinstance(check_out, str)
                        or not check_out
                    ):
                        raise ValueError("Run manifest has an invalid planned stay")
                    expected_jobs[(destination, check_in, check_out)] += 1
            if actual_jobs != expected_jobs:
                raise ValueError("Run manifest per-job outcomes do not match planned jobs")

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
