"""Faults use real worker/serial control flow with bounded synchronization."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import threading
from types import SimpleNamespace

import pytest

from agoda_crawler.enrichment import detail


class BoundedSlots:
    def __init__(self, capacity):
        self.semaphore = threading.BoundedSemaphore(capacity)
        self.waiting = threading.Event()

    def acquire(self):
        self.waiting.set()
        assert self.semaphore.acquire(timeout=3), "global detail slot was not released"

    def release(self):
        self.semaphore.release()

    def assert_available(self):
        assert self.semaphore.acquire(blocking=False), "global detail slot leaked"
        self.semaphore.release()


class BrowserResources:
    def __init__(self, fault=None):
        self.fault = fault
        self.created = []
        self.closed = []
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def fail(self, stage):
        if self.fault == stage:
            raise RuntimeError()

    def playwright(self):
        resources = self

        class Playwright:
            chromium = resources

            def __enter__(self):
                resources.fail("playwright_enter")
                return self

            def __exit__(self, *_):
                resources.fail("playwright_exit")

        return Playwright()

    def launch(self, **_):
        self.fail("launch")
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        return self.resource("browser")

    def resource(self, name):
        self.created.append(name)

        def close():
            self.closed.append(name)
            if name == "browser":
                with self.lock:
                    self.active -= 1
            self.fail(name + "_close")

        def new_context(**_):
            self.fail("new_context")
            return self.resource("context")

        def new_page():
            self.fail("new_page")
            return self.resource("page")

        return SimpleNamespace(close=close, new_context=new_context, new_page=new_page)


def worker(records, semaphore):
    queue = Queue()
    for record in records:
        queue.put(record)
    progress = {
        "started": 0, "completed": 0, "failed": 0, "total": len(records),
        "started_at": detail.time.perf_counter(), "last_log_at": detail.time.perf_counter(),
        "load_seconds": [], "extract_seconds": [], "total_seconds": [], "retry_count": 0,
    }
    detail.enrich_detail_record_queue(
        queue, "2026-11-01", "2026-11-02", 2, 1, 0, str(len(records)),
        progress, threading.Lock(), True, "vi-vn", 100, "",
        ("price_value",), 0, 0, semaphore,
    )
    return progress


def patch_browser(monkeypatch, resources):
    monkeypatch.setattr(detail, "sync_playwright", resources.playwright)

    def blocking(_):
        resources.fail("routing")

    monkeypatch.setattr(detail, "apply_resource_blocking", blocking)


@pytest.mark.parametrize("fault", [
    "playwright_enter", "launch", "new_context", "routing", "new_page", "processing",
    "page_close", "context_close", "browser_close", "playwright_exit",
])
def test_detail_worker_releases_slot_and_created_resources_on_fault(monkeypatch, fault):
    resources = BrowserResources(fault)
    patch_browser(monkeypatch, resources)
    semaphore = BoundedSlots(1)

    def process(_, record, *_args):
        resources.fail("processing")
        record["enrich_status"] = "success"

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    if fault.endswith("_close"):
        progress = worker([{}], semaphore)
        assert progress["completed"] == 1
    else:
        with pytest.raises(RuntimeError):
            worker([{}], semaphore)

    semaphore.assert_available()
    assert resources.closed == list(reversed(resources.created))
    assert resources.active == 0


def test_detail_processing_error_survives_empty_cleanup_errors(monkeypatch):
    resources = BrowserResources()
    patch_browser(monkeypatch, resources)
    semaphore = BoundedSlots(1)

    def fail(stage):
        if stage.endswith("_close"):
            raise ValueError()

    resources.fail = fail

    def process(*_):
        raise RuntimeError("original processing error")

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    with pytest.raises(RuntimeError, match="original processing error"):
        worker([{}], semaphore)

    semaphore.assert_available()
    assert resources.closed == ["page", "context", "browser"]


def test_shared_global_cap_applies_across_detail_jobs(monkeypatch):
    resources = BrowserResources()
    patch_browser(monkeypatch, resources)
    semaphore = BoundedSlots(1)
    first_processing = threading.Event()
    release_processing = threading.Event()
    processed = []

    def process(_, record, *_args):
        if record["id"] == "first":
            first_processing.set()
            assert release_processing.wait(timeout=3), "test did not release first worker"
        processed.append(record["id"])
        record["enrich_status"] = "success"

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(worker, [{"id": "first"}], semaphore)
        try:
            assert first_processing.wait(timeout=3), "first worker did not start"
            semaphore.waiting.clear()
            second = executor.submit(worker, [{"id": "second"}], semaphore)
            assert semaphore.waiting.wait(timeout=3), "second worker did not request a slot"
            assert resources.active == 1
        finally:
            release_processing.set()
        assert first.result(timeout=5)["completed"] == 1
        assert second.result(timeout=5)["completed"] == 1

    assert resources.peak == 1
    assert resources.active == 0
    assert processed == ["first", "second"]
    semaphore.assert_available()


def test_parallel_entrypoint_shares_global_cap_across_jobs(monkeypatch):
    resources = BrowserResources()
    patch_browser(monkeypatch, resources)
    semaphore = BoundedSlots(1)
    entered = threading.Event()
    finish = threading.Event()
    processed = []

    def process(_, record, *_args):
        entered.set()
        assert finish.wait(timeout=3), "test did not release detail processing"
        processed.append(record["hotel_url"])
        record["enrich_status"] = "success"

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)

    def run_job(job):
        records = [{"hotel_url": f"https://example.test/{job}/{index}"} for index in range(2)]
        detail.enrich_records_from_details(
            None, records, "2026-11-01", "2026-11-02", 2, 1, 0,
            max_detail_pages=0, detail_concurrency=2, detail_worker_semaphore=semaphore,
        )
        return records

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_job, "one")
        try:
            assert entered.wait(timeout=3), "parallel detail worker did not start"
            second = executor.submit(run_job, "two")
        finally:
            finish.set()
        results = first.result(timeout=5) + second.result(timeout=5)

    assert len(processed) == 4
    assert all(record["enrich_status"] == "success" for record in results)
    assert resources.peak == 1
    assert resources.active == 0
    semaphore.assert_available()


@pytest.mark.parametrize("fault", ["new_page", "processing", "page_close"])
def test_serial_detail_releases_global_slot_on_fault(monkeypatch, fault):
    resources = BrowserResources(fault)
    context = resources.resource("context")
    semaphore = BoundedSlots(1)

    def process(*_):
        resources.fail("processing")

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    args = dict(
        context=context, records=[{"hotel_url": "https://example.test/hotel"}],
        check_in="2026-11-01", check_out="2026-11-02", adults=2, rooms=1,
        children=0, max_detail_pages=1, detail_concurrency=1,
        detail_worker_semaphore=semaphore,
    )
    if fault == "page_close":
        detail.enrich_records_from_details(**args)
    else:
        with pytest.raises(RuntimeError):
            detail.enrich_records_from_details(**args)

    semaphore.assert_available()
    assert resources.closed == ([] if fault == "new_page" else ["page"])
