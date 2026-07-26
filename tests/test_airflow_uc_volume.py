import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from agoda_crawler.run_context import RunContext


SCRIPTS_DIR = Path(__file__).parents[1] / "airflow" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


upload_to_uc_volume = load_script("upload_to_uc_volume")
cleanup_local_output = load_script("cleanup_local_output")

RUN_CONTEXT = RunContext(
    "agoda_daily_crawl", "manual__2026-07-25T08:00:00+07:00", 2
)


def write_complete_attempt(tmp_path: Path, finished_at: datetime | None = None) -> Path:
    run_dir = RUN_CONTEXT.output_directory(tmp_path)
    run_dir.mkdir(parents=True)
    output_path = run_dir / "agoda_hotels_2026-08-15.jsonl"
    output_path.write_text('{"hotel_name":"Example"}\n', encoding="utf-8")
    manifest = {
        "status": "complete",
        "finished_at": (finished_at or datetime.now(timezone.utc)).isoformat(),
        **RUN_CONTEXT.record_metadata(),
        "stays": [
            {
                "publishable_records": 1,
                "output_path": str(output_path),
                "output_file": output_path.name,
            }
        ],
    }
    manifest_path = run_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    RUN_CONTEXT.completion_pointer_path(tmp_path).write_text(
        json.dumps({**RUN_CONTEXT.record_metadata(), "manifest_path": str(manifest_path)}),
        encoding="utf-8",
    )
    return run_dir


class FakeFiles:
    def __init__(self) -> None:
        self.directories: list[str] = []
        self.uploads: list[tuple[str, bytes, bool]] = []

    def create_directory(self, path: str) -> None:
        self.directories.append(path)

    def upload_from(self, path: str, source_path: str, overwrite: bool) -> None:
        self.uploads.append((path, Path(source_path).read_bytes(), overwrite))


class FakeWorkspaceClient:
    def __init__(self) -> None:
        self.files = FakeFiles()


def test_uploads_jsonl_before_manifest_and_writes_local_receipt(tmp_path):
    run_dir = write_complete_attempt(tmp_path)
    client = FakeWorkspaceClient()

    receipt = upload_to_uc_volume.upload_batch(
        tmp_path,
        RUN_CONTEXT.airflow_dag_id,
        RUN_CONTEXT.airflow_run_id,
        "/Volumes/agoda/raw/crawler",
        client,
    )

    assert receipt["volume_path"].endswith("attempt=2")
    assert [Path(upload[0]).name for upload in client.files.uploads] == [
        "agoda_hotels_2026-08-15.jsonl",
        "run_manifest.json",
    ]
    assert all(upload[2] is True for upload in client.files.uploads)
    assert (run_dir / "upload_receipt.json").is_file()


def test_cleanup_only_removes_old_attempts_with_a_receipt(tmp_path):
    run_dir = write_complete_attempt(tmp_path, datetime.now(timezone.utc) - timedelta(days=15))
    receipt = {**RUN_CONTEXT.record_metadata(), "uploaded_at": datetime.now(timezone.utc).isoformat()}
    (run_dir / "upload_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

    deleted = cleanup_local_output.cleanup_old_attempts(tmp_path, retention_days=14)

    assert deleted == [run_dir]
    assert not run_dir.exists()


def test_cleanup_removes_debug_for_the_same_uploaded_batch(tmp_path):
    run_dir = write_complete_attempt(tmp_path, datetime.now(timezone.utc) - timedelta(days=15))
    receipt = {**RUN_CONTEXT.record_metadata(), "uploaded_at": datetime.now(timezone.utc).isoformat()}
    (run_dir / "upload_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    debug_root = tmp_path / "debug"
    debug_dir = debug_root / RUN_CONTEXT.path_batch_id
    debug_dir.mkdir(parents=True)
    (debug_dir / "summary.json").write_text("{}", encoding="utf-8")

    cleanup_local_output.cleanup_old_attempts(
        tmp_path, retention_days=14, debug_root=debug_root
    )

    assert not debug_dir.exists()


def test_cleanup_keeps_attempt_without_upload_receipt(tmp_path):
    run_dir = write_complete_attempt(tmp_path, datetime.now(timezone.utc) - timedelta(days=15))

    deleted = cleanup_local_output.cleanup_old_attempts(tmp_path, retention_days=14)

    assert deleted == []
    assert run_dir.is_dir()
