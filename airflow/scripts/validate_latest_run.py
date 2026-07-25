"""Fail an Airflow task when its crawler run did not create usable output."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agoda_crawler.run_context import RunContext


def expected_manifest_path(output_dir: Path, run_context: RunContext) -> Path:
    return run_context.output_directory(output_dir) / "run_manifest.json"


def validate_manifest(manifest_path: Path, run_context: RunContext) -> dict[str, Any]:
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Root directory that contains Airflow crawler batches",
    )
    parser.add_argument("--airflow-dag-id", required=True)
    parser.add_argument("--airflow-run-id", required=True)
    parser.add_argument("--airflow-try-number", required=True, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_context = RunContext(
        args.airflow_dag_id,
        args.airflow_run_id,
        args.airflow_try_number,
    )
    try:
        manifest_path = expected_manifest_path(args.output_dir, run_context)
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Expected manifest does not exist: {manifest_path}")
        result = validate_manifest(manifest_path, run_context)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"VERIFY_CRAWL_OUTPUT=failed: {error}", file=sys.stderr)
        return 1

    print(
        "VERIFY_CRAWL_OUTPUT=success "
        f"batch_id={result['batch_id']} records={result['publishable_records']} "
        f"manifest={result['manifest_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
