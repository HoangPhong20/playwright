"""Upload one verified Airflow crawler batch to a Unity Catalog Volume."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from typing import Any

from agoda_crawler.run_context import RunContext
from agoda_crawler.run_manifest import completed_manifest_path, validate_manifest


def validated_volume_root(value: str) -> PurePosixPath:
    root = PurePosixPath(value.rstrip("/"))
    if len(root.parts) != 5 or root.parts[1] != "Volumes":
        raise ValueError(
            "DATABRICKS_UC_VOLUME_PATH must be /Volumes/<catalog>/<schema>/<volume>"
        )
    return root


def remote_attempt_directory(volume_root: PurePosixPath, context: RunContext) -> PurePosixPath:
    return (
        volume_root
        / f"dag_id={context.path_dag_id}"
        / f"batch_id={context.path_batch_id}"
        / f"attempt={context.airflow_try_number}"
    )


def manifest_output_files(manifest: dict[str, Any], attempt_directory: Path) -> list[Path]:
    files: list[Path] = []
    for stay in manifest.get("stays", []):
        if not isinstance(stay, dict):
            raise ValueError("Run manifest has an invalid stay entry")
        filename = stay.get("output_file") or Path(str(stay.get("output_path", ""))).name
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise ValueError("Run manifest has an unsafe output filename")
        path = attempt_directory / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Declared JSONL file is missing or empty: {path}")
        if path not in files:
            files.append(path)
    if not files:
        raise ValueError("Run manifest has no JSONL files to upload")
    return files


def _ensure_directory(client: Any, directory: PurePosixPath) -> None:
    client.files.create_directory(str(directory))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        json.dump(receipt, temporary, ensure_ascii=False, sort_keys=True)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def upload_batch(
    output_dir: Path,
    airflow_dag_id: str,
    airflow_run_id: str,
    volume_path: str,
    workspace_client: Any | None = None,
) -> dict[str, Any]:
    batch_context = RunContext(airflow_dag_id, airflow_run_id, 1)
    manifest_path, run_context = completed_manifest_path(output_dir, batch_context)
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Expected manifest does not exist: {manifest_path}")
    validation = validate_manifest(manifest_path, run_context)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    attempt_directory = manifest_path.parent
    output_files = manifest_output_files(manifest, attempt_directory)
    volume_root = validated_volume_root(volume_path)
    remote_directory = remote_attempt_directory(volume_root, run_context)

    if workspace_client is None:
        host = os.environ.get("DATABRICKS_HOST", "").strip()
        token = os.environ.get("DATABRICKS_TOKEN", "").strip()
        if not host or not token:
            raise ValueError("DATABRICKS_HOST and DATABRICKS_TOKEN must be configured")
        from databricks.sdk import WorkspaceClient

        workspace_client = WorkspaceClient(host=host, token=token)

    current = volume_root
    for segment in remote_directory.parts[len(volume_root.parts) :]:
        current /= segment
        _ensure_directory(workspace_client, current)

    uploaded_files = []
    # The manifest is intentionally last: consumers may treat its presence as
    # the ready signal for the immutable batch directory.
    for local_path in [*output_files, manifest_path]:
        remote_path = remote_directory / local_path.name
        workspace_client.files.upload_from(
            str(remote_path), str(local_path), overwrite=True
        )
        uploaded_files.append(
            {
                "local_file": local_path.name,
                "remote_path": str(remote_path),
                "size_bytes": local_path.stat().st_size,
                "sha256": _sha256(local_path),
            }
        )

    receipt = {
        **run_context.record_metadata(),
        "manifest_path": str(manifest_path),
        "volume_path": str(remote_directory),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "files": uploaded_files,
        "publishable_records": validation["publishable_records"],
    }
    _write_receipt(attempt_directory / "upload_receipt.json", receipt)
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--airflow-dag-id", required=True)
    parser.add_argument("--airflow-run-id", required=True)
    parser.add_argument(
        "--volume-path",
        default=os.environ.get("DATABRICKS_UC_VOLUME_PATH", ""),
        help="Unity Catalog Volume root, e.g. /Volumes/agoda/raw/crawler",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        receipt = upload_batch(
            args.output_dir,
            args.airflow_dag_id,
            args.airflow_run_id,
            args.volume_path,
        )
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"UPLOAD_TO_UC_VOLUME=failed: {error}", file=sys.stderr)
        return 1
    print(
        "UPLOAD_TO_UC_VOLUME=success "
        f"batch_id={receipt['batch_id']} files={len(receipt['files'])} "
        f"volume={receipt['volume_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
