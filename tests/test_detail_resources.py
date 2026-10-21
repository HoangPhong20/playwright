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


class FakeClock:
    def __init__(self):
        self.values = {}
        self.lock = threading.Lock()

    def perf_counter(self):
        thread_id = threading.get_ident()
        with self.lock:
            return self.values.get(thread_id, 0.0)

    def advance_current(self, seconds):
        thread_id = threading.get_ident()
        with self.lock:
            self.values[thread_id] = self.values.get(thread_id, 0.0) + seconds


class TimedSlots:
    def __init__(self, clock, waits, acquire_barrier=None):
        self.clock = clock
        self.waits = list(waits)
        self.acquire_barrier = acquire_barrier
        self.acquire_count = 0
        self.release_count = 0
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            assert self.waits, "unexpected global detail slot acquire"
            wait = self.waits.pop(0)
            self.acquire_count += 1
        self.clock.advance_current(wait)
        if self.acquire_barrier is not None:
            self.acquire_barrier.wait(timeout=3)

    def release(self):
        with self.lock:
            self.release_count += 1

    def assert_released(self):
        assert self.release_count == self.acquire_count


def test_enrich_one_record_marks_missing_hotel_url_failed():
    class UnusedPage:
        def goto(self, *_args, **_kwargs):
            pytest.fail("detail navigation must not run without a hotel URL")

    record = {}
    metrics = {}

    detail.enrich_one_record_on_page(
        UnusedPage(),
        record,
        check_in="2026-11-01",
        check_out="2026-11-02",
        adults=2,
        rooms=1,
        children=0,
        index=1,
        total_label="1",
        detail_timeout=1000,
        detail_fields=("price_value",),
        field_retry_timeout=1000,
        field_retry_count=0,
        metrics_outcome=metrics,
    )

    assert record["enrich_status"] == "failed"
    assert "hotel_url" in record["enrich_error"]
    assert metrics == {}
    assert "_detail_load_seconds" not in record
    assert "_detail_extract_seconds" not in record


def timed_slots(monkeypatch, waits, acquire_barrier=None):
    clock = FakeClock()
    monkeypatch.setattr(detail, "time", SimpleNamespace(perf_counter=clock.perf_counter))
    return clock, TimedSlots(clock, waits, acquire_barrier)


class TimedDetailPage:
    def __init__(self, clock, load_times, failed_urls=()):
        self.clock = clock
        self.load_times = dict(load_times)
        self.failed_urls = failed_urls
        self.visited = []

    def goto(self, url, **_):
        self.visited.append(url)
        load_seconds = next(
            seconds for marker, seconds in self.load_times.items() if marker in url
        )
        self.clock.advance_current(load_seconds)
        if any(marker in url for marker in self.failed_urls):
            raise RuntimeError("detail navigation failed")

    def close(self):
        pass


def assert_slot_metrics(metrics, count, wait_sum, wait_max):
    assert metrics["slot_acquire_count"] == count
    assert metrics["slot_wait_seconds_sum"] == wait_sum
    assert metrics["slot_wait_seconds_max"] == wait_max


def enrich_with_metrics(**kwargs):
    try:
        return detail.enrich_records_from_details(**kwargs)
    except TypeError as exc:
        if "metrics_outcome" in str(exc):
            pytest.fail("enrich_records_from_details does not accept metrics_outcome")
        raise


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


def test_serial_detail_slot_metrics_count_one_acquire_for_many_records(monkeypatch):
    resources = BrowserResources()
    context = resources.resource("context")
    _, semaphore = timed_slots(monkeypatch, [0.375])
    processed = []
    metrics = {}

    def process(_, record, *_args):
        processed.append(record["id"])
        record["enrich_status"] = "success"

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    records = [
        {"id": str(index), "hotel_url": f"https://example.test/{index}"}
        for index in range(5)
    ]
    enrich_with_metrics(
        context=context, records=records, check_in="2026-11-01",
        check_out="2026-11-02", adults=2, rooms=1, children=0,
        max_detail_pages=0, detail_concurrency=1, detail_worker_semaphore=semaphore,
        metrics_outcome=metrics,
    )

    assert processed == ["0", "1", "2", "3", "4"]
    assert semaphore.acquire_count == 1
    semaphore.assert_released()
    assert_slot_metrics(metrics, 1, 0.375, 0.375)


