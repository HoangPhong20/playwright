"""Fail an Airflow task when its crawler run did not create usable output."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agoda_crawler.run_context import RunContext
from agoda_crawler.run_manifest import (
    completed_manifest_path,
    expected_manifest_path,
    validate_manifest,
)


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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch_context = RunContext(
        args.airflow_dag_id,
        args.airflow_run_id,
        1,
    )
    try:
        manifest_path, run_context = completed_manifest_path(args.output_dir, batch_context)
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Expected manifest does not exist: {manifest_path}")
        result = validate_manifest(manifest_path, run_context)
    except (FileNotFoundError, OSError, ValueError) as error:
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
