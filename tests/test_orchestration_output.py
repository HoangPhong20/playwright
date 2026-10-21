import json
import threading
from types import SimpleNamespace

import pytest

from agoda_crawler import orchestration
from agoda_crawler.run_context import RunContext


def _run_args(tmp_path, run_id: str, destinations: str, workers: int) -> SimpleNamespace:
    return SimpleNamespace(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id=run_id,
        airflow_try_number=1,
        output_dir=str(tmp_path),
        destinations=destinations,
        destination=destinations.split(",")[0],
        date="2026-06-10",
        max_pages=1,
        detail_fields="price_value",
        total_detail_concurrency=2,
        workers=workers,
        headless=True,
        max_scroll_rounds=1,
        stable_rounds=1,
        scroll_wait_ms=0,
        detail_timeout=1000,
        field_retry_timeout=0,
        field_retry_count=0,
        detail_concurrency=1,
        max_detail_pages=0,
        enrich_details=False,
        enrich_missing_only=True,
        print_records=False,
        adults=2,
        rooms=1,
        children=0,
        locale="en-us",
    )


def test_parallel_jobs_keep_independent_metrics_on_results(tmp_path, monkeypatch) -> None:
    jobs = [
        orchestration.CrawlJob("Vung Tau", "2026-06-10", "2026-06-11", tmp_path / "a.jsonl"),
        orchestration.CrawlJob("Da Nang", "2026-06-10", "2026-06-11", tmp_path / "b.jsonl"),
    ]
    barrier = threading.Barrier(2)
    observed_metrics = {}
    version_counter = iter(("141.0.worker-one", "142.0.worker-two"))
    version_lock = threading.Lock()

    class Browser:
        def __init__(self) -> None:
            with version_lock:
                self.version = next(version_counter)

        def close(self) -> None:
            pass

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **_kwargs: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

    args = SimpleNamespace(
        headless=True,
        max_pages=1,
        adults=2,
        rooms=1,
        children=0,
        locale="en-us",
        enrich_details=False,
        max_detail_pages=0,
        detail_concurrency=1,
        enrich_missing_only=True,
        detail_timeout=1000,
        field_retry_timeout=0,
        field_retry_count=0,
        max_scroll_rounds=1,
        stable_rounds=1,
        scroll_wait_ms=0,
        print_records=False,
    )

    def crawl(_browser, **kwargs):
        destination = kwargs["destination"]
        metrics = kwargs.get("metrics_outcome")
        observed_metrics[destination] = metrics
        barrier.wait(timeout=2)
        if metrics is not None:
            metrics["detail_attempts"] = 1 if destination == "Vung Tau" else 2
        return []

    monkeypatch.setattr(orchestration, "sync_playwright", lambda: Playwright())
    monkeypatch.setattr(orchestration, "crawl_agoda_search_with_browser", crawl)
    monkeypatch.setattr(orchestration, "write_crawl_results", lambda _results: None)
    browser_metadata = {
        "actual_version": None,
        "actual_version_status": "not_launched",
    }

    results = orchestration.run_crawl_jobs_for_stay(
        jobs,
        args,
        worker_count=2,
        run_context=RunContext("dag", "run", 1),
        detail_worker_semaphore=threading.BoundedSemaphore(1),
        detail_fields=("price_value",),
        browser_metadata=browser_metadata,
    )

    assert observed_metrics["Vung Tau"] is not None
    assert observed_metrics["Da Nang"] is not None
    assert observed_metrics["Vung Tau"] is not observed_metrics["Da Nang"]
    assert [result.metrics["detail_attempts"] for result in results] == [1, 2]
    assert browser_metadata["observed_versions"] == [
        "141.0.worker-one",
        "142.0.worker-two",
    ]
    assert browser_metadata["actual_version"] is None
    assert browser_metadata["actual_version_status"] == "inconsistent"
    assert all("actual_version" not in result.metrics for result in results)


def test_browser_metadata_failure_still_closes_launched_browser(
    tmp_path, monkeypatch
) -> None:
    closed = []

    class Browser:
        def close(self) -> None:
            closed.append(True)

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **_kwargs: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            pass

    def fail_metadata(*_args) -> None:
        raise RuntimeError("metadata capture failed")

    monkeypatch.setattr(orchestration, "sync_playwright", lambda: Playwright())
    monkeypatch.setattr(orchestration._provenance, "record_browser_version", fail_metadata)

    with pytest.raises(RuntimeError, match="metadata capture failed"):
        orchestration.run_crawl_job_batch(
            [
                orchestration.CrawlJob(
                    "Vung Tau", "2026-06-10", "2026-06-11", tmp_path / "a.jsonl"
                )
            ],
            SimpleNamespace(headless=True),
            RunContext("dag", "run", 1),
            threading.BoundedSemaphore(1),
            ("price_value",),
            {"actual_version": None, "actual_version_status": "not_launched"},
        )

    assert closed == [True]