def test_detail_slot_metrics_are_zero_without_global_semaphore(monkeypatch):
    context = BrowserResources().resource("context")
    metrics = {}
    records = [
        {"hotel_url": f"https://example.test/{index}"} for index in range(3)
    ]

    def process(_, record, *_args):
        record["enrich_status"] = "success"

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    enrich_with_metrics(
        context=context, records=records, check_in="2026-11-01",
        check_out="2026-11-02", adults=2, rooms=1, children=0,
        max_detail_pages=0, detail_concurrency=1, metrics_outcome=metrics,
    )

    assert_slot_metrics(metrics, 0, 0.0, 0.0)


def test_parallel_detail_slot_metrics_count_each_worker_acquire_once(monkeypatch):
    resources = BrowserResources()
    patch_browser(monkeypatch, resources)
    acquire_barrier = threading.Barrier(2)
    _, semaphore = timed_slots(monkeypatch, [0.125, 0.5], acquire_barrier)
    processed = []
    process_lock = threading.Lock()
    metrics = {}

    def process(_, record, *_args):
        with process_lock:
            processed.append(record["hotel_url"])
        record["enrich_status"] = "success"

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    records = [
        {"hotel_url": f"https://example.test/{index}"} for index in range(4)
    ]
    enrich_with_metrics(
        context=None, records=records, check_in="2026-11-01",
        check_out="2026-11-02", adults=2, rooms=1, children=0,
        max_detail_pages=0, detail_concurrency=2, detail_worker_semaphore=semaphore,
        metrics_outcome=metrics,
    )

    assert len(processed) == 4
    assert semaphore.acquire_count == 2
    semaphore.assert_released()
    assert_slot_metrics(metrics, 2, 0.625, 0.5)


@pytest.mark.parametrize("fault", ["launch", "new_context", "new_page"])
def test_parallel_slot_metrics_survive_browser_context_page_failures(monkeypatch, fault):
    resources = BrowserResources(fault)
    patch_browser(monkeypatch, resources)
    acquire_barrier = threading.Barrier(2)
    _, semaphore = timed_slots(monkeypatch, [0.125, 0.5], acquire_barrier)
    metrics = {}
    records = [
        {"hotel_url": f"https://example.test/{index}"} for index in range(2)
    ]

    with pytest.raises(RuntimeError):
        enrich_with_metrics(
            context=None, records=records, check_in="2026-11-01",
            check_out="2026-11-02", adults=2, rooms=1, children=0,
            max_detail_pages=0, detail_concurrency=2, detail_worker_semaphore=semaphore,
            metrics_outcome=metrics,
        )

    assert semaphore.acquire_count == 2
    semaphore.assert_released()
    assert_slot_metrics(metrics, 2, 0.625, 0.5)
    assert resources.active == 0
    assert sorted(resources.closed) == sorted(resources.created)


@pytest.mark.parametrize("fault", ["new_page", "processing", "page_close"])
def test_serial_detail_releases_global_slot_on_fault(monkeypatch, fault):
    resources = BrowserResources(fault)
    context = resources.resource("context")
    _, semaphore = timed_slots(monkeypatch, [0.125])
    metrics = {}

    def process(*_):
        resources.fail("processing")

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    args = dict(
        context=context, records=[{"hotel_url": "https://example.test/hotel"}],
        check_in="2026-11-01", check_out="2026-11-02", adults=2, rooms=1,
        children=0, max_detail_pages=1, detail_concurrency=1,
        detail_worker_semaphore=semaphore,
        metrics_outcome=metrics,
    )
    if fault == "page_close":
        enrich_with_metrics(**args)
    else:
        with pytest.raises(RuntimeError):
            enrich_with_metrics(**args)

    semaphore.assert_released()
    assert_slot_metrics(metrics, 1, 0.125, 0.125)
    assert resources.closed == ([] if fault == "new_page" else ["page"])


