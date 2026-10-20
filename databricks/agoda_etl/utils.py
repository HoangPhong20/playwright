"""Pure helpers shared by the Agoda ETL modules."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import PurePosixPath
from typing import Any


def validate_manifest_path(manifest_path: str, volume_root: str) -> PurePosixPath:
    root = PurePosixPath(volume_root.rstrip("/"))
    candidate = PurePosixPath(manifest_path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("manifest_path must be an absolute path without '..'")
    if not candidate.is_relative_to(root):
        raise ValueError(f"manifest_path must be under {root}")
    if candidate.name != "run_manifest.json":
        raise ValueError("manifest_path must point to run_manifest.json")
    return candidate


def parse_manifest_text(text: str) -> dict[str, Any]:
    try:
        manifest = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError(f"manifest is not valid JSON: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    return manifest


def _validate_job_outcomes(manifest: dict[str, Any]) -> None:
    """Validate current per-job manifests while allowing legacy manifests."""
    if "jobs" not in manifest:
        return
    jobs = manifest["jobs"]
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("Run manifest has no per-job outcomes")

    successful_stop_reasons = {"max_pages_reached", "end_of_results"}
    actual_jobs: Counter[tuple[str, str, str]] = Counter()
    for job in jobs:
        if not isinstance(job, dict):
            raise ValueError("Run manifest has an invalid job outcome")
        identity = tuple(job.get(field) for field in ("destination", "check_in", "check_out"))
        if any(not isinstance(value, str) or not value for value in identity):
            raise ValueError("Run manifest has an invalid job identity")
        destination, check_in, check_out = identity
        actual_jobs[(destination, check_in, check_out)] += 1

        pages_requested = job.get("pages_requested")
        pages_collected = job.get("pages_collected")
        page_counts_valid = all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (pages_requested, pages_collected)
        )
        if not page_counts_valid or pages_requested < 0 or pages_collected < 1:
            raise ValueError("Run manifest has invalid per-job page counts")
        if pages_requested and pages_collected > pages_requested:
            raise ValueError("A job collected more pages than its requested upper bound")

        stop_reason = job.get("stop_reason")
        if job.get("status") != "complete":
            raise ValueError(f"Job {destination!r} status is incomplete")
        if stop_reason not in successful_stop_reasons:
            raise ValueError(f"Job {destination!r} has an incomplete stop reason")
        if stop_reason == "max_pages_reached" and (
            pages_requested == 0 or pages_collected != pages_requested
        ):
            raise ValueError(f"Job {destination!r} did not reach its requested page limit")

        page_statuses = job.get("page_statuses")
        page_numbers = {str(page) for page in range(1, pages_collected + 1)}
        if (
            not isinstance(page_statuses, dict)
            or set(page_statuses) != page_numbers
            or any(status != "collected" for status in page_statuses.values())
        ):
            raise ValueError(f"Job {destination!r} has incomplete page statuses")
        if (
            stop_reason == "end_of_results"
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
                stay_identity = (stay.get("check_in"), stay.get("check_out"))
                if any(
                    not isinstance(value, str) or not value for value in stay_identity
                ):
                    raise ValueError("Run manifest has an invalid planned stay")
                check_in, check_out = stay_identity
                expected_jobs[(destination, check_in, check_out)] += 1
        if actual_jobs != expected_jobs:
            raise ValueError("Run manifest per-job outcomes do not match planned jobs")


def manifest_output_record_counts(
    manifest: dict[str, Any], manifest_path: str | PurePosixPath
) -> dict[str, int]:
    """Return each declared JSONL file and its manifest record count."""
    if manifest.get("status") != "complete":
        raise ValueError("manifest status must be 'complete'")
    for field in ("batch_id", "airflow_dag_id", "airflow_run_id"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"manifest has an invalid {field}")
    airflow_try_number = manifest.get("airflow_try_number")
    if (
        not isinstance(airflow_try_number, int)
        or isinstance(airflow_try_number, bool)
        or airflow_try_number < 1
    ):
        raise ValueError("manifest has an invalid airflow_try_number")

    parent = PurePosixPath(manifest_path).parent
    stays = manifest.get("stays")
    if not isinstance(stays, list) or not stays:
        raise ValueError("manifest has no completed stays")

    files: dict[str, int] = {}
    for stay in stays:
        if not isinstance(stay, dict):
            raise ValueError("manifest has an invalid stay entry")
        filename = stay.get("output_file")
        if not isinstance(filename, str) or not filename.endswith(".jsonl"):
            raise ValueError("manifest stay has an invalid output_file")
        if PurePosixPath(filename).name != filename:
            raise ValueError("manifest output_file must be a filename, not a path")
        publishable_records = stay.get("publishable_records", 0)
        if (
            not isinstance(publishable_records, int)
            or isinstance(publishable_records, bool)
            or publishable_records < 1
        ):
            raise ValueError("manifest stay has no publishable records")
        file_path = str(parent / filename)
        if file_path in files:
            raise ValueError("manifest declares the same output_file more than once")
        files[file_path] = publishable_records

    _validate_job_outcomes(manifest)
    return files


def manifest_output_files(
    manifest: dict[str, Any], manifest_path: str | PurePosixPath
) -> list[str]:
    """Return only JSONL files declared by a complete crawler manifest."""
    return list(manifest_output_record_counts(manifest, manifest_path))