def test_new_manifest_captures_additive_provenance_once_and_keeps_git_revision(
    tmp_path, monkeypatch
) -> None:
    args = SimpleNamespace(max_pages=1, output_dir=str(tmp_path))
    run_context = RunContext("dag", "run", 1)
    captured = []

    def capture(*args, **kwargs):
        captured.append((args, kwargs))
        return {"fingerprint": "source-and-config"}

    monkeypatch.setattr(orchestration._provenance, "capture_run_provenance", capture)
    monkeypatch.setattr(orchestration, "_git_revision", lambda: "legacy-commit-sha")

    manifest = orchestration._new_run_manifest(
        run_context,
        args,
        ["Vung Tau"],
        [("2026-06-10", "2026-06-11")],
        [],
    )

    assert len(captured) == 1
    assert captured[0][0][0] is args
    assert captured[0][1]["captured_at"] == manifest["started_at"]
    assert manifest["provenance"] == {"fingerprint": "source-and-config"}
    assert manifest["git_revision"] == "legacy-commit-sha"


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
                metrics={
                    "detail_candidates": 4,
                    "detail_attempts": 2,
                    "detail_failures": 1,
                    "job_wall_seconds": 5.0,
                    "scroll_rounds_max": 3,
                    "slot_wait_seconds_max": 0.25,
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
    assert manifest["jobs"][0]["metrics"]["detail_candidates"] == 4
    assert manifest["stays"][0]["metrics"]["detail_failures"] == 1
    assert manifest["summary"]["detail_candidates"] == 4
    assert manifest["summary"]["batch_wall_seconds"] >= 0
    assert not context.completion_pointer_path(tmp_path).exists()


def test_batch_manifest_metrics_include_output_work_and_sum_job_metrics(
    tmp_path, monkeypatch, capsys
) -> None:
    class Clock:
        def __init__(self):
            self.now = 0.0

        def perf_counter(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(
        orchestration, "time", SimpleNamespace(perf_counter=clock.perf_counter)
    )
    run_context = RunContext("agoda_daily_crawl", "manual__metrics", 1)
    run_output_dir = run_context.output_directory(tmp_path)
    run_output_dir.mkdir(parents=True)
    output_path = run_output_dir / "agoda_hotels_2026-06-10.jsonl"
    jobs = [
        orchestration.CrawlJob("Vung Tau", "2026-06-10", "2026-06-11", output_path),
        orchestration.CrawlJob("Da Nang", "2026-06-10", "2026-06-11", output_path),
    ]
    args = SimpleNamespace(
        output_dir=str(tmp_path),
        max_pages=1,
        detail_fields="price_value",
        total_detail_concurrency=2,
        workers=2,
        headless=True,
        max_scroll_rounds=1,
        stable_rounds=1,
        scroll_wait_ms=0,
        detail_timeout=1000,
        field_retry_timeout=0,
        field_retry_count=0,
        detail_concurrency=1,
        max_detail_pages=0,
        enrich_details=False,
        enrich_missing_only=True,
        print_records=False,
    )
    destinations = ["Vung Tau", "Da Nang"]
    stays = [("2026-06-10", "2026-06-11")]
    manifest = orchestration._new_run_manifest(
        run_context, args, destinations, stays, jobs
    )
    manifest_path = run_output_dir / "run_manifest.json"
    orchestration._write_run_manifest(manifest_path, manifest)
    jobs_metrics = [
        {
            "job_wall_seconds": 100.0,
            "search_wall_seconds": 2.0,
            "regular_snapshot_count": 2,
            "scroll_rounds_total": 3,
            "scroll_rounds_max": 2,
            "slot_acquire_count": 1,
            "slot_wait_seconds_sum": 0.2,
            "slot_wait_seconds_max": 0.2,
            "detail_candidates": 5,
        },
        {
            "job_wall_seconds": 200.0,
            "search_wall_seconds": 1.0,
            "regular_snapshot_count": 1,
            "scroll_rounds_total": 2,
            "scroll_rounds_max": 4,
            "slot_acquire_count": 2,
            "slot_wait_seconds_sum": 0.8,
            "slot_wait_seconds_max": 0.5,
            "detail_candidates": 4,
        },
    ]

    def fake_crawl_jobs(jobs, *_args):
        clock.advance(0.6)
        return [
            orchestration.CrawlJobResult(
                job=job,
                records=[],
                pagination={
                    "pages_requested": 1,
                    "pages_collected": 1,
                    "status": "complete",
                    "stop_reason": "max_pages_reached",
                },
                metrics=metrics,
            )
            for job, metrics in zip(jobs, jobs_metrics)
        ]

    real_write_manifest = orchestration._write_run_manifest
    intermediate_writes = 0

    def fake_write_manifest(path, value):
        nonlocal intermediate_writes
        if value["status"] == "complete":
            clock.advance(10.0)
        else:
            intermediate_writes += 1
            clock.advance(0.1)
        real_write_manifest(path, value)

    monkeypatch.setattr(orchestration, "run_crawl_jobs_for_stay", fake_crawl_jobs)
    monkeypatch.setattr(
        orchestration,
        "write_latest_outputs",
        lambda *_args, **_kwargs: clock.advance(0.4),
    )
    monkeypatch.setattr(
        orchestration, "summarize", lambda *_args, **_kwargs: clock.advance(0.2)
    )
    monkeypatch.setattr(orchestration, "_write_run_manifest", fake_write_manifest)
    monkeypatch.setattr(
        orchestration,
        "_write_completed_attempt_pointer",
        lambda *_args: clock.advance(20.0),
    )

    orchestration._run_created_attempt(
        args,
        destinations,
        stays,
        run_context,
        run_output_dir,
        jobs,
        manifest_path,
        manifest,
    )

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    summary = saved["summary"]
    assert intermediate_writes == 2
    assert summary["batch_wall_seconds"] == pytest.approx(1.4)
    assert summary["batch_wall_seconds"] != sum(
        metrics["job_wall_seconds"] for metrics in jobs_metrics
    )
    assert summary["job_wall_seconds"] == 300.0
    assert summary["search_wall_seconds"] == 3.0
    assert summary["regular_snapshot_count"] == 3
    assert summary["scroll_rounds_total"] == 5
    assert summary["scroll_rounds_max"] == 4
    assert summary["slot_acquire_count"] == 3
    assert summary["slot_wait_seconds_sum"] == pytest.approx(1.0)
    assert summary["slot_wait_seconds_max"] == 0.5
    assert summary["detail_candidates"] == 9
    assert saved["jobs"][0]["metrics"] == jobs_metrics[0]
    assert saved["stays"][0]["metrics"]["detail_candidates"] == 9
    output = capsys.readouterr().out
    assert "VERIFY_DETAIL_ATTEMPTED=0" in output
    assert "VERIFY_DETAIL_CANDIDATES_ALL=9" in output


def test_failed_latest_output_work_is_persisted_in_failed_batch_metrics(
    tmp_path, monkeypatch
) -> None:
    class Clock:
        def __init__(self):
            self.now = 0.0

        def perf_counter(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(
        orchestration, "time", SimpleNamespace(perf_counter=clock.perf_counter)
    )
    args = SimpleNamespace(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id="manual__output_failure",
        airflow_try_number=1,
        output_dir=str(tmp_path),
        destinations="Vung Tau",
        destination="Vung Tau",
        date="2026-06-10",
        max_pages=1,
        detail_fields="price_value",
        total_detail_concurrency=1,
        workers=1,
        headless=True,
        max_scroll_rounds=1,
        stable_rounds=1,
        scroll_wait_ms=0,
        detail_timeout=1000,
        field_retry_timeout=0,
        field_retry_count=0,
        detail_concurrency=1,
        max_detail_pages=0,
        enrich_details=False,
        enrich_missing_only=True,
        print_records=False,
        adults=2,
        rooms=1,
        children=0,
        locale="en-us",
    )

    def fake_crawl_jobs(jobs, *_args):
        clock.advance(0.3)
        return [
            orchestration.CrawlJobResult(
                job=jobs[0],
                records=[],
                pagination={
                    "pages_requested": 1,
                    "pages_collected": 1,
                    "status": "complete",
                    "stop_reason": "max_pages_reached",
                },
                metrics={"job_wall_seconds": 0.25, "detail_attempts": 1},
            )
        ]

    def fail_latest_output(*_args, **_kwargs):
        clock.advance(0.4)
        raise RuntimeError("latest output failed")

    monkeypatch.setattr(orchestration, "run_crawl_jobs_for_stay", fake_crawl_jobs)
    monkeypatch.setattr(orchestration, "write_latest_outputs", fail_latest_output)

    with pytest.raises(RuntimeError, match="latest output failed"):
        orchestration.run_from_args(args)

    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error"] == "RuntimeError: latest output failed"
    assert manifest["summary"]["batch_wall_seconds"] == pytest.approx(0.7)
    assert not context.completion_pointer_path(tmp_path).exists()


def test_failed_stay_execution_time_is_persisted_in_failed_batch_metrics(
    tmp_path, monkeypatch
) -> None:
    class Clock:
        def __init__(self):
            self.now = 0.0

        def perf_counter(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(
        orchestration, "time", SimpleNamespace(perf_counter=clock.perf_counter)
    )
    args = SimpleNamespace(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id="manual__stay_failure",
        airflow_try_number=1,
        output_dir=str(tmp_path),
        destinations="Vung Tau",
        destination="Vung Tau",
        date="2026-06-10",
        max_pages=1,
        detail_fields="price_value",
        total_detail_concurrency=1,
        workers=1,
        headless=True,
        max_scroll_rounds=1,
        stable_rounds=1,
        scroll_wait_ms=0,
        detail_timeout=1000,
        field_retry_timeout=0,
        field_retry_count=0,
        detail_concurrency=1,
        max_detail_pages=0,
        enrich_details=False,
        enrich_missing_only=True,
        print_records=False,
    )

    def fail_stay(*_args):
        clock.advance(0.4)
        raise RuntimeError("stay execution failed")

    monkeypatch.setattr(orchestration, "run_crawl_jobs_for_stay", fail_stay)

    with pytest.raises(RuntimeError, match="stay execution failed"):
        orchestration.run_from_args(args)

    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error"] == "RuntimeError: stay execution failed"
    assert manifest["summary"]["batch_wall_seconds"] == pytest.approx(0.4)
    assert not context.completion_pointer_path(tmp_path).exists()


def test_failed_job_result_write_preserves_worker_metrics(tmp_path, monkeypatch) -> None:
    class Clock:
        def __init__(self):
            self.now = 0.0

        def perf_counter(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    clock = Clock()
    monkeypatch.setattr(
        orchestration, "time", SimpleNamespace(perf_counter=clock.perf_counter)
    )
    args = SimpleNamespace(
        airflow_dag_id="agoda_daily_crawl",
        airflow_run_id="manual__job_write_failure",
        airflow_try_number=1,
        output_dir=str(tmp_path),
        destinations="Vung Tau",
        destination="Vung Tau",
        date="2026-06-10",
        max_pages=1,
        detail_fields="price_value",
        total_detail_concurrency=1,
        workers=1,
        headless=True,
        max_scroll_rounds=1,
        stable_rounds=1,
        scroll_wait_ms=0,
        detail_timeout=1000,
        field_retry_timeout=0,
        field_retry_count=0,
        detail_concurrency=1,
        max_detail_pages=0,
        enrich_details=False,
        enrich_missing_only=True,
        print_records=False,
    )
    observed_metrics = {
        "job_wall_seconds": 1.5,
        "detail_candidates": 3,
        "detail_attempts": 2,
    }

    def fake_job_batch(jobs, *_args):
        clock.advance(0.3)
        return [
            orchestration.CrawlJobResult(
                job=jobs[0],
                records=[],
                pagination={
                    "pages_requested": 1,
                    "pages_collected": 1,
                    "status": "complete",
                    "stop_reason": "max_pages_reached",
                },
                metrics=dict(observed_metrics),
            )
        ]

    def fail_result_write(_results):
        clock.advance(0.4)
        raise RuntimeError("job result write failed")

    monkeypatch.setattr(orchestration, "run_crawl_job_batch", fake_job_batch)
    monkeypatch.setattr(orchestration, "write_crawl_results", fail_result_write)

    with pytest.raises(RuntimeError, match="job result write failed"):
        orchestration.run_from_args(args)

    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error"] == "RuntimeError: job result write failed"
    assert manifest["jobs"][0]["metrics"] == observed_metrics
    assert manifest["summary"]["detail_candidates"] == 3
    assert manifest["summary"]["batch_wall_seconds"] == pytest.approx(0.7)
    assert not context.completion_pointer_path(tmp_path).exists()


def test_serial_browser_close_failure_keeps_completed_job_metrics(
    tmp_path, monkeypatch
) -> None:
    args = _run_args(tmp_path, "manual__browser_close_failure", "Vung Tau", 1)
    observed_metrics = {"job_wall_seconds": 1.25, "detail_attempts": 2}

    class Browser:
        version = "142.0.test"

        def new_context(self, **_kwargs):
            return object()

        def close(self):
            raise RuntimeError("browser close failed")

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **_kwargs: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    def crawl(_browser, **kwargs):
        kwargs["metrics_outcome"].update(observed_metrics)
        kwargs["pagination_outcome"].update(
            pages_requested=1,
            pages_collected=1,
            status="complete",
            stop_reason="max_pages_reached",
        )
        return []

    monkeypatch.setattr(orchestration, "sync_playwright", Playwright)
    monkeypatch.setattr(orchestration, "crawl_agoda_search_with_browser", crawl)

    with pytest.raises(RuntimeError, match="browser close failed"):
        orchestration.run_from_args(args)

    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["jobs"][0]["status"] == "complete"
    assert manifest["jobs"][0]["metrics"] == observed_metrics
    assert manifest["summary"]["detail_attempts"] == 2
    assert not context.completion_pointer_path(tmp_path).exists()


def test_parallel_worker_launch_failure_keeps_completed_sibling_metrics(
    tmp_path, monkeypatch
) -> None:
    args = _run_args(
        tmp_path,
        "manual__worker_launch_failure",
        "Vung Tau,Da Nang",
        2,
    )
    release_healthy_worker = threading.Event()

    def fake_batch(jobs, *batch_args, **_kwargs):
        job = jobs[0]
        if job.destination == "Vung Tau":
            raise RuntimeError("worker browser launch failed")
        assert job.destination == "Da Nang"
        assert release_healthy_worker.wait(timeout=2)
        result = orchestration.CrawlJobResult(
            job=job,
            records=[],
            pagination={
                "pages_requested": 1,
                "pages_collected": 1,
                "status": "complete",
                "stop_reason": "max_pages_reached",
            },
            metrics={"job_wall_seconds": 0.8, "detail_attempts": 3},
        )
        batch_args[-1].append(result)
        return [result]

    def failed_future_first(futures):
        failed_future, healthy_future = list(futures)
        with pytest.raises(RuntimeError, match="worker browser launch failed"):
            failed_future.result(timeout=2)
        release_healthy_worker.set()
        yield failed_future
        healthy_future.result(timeout=2)
        yield healthy_future

    monkeypatch.setattr(orchestration, "run_crawl_job_batch", fake_batch)
    monkeypatch.setattr(orchestration, "as_completed", failed_future_first)

    with pytest.raises(RuntimeError, match="worker browser launch failed"):
        orchestration.run_from_args(args)

    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    failed_outcome, healthy_outcome = manifest["jobs"]
    assert failed_outcome["status"] == "failed"
    assert failed_outcome["metrics"] == {}
    assert healthy_outcome["status"] == "complete"
    assert healthy_outcome["metrics"] == {
        "job_wall_seconds": 0.8,
        "detail_attempts": 3,
    }
    assert manifest["summary"]["detail_attempts"] == 3
    assert not context.completion_pointer_path(tmp_path).exists()


def test_batch_preserves_worker_error_when_browser_and_playwright_cleanup_fail(
    tmp_path, monkeypatch
) -> None:
    args = _run_args(tmp_path, "manual__cleanup_failure", "Vung Tau", 1)
    observed_metrics = {"job_wall_seconds": 0.7, "detail_attempts": 4}

    class Browser:
        def close(self):
            raise RuntimeError("browser cleanup failed")

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **_kwargs: Browser())

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            raise RuntimeError("playwright cleanup failed")

    def return_record(_browser, **kwargs):
        kwargs["metrics_outcome"].update(observed_metrics)
        kwargs["pagination_outcome"].update(
            pages_requested=1,
            pages_collected=1,
            status="complete",
            stop_reason="max_pages_reached",
        )
        return [{}]

    def fail_annotation(*_args, **_kwargs):
        raise RuntimeError("worker annotation failed")

    monkeypatch.setattr(orchestration, "sync_playwright", Playwright)
    monkeypatch.setattr(
        orchestration, "crawl_agoda_search_with_browser", return_record
    )
    monkeypatch.setattr(orchestration, "annotate_record", fail_annotation)

    with pytest.raises(RuntimeError, match="worker annotation failed"):
        orchestration.run_from_args(args)

    context = RunContext(args.airflow_dag_id, args.airflow_run_id, 1)
    manifest_path = context.output_directory(tmp_path) / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    job = manifest["jobs"][0]
    assert manifest["status"] == "failed"
    assert job["status"] == "failed"
    assert job["stop_reason"] == "crawl_error"
    assert job["metrics"] == observed_metrics
    assert manifest["summary"]["detail_attempts"] == 4
    assert manifest["error"] == "RuntimeError: worker annotation failed"
    assert not context.completion_pointer_path(tmp_path).exists()