def test_detail_metrics_count_candidates_before_scheduled_limit(monkeypatch):
    records = [
        {"id": "first", "hotel_url": "https://example.test/first"},
        {"id": "second", "hotel_url": "https://example.test/second"},
        {"id": "without-url"},
    ]
    context = SimpleNamespace(new_page=lambda: SimpleNamespace(close=lambda: None))
    processed = []
    metrics = {}

    def process(_, record, *_args):
        processed.append(record["id"])
        record["enrich_status"] = "success"

    monkeypatch.setattr(detail, "enrich_one_record_on_page", process)
    enrich_with_metrics(
        context=context, records=records, check_in="2026-11-01",
        check_out="2026-11-02", adults=2, rooms=1, children=0,
        max_detail_pages=1, detail_concurrency=1, detail_fields=("price_value",),
        metrics_outcome=metrics,
    )

    assert metrics["detail_candidates"] == 2
    assert metrics["detail_scheduled"] == 1
    assert len(processed) == 1
    assert records[2]["enrich_status"] == "skipped"


def test_detail_metrics_empty_job_initializes_zero_counters():
    metrics = {}
    enrich_with_metrics(
        context=None, records=[], check_in="2026-11-01", check_out="2026-11-02",
        adults=2, rooms=1, children=0, max_detail_pages=0, metrics_outcome=metrics,
    )

    assert metrics == {
        "slot_acquire_count": 0,
        "slot_wait_seconds_sum": 0.0,
        "slot_wait_seconds_max": 0.0,
        "detail_candidates": 0,
        "detail_scheduled": 0,
        "detail_attempts": 0,
        "detail_failures": 0,
        "field_retries": 0,
        "detail_missing_target_after_attempt": 0,
        "load_seconds_sum": 0.0,
        "extract_seconds_sum": 0.0,
        "record_seconds_sum": 0.0,
    }


def test_detail_metrics_keep_failed_and_discardable_attempts(monkeypatch):
    clock, _ = timed_slots(monkeypatch, [])
    page = TimedDetailPage(
        clock,
        {"discardable": 0.25, "failed": 0.125},
        failed_urls=("/failed",),
    )
    context = SimpleNamespace(new_page=lambda: page)
    monkeypatch.setattr(detail, "handle_cookie_popup", lambda _: None)

    def extract_fields(_page):
        clock.advance_current(0.5)
        return {"price_value": None}

    monkeypatch.setattr(detail, "extract_detail_fields", extract_fields)
    records = [
        {
            "hotel_url": "https://example.test/discardable",
            "price_value": None,
            "rating_text": "8.5",
            "review_count_text": "100",
            "star_rating_text": "4 stars",
        },
        {
            "hotel_url": "https://example.test/failed",
            "price_value": "1000",
            "rating_text": "8.5",
            "review_count_text": "100",
            "star_rating_text": "4 stars",
        },
    ]
    metrics = {}

    enrich_with_metrics(
        context=context, records=records, check_in="2026-11-01",
        check_out="2026-11-02", adults=2, rooms=1, children=0,
        max_detail_pages=0, detail_concurrency=1, enrich_missing_only=False,
        detail_fields=("price_value",), field_retry_count=0, metrics_outcome=metrics,
    )

    discardable = next(record for record in records if "discardable" in record["hotel_url"])
    failed = next(record for record in records if "failed" in record["hotel_url"])
    assert discardable["enrich_status"] == "success"
    assert discardable["price_value"] is None
    assert failed["enrich_status"] == "failed"
    assert metrics["detail_candidates"] == 2
    assert metrics["detail_scheduled"] == 2
    assert metrics["detail_attempts"] == 2
    assert metrics["detail_failures"] == 1
    assert metrics["field_retries"] == 0
    assert metrics["detail_missing_target_after_attempt"] == 1
    assert metrics["load_seconds_sum"] == 0.375
    assert metrics["extract_seconds_sum"] == 0.5
    assert metrics["record_seconds_sum"] == 0.875


