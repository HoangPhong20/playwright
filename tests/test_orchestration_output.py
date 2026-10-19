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


@pytest.mark.parametrize("status", ["running", "failed", "complete"])
def test_run_from_args_preserves_existing_attempt_manifest(tmp_path, status) -> None:
    args = SimpleNamespace(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id="manual__failure",
        airflow_try_number=1,
        output_dir=str(tmp_path),
        destinations="Vung Tau",
        destination="Vung Tau",
        date="2026-06-10",
    )
    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    original = json.dumps({"status": status, "sentinel": "preserve"}).encode("utf-8")
    manifest_path.write_bytes(original)

    with pytest.raises(FileExistsError, match="already exists"):
        orchestration.run_from_args(args)

    assert manifest_path.read_bytes() == original


def test_run_from_args_marks_only_its_new_manifest_failed(tmp_path, monkeypatch) -> None:
    args = SimpleNamespace(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id="manual__failure",
        airflow_try_number=1,
        output_dir=str(tmp_path),
        destinations="Vung Tau",
        destination="Vung Tau",
        date="2026-06-10",
        max_pages=5,
    )

    def fail(*_args) -> None:
        raise RuntimeError("crawler failed")

    monkeypatch.setattr(orchestration, "_run_created_attempt", fail)

    with pytest.raises(RuntimeError, match="crawler failed"):
        orchestration.run_from_args(args)

    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error"] == "RuntimeError: crawler failed"
    assert manifest["finished_at"]
    assert manifest["jobs"][0]["status"] == "failed"


@pytest.mark.parametrize(
    "job_status, stop_reason",
    [("incomplete", "low_new_records"), ("failed", "pagination_navigation_failed")],
)
def test_incomplete_job_cannot_publish_completed_attempt(
    tmp_path, monkeypatch, job_status, stop_reason
) -> None:
    args = SimpleNamespace(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id="manual__partial",
        airflow_try_number=1,
        output_dir=str(tmp_path),
        destinations="Vung Tau",
        destination="Vung Tau",
        date="2026-06-10",
        max_pages=5,
        detail_fields="price_value",
        total_detail_concurrency=1,
        workers=1,
        headless=True,
        max_scroll_rounds=2,
        stable_rounds=1,
        scroll_wait_ms=0,
        detail_timeout=1000,
        field_retry_timeout=0,
        field_retry_count=0,
        detail_concurrency=1,
        max_detail_pages=1,
        enrich_details=False,
        enrich_missing_only=True,
        print_records=False,
    )
    partial_record = {
        "hotel_name": "Partial result",
        "hotel_url": "https://www.agoda.com/partial/hotel/demo.html",
        "price_value": "1000000",
        "destination": "Vung Tau",
        "check_in": "2026-06-10",
    }

    def return_partial(jobs, *_args):
        return [
            orchestration.CrawlJobResult(
                job=jobs[0],
                records=[partial_record],
                pagination={
                    "pages_requested": 5,
                    "pages_collected": 2,
                    "status": job_status,
                    "stop_reason": stop_reason,
                    "page_statuses": {"1": "collected", "2": "collected"},
                },
            )
        ]

    monkeypatch.setattr(orchestration, "run_crawl_jobs_for_stay", return_partial)
    monkeypatch.setattr(orchestration, "write_latest_outputs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(orchestration, "summarize", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        orchestration, "print_verification_summary", lambda *_args, **_kwargs: None
    )

    with pytest.raises(RuntimeError, match="Crawl jobs did not complete"):
        orchestration.run_from_args(args)

    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["jobs"][0]["pages_collected"] == 2
    assert manifest["jobs"][0]["status"] == job_status
    assert manifest["jobs"][0]["stop_reason"] == stop_reason
    assert not context.completion_pointer_path(tmp_path).exists()
