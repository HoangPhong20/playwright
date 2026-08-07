"""Pure helpers shared by the Agoda ETL modules."""

from __future__ import annotations

import json
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


def manifest_output_record_counts(
    manifest: dict[str, Any], manifest_path: str | PurePosixPath
) -> dict[str, int]:
    """Return each declared JSONL file and its manifest record count."""
    if manifest.get("status") != "complete":
        raise ValueError("manifest status must be 'complete'")
    for field in ("batch_id", "airflow_dag_id", "airflow_run_id"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"manifest has an invalid {field}")
    if not isinstance(manifest.get("airflow_try_number"), int) or manifest["airflow_try_number"] < 1:
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
        if not isinstance(publishable_records, int) or publishable_records < 1:
            raise ValueError("manifest stay has no publishable records")
        file_path = str(parent / filename)
        if file_path in files:
            raise ValueError("manifest declares the same output_file more than once")
        files[file_path] = publishable_records
    return files


def manifest_output_files(
    manifest: dict[str, Any], manifest_path: str | PurePosixPath
) -> list[str]:
    """Return only JSONL files declared by a complete crawler manifest."""
    return list(manifest_output_record_counts(manifest, manifest_path))
