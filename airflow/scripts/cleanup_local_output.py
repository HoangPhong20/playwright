"""Remove old, successfully uploaded crawler attempts from local storage."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from agoda_crawler.run_context import RunContext, path_safe_identifier


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_uploaded_complete_attempt(attempt_dir: Path) -> tuple[dict[str, Any], datetime] | None:
    manifest_path = attempt_dir / "run_manifest.json"
    receipt_path = attempt_dir / "upload_receipt.json"
    if not manifest_path.is_file() or not receipt_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    finished_at = _parse_timestamp(manifest.get("finished_at"))
    if (
        manifest.get("status") != "complete"
        or finished_at is None
        or receipt.get("batch_id") != manifest.get("batch_id")
        or receipt.get("airflow_try_number") != manifest.get("airflow_try_number")
    ):
        return None
    return manifest, finished_at


def _remove_empty_parents(attempt_dir: Path, output_root: Path) -> None:
    for directory in (attempt_dir.parent, attempt_dir.parent.parent):
        if directory == output_root or directory.parent == output_root.parent:
            return
        try:
            directory.rmdir()
        except OSError:
            return


def _remove_batch_debug_artifacts(debug_root: Path, batch_id: str) -> None:
    """Remove debug files for an old batch that has already reached the Volume."""
    root = debug_root.resolve()
    directory = (root / path_safe_identifier(batch_id)).resolve()
    try:
        directory.relative_to(root)
    except ValueError:
        return
    if directory.is_dir():
        shutil.rmtree(directory)


def cleanup_old_attempts(
    output_root: Path,
    retention_days: int,
    exclude_batch_id: str | None = None,
    debug_root: Path | None = None,
    now: datetime | None = None,
) -> list[Path]:
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")
    root = output_root.resolve()
    if not root.is_dir():
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=retention_days)
    deleted: list[Path] = []
    for attempt_dir in root.glob("dag_id=*/batch_id=*/attempt=*"):
        try:
            resolved = attempt_dir.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        result = _is_uploaded_complete_attempt(resolved)
        if result is None:
            continue
        manifest, finished_at = result
        if manifest.get("batch_id") == exclude_batch_id or finished_at >= cutoff:
            continue
        shutil.rmtree(resolved)
        if debug_root is not None:
            _remove_batch_debug_artifacts(debug_root, str(manifest["batch_id"]))
        _remove_empty_parents(resolved, root)
        deleted.append(resolved)
    return deleted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument(
        "--debug-dir",
        type=Path,
        help="Optional debug root; matching uploaded batches are removed with output",
    )
    parser.add_argument("--airflow-dag-id")
    parser.add_argument("--airflow-run-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if bool(args.airflow_dag_id) != bool(args.airflow_run_id):
        print(
            "CLEANUP_LOCAL_OUTPUT=failed: both Airflow identifiers are required together",
            file=sys.stderr,
        )
        return 1
    exclude_batch_id = None
    if args.airflow_dag_id:
        exclude_batch_id = RunContext(args.airflow_dag_id, args.airflow_run_id, 1).batch_id
    try:
        deleted = cleanup_old_attempts(
            args.output_dir,
            args.retention_days,
            exclude_batch_id,
            args.debug_dir,
        )
    except (OSError, ValueError) as error:
        print(f"CLEANUP_LOCAL_OUTPUT=failed: {error}", file=sys.stderr)
        return 1
    print(f"CLEANUP_LOCAL_OUTPUT=success deleted_attempts={len(deleted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