def test_detail_metrics_keep_retry_count_and_time_when_retry_extraction_fails(monkeypatch):
    clock, _ = timed_slots(monkeypatch, [])
    page = TimedDetailPage(clock, {"hotel": 0.125})
    context = SimpleNamespace(new_page=lambda: page)
    monkeypatch.setattr(detail, "handle_cookie_popup", lambda _: None)
    monkeypatch.setattr(detail, "wait_for_any_detail_field", lambda *_: False)

    extract_calls = 0

    def extract_fields(_page):
        nonlocal extract_calls
        extract_calls += 1
        if extract_calls == 1:
            clock.advance_current(0.25)
            return {"price_value": None}
        clock.advance_current(0.5)
        raise RuntimeError("retry extraction failed")

    def scroll_for_retry(*_):
        clock.advance_current(0.375)

    monkeypatch.setattr(detail, "extract_detail_fields", extract_fields)
    monkeypatch.setattr(detail, "scroll_detail_for_fields", scroll_for_retry)
    records = [{"hotel_url": "https://example.test/hotel", "price_value": None}]
    metrics = {}

    enrich_with_metrics(
        context=context, records=records, check_in="2026-11-01",
        check_out="2026-11-02", adults=2, rooms=1, children=0,
        max_detail_pages=0, detail_concurrency=1, detail_fields=("price_value",),
        field_retry_timeout=0, field_retry_count=1, metrics_outcome=metrics,
    )

    assert records[0]["enrich_status"] == "failed"
    assert "_detail_retry_count" not in records[0]
    assert metrics["detail_attempts"] == 1
    assert metrics["detail_failures"] == 1
    assert metrics["field_retries"] == 1
    assert metrics["detail_missing_target_after_attempt"] == 1
    assert metrics["load_seconds_sum"] == 0.125
    assert metrics["extract_seconds_sum"] == 1.125
    assert metrics["record_seconds_sum"] == 1.25


def test_parallel_detail_workers_update_per_job_record_metrics(monkeypatch):
    clock, _ = timed_slots(monkeypatch, [])
    resources = BrowserResources()
    patch_browser(monkeypatch, resources)
    record_barrier = threading.Barrier(2)
    page_ids = []
    page_lock = threading.Lock()

    class ParallelPage:
        def __init__(self):
            self.current_url = ""

        def goto(self, url, **_):
            self.current_url = url
            with page_lock:
                page_ids.append(threading.get_ident())
            record_barrier.wait(timeout=3)
            if "/failed" in url:
                clock.advance_current(0.125)
                raise RuntimeError("detail navigation failed")
            clock.advance_current(0.25)

        def close(self):
            pass

    original_resource = resources.resource

    def create_resource(name):
        if name == "page":
            return ParallelPage()
        return original_resource(name)

    monkeypatch.setattr(resources, "resource", create_resource)
    monkeypatch.setattr(detail, "handle_cookie_popup", lambda _: None)

    def extract_fields(page):
        clock.advance_current(0.5)
        return {"price_value": "1000"}

    monkeypatch.setattr(detail, "extract_detail_fields", extract_fields)
    records = [
        {"hotel_url": f"https://example.test/{marker}", "price_value": None}
        for marker in ("success", "failed")
    ]
    metrics = {
        "detail_candidates": 0,
        "detail_scheduled": 0,
        "detail_attempts": 0,
        "detail_failures": 0,
        "field_retries": 0,
        "detail_missing_target_after_attempt": 0,
        "load_seconds_sum": 0.0,
        "extract_seconds_sum": 0.0,
        "record_seconds_sum": 0.0,
    }

    enrich_with_metrics(
        context=None,
        records=records,
        check_in="2026-11-01",
        check_out="2026-11-02",
        adults=2,
        rooms=1,
        children=0,
        max_detail_pages=0,
        detail_concurrency=2,
        detail_fields=("price_value",),
        field_retry_timeout=0,
        field_retry_count=0,
        metrics_outcome=metrics,
    )

    assert sorted(record["enrich_status"] for record in records) == [
        "failed",
        "success",
    ]
    assert len(set(page_ids)) == 2
    assert metrics == {
        "detail_candidates": 2,
        "detail_scheduled": 2,
        "detail_attempts": 2,
        "detail_failures": 1,
        "field_retries": 0,
        "detail_missing_target_after_attempt": 1,
        "load_seconds_sum": 0.375,
        "extract_seconds_sum": 0.5,
        "record_seconds_sum": 0.875,
        "slot_acquire_count": 0,
        "slot_wait_seconds_sum": 0.0,
        "slot_wait_seconds_max": 0.0,
    }
