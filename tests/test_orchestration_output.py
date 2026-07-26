import json
from types import SimpleNamespace

import pytest

from agoda_crawler import orchestration
from agoda_crawler.run_context import RunContext


def test_prepare_run_output_directory_rejects_existing_attempt(tmp_path) -> None:
    attempt_dir = tmp_path / "attempt=1"
    attempt_dir.mkdir()
    (attempt_dir / "existing.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        orchestration._prepare_run_output_directory(attempt_dir)


def test_run_from_args_marks_existing_manifest_failed_on_crawl_error(
    tmp_path, monkeypatch
) -> None:
    args = SimpleNamespace(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id="manual__failure",
        airflow_try_number=1,
        output_dir=str(tmp_path),
    )
    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text('{"status":"running"}', encoding="utf-8")

    def fail(_args) -> None:
        raise RuntimeError("crawler failed")

    monkeypatch.setattr(orchestration, "_run_from_args", fail)

    with pytest.raises(RuntimeError, match="crawler failed"):
        orchestration.run_from_args(args)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error"] == "RuntimeError: crawler failed"
    assert manifest["finished_at"]
