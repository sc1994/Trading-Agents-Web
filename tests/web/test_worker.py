import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest

from web.store import Store
from web.worker import TaskWorker


class RecordingRunner:
    """Gate real worker execution at the external graph boundary."""

    def __init__(self, *, block_first=False, error=None, decision=True, resumable=True):
        self.first_started = Event()
        self.second_started = Event()
        self.release = Event()
        if not block_first:
            self.release.set()
        self.error = error
        self.decision = decision
        self.resumable = resumable
        self.calls = []

    def can_resume(self, task):
        return self.resumable

    def run(self, task, emit, *, resume=False):
        self.calls.append((task, resume))
        emit("section", {"section": "market_report", "text": "Partial market evidence"})
        if len(self.calls) == 1:
            self.first_started.set()
            if not self.release.wait(5):
                raise TimeoutError("Test runner was not released")
            if self.error:
                raise self.error
        else:
            self.second_started.set()
        if self.decision:
            emit("section", {"section": "decision", "text": "**Rating**: [REDACTED]"})
        return {"final_trade_decision": "**Rating**: Overweight secret-raw-key"}, "Overweight"


def await_status(store, task_id, status):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        task = store.get_task(task_id)
        if task["status"] == status:
            return task
        Event().wait(0.01)
    pytest.fail(f"Task did not reach {status}: {store.get_task(task_id)}")


def test_worker_serializes_and_persists_safe_decision_before_notification(tmp_path):
    store = Store(tmp_path / "web.db")
    first = store.create_task({"ticker": "NVDA", "date": "2026-09-22"})
    second = store.create_task({"ticker": "AAPL", "date": "2026-09-22"})
    runner = RecordingRunner(block_first=True)

    class ObservingWorker(TaskWorker):
        def notify(self, task_id):
            snapshot = store.get_task(task_id)
            events = store.events_after(task_id, 0)
            observations.append((snapshot, events))
            super().notify(task_id)

    observations = []
    worker = ObservingWorker(store, runner)
    worker.start()
    try:
        assert runner.first_started.wait(5)
        worker.start()  # Repeated start must not interrupt an active task.
        assert store.get_task(first)["status"] == "running"
        assert store.get_task(first)["sections"] == {"market_report": "Partial market evidence"}
        assert store.get_task(second)["status"] == "queued"
        assert store.delete_task(first) is False
        runner.release.set()
        assert runner.second_started.wait(5)
        await_status(store, second, "completed")
    finally:
        runner.release.set()
        worker.stop()
    task = store.get_task(first)
    assert task["decision"] == "**Rating**: [REDACTED]"
    assert task["rating"] == "Overweight"  # Never reparse the redacted Markdown.
    assert "secret-raw-key" not in json.dumps(store.list_tasks() + store.events_after(first, 0))
    completed = [(task, events) for task, events in observations if events[-1]["kind"] == "completed"]
    assert len(completed) == 2
    for snapshot, events in completed:
        assert snapshot["status"] == "completed"
        assert snapshot["sections"]["decision"] == snapshot["decision"]
        assert events[-1]["payload"]["rating"] == "Overweight"


@pytest.mark.parametrize("error", [RuntimeError("secret-provider-key"), TimeoutError("secret-url")])
def test_failure_preserves_partial_reports_hides_exception_and_continues(tmp_path, error):
    store = Store(tmp_path / "web.db")
    first = store.create_task({"ticker": "NVDA"})
    second = store.create_task({"ticker": "AAPL"})
    worker = TaskWorker(store, RecordingRunner(error=error))
    worker.start()
    try:
        task = await_status(store, first, "failed")
        await_status(store, second, "completed")
    finally:
        worker.stop()
    assert task["sections"] == {"market_report": "Partial market evidence"}
    assert task["rating"] is None
    assert task["decision"] is None
    assert task["error"]
    events = store.events_after(first, 0)
    assert events[-1]["kind"] == "failed"
    assert "secret" not in json.dumps([task, events])


def test_missing_safe_decision_fails_without_raw_fallback(tmp_path):
    store = Store(tmp_path / "web.db")
    task_id = store.create_task({"ticker": "NVDA"})
    worker = TaskWorker(store, RecordingRunner(decision=False))
    worker.start()
    try:
        task = await_status(store, task_id, "failed")
    finally:
        worker.stop()
    assert task["rating"] is None
    assert "secret-raw-key" not in json.dumps([task, store.events_after(task_id, 0)])


def test_startup_interrupts_abandoned_run_and_processes_queue(tmp_path):
    store = Store(tmp_path / "web.db")
    abandoned = store.create_task({"ticker": "NVDA"})
    store.claim_next()
    store.save_section(abandoned, "market_report", "Saved before restart")
    queued = store.create_task({"ticker": "AAPL"})
    worker = TaskWorker(Store(store.path), RecordingRunner())
    worker.start()
    try:
        await_status(store, queued, "completed")
    finally:
        worker.stop()
    task = store.get_task(abandoned)
    assert task["status"] == "interrupted"
    assert task["sections"] == {"market_report": "Saved before restart"}
    assert store.events_after(abandoned, 0)[-1]["kind"] == "interrupted"


@pytest.mark.parametrize("status,resumable", [("queued", True), ("interrupted", False)])
def test_resume_rejects_wrong_state_or_missing_checkpoint(tmp_path, status, resumable):
    store = Store(tmp_path / "web.db")
    task_id = store.create_task({"ticker": "NVDA"})
    if status == "interrupted":
        store.claim_next()
        store.interrupt_running()
    worker = TaskWorker(store, RecordingRunner(resumable=resumable))
    before = store.get_task(task_id)
    with pytest.raises(ValueError):
        worker.resume(task_id)
    assert store.get_task(task_id) == before


def test_resume_preserves_id_params_partial_reports_and_request_across_restart(tmp_path):
    store = Store(tmp_path / "web.db")
    params = {"ticker": "NVDA", "date": "2026-09-22", "analysts": ["market"], "max_debate_rounds": 3}
    task_id = store.create_task(params)
    store.claim_next()
    store.save_section(task_id, "news_report", "Previous news evidence")
    store.interrupt_running()
    runner = RecordingRunner()
    worker = TaskWorker(store, runner)
    result = worker.resume(task_id)
    assert result["id"] == task_id
    assert result["status"] == "queued"
    assert result["params"] == params
    assert result["sections"] == {"news_report": "Previous news evidence"}
    with pytest.raises(ValueError):
        worker.resume(task_id)
    restarted = TaskWorker(Store(store.path), runner)
    restarted.start()
    try:
        task = await_status(store, task_id, "completed")
    finally:
        restarted.stop()
    assert task["sections"]["news_report"] == "Previous news evidence"
    assert runner.calls[0][0]["id"] == task_id
    assert runner.calls[0][0]["params"] == params
    assert runner.calls[0][1] is True


def test_rerun_creates_new_identity_with_original_params_and_fresh_execution(tmp_path):
    store = Store(tmp_path / "web.db")
    old_id = store.create_task({"ticker": "NVDA", "date": "2026-09-22", "analysts": ["market"]})
    store.claim_next()
    store.save_section(old_id, "news_report", "Old evidence")
    store.interrupt_running()
    original = store.get_task(old_id)
    runner = RecordingRunner()
    worker = TaskWorker(store, runner)
    new = worker.rerun(old_id)
    assert new["id"] != old_id
    assert new["params"] == original["params"]
    assert new["sections"] == {}
    assert store.get_task(old_id) == original
    worker.start()
    try:
        await_status(store, new["id"], "completed")
    finally:
        worker.stop()
    assert runner.calls[0][0]["id"] == new["id"]
    assert runner.calls[0][1] is False
    assert store.get_task(old_id) == original


def test_cursor_wait_reads_persisted_events_and_wakes_on_completion(tmp_path):
    store = Store(tmp_path / "web.db")
    task_id = store.create_task({"ticker": "NVDA"})
    runner = RecordingRunner(block_first=True)
    worker = TaskWorker(store, runner)
    worker.start()
    try:
        assert runner.first_started.wait(5)
        events = worker.wait_for_events(task_id, 0, timeout=0.1)
        assert events[-1]["payload"]["text"] == "Partial market evidence"
        cursor = events[-1]["id"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(worker.wait_for_events, task_id, cursor, 2)
            runner.release.set()
            assert pending.result(3)
        await_status(store, task_id, "completed")
        events = worker.wait_for_events(task_id, cursor, timeout=0.1)
        assert events[-1]["kind"] == "completed"
        start = monotonic()
        assert worker.wait_for_events(task_id, events[-1]["id"], timeout=2) == []
        assert monotonic() - start < 0.5
    finally:
        runner.release.set()
        worker.stop()


def test_stop_does_not_cancel_current_run_or_claim_next_task(tmp_path):
    store = Store(tmp_path / "web.db")
    first = store.create_task({"ticker": "NVDA"})
    second = store.create_task({"ticker": "AAPL"})
    runner = RecordingRunner(block_first=True)
    worker = TaskWorker(store, runner)
    worker.start()
    try:
        assert runner.first_started.wait(5)
        worker.stop()
        assert store.get_task(first)["status"] == "running"
        runner.release.set()
        await_status(store, first, "completed")
    finally:
        runner.release.set()
        worker.stop()
    assert store.get_task(second)["status"] == "queued"


def test_completion_between_cursor_read_and_snapshot_does_not_drop_terminal_event(tmp_path):
    class CompletingStore(Store):
        def get_task(self, task_id):
            # Reproduce a worker commit between the subscriber's two reads.
            self.save_section(task_id, "decision", "Safe decision")
            self.finish(task_id, "Hold", "Safe decision")
            return super().get_task(task_id)

    store = CompletingStore(tmp_path / "web.db")
    task_id = store.create_task({"ticker": "NVDA"})
    store.claim_next()
    worker = TaskWorker(store, RecordingRunner())
    events = worker.wait_for_events(task_id, 0, timeout=0.1)
    assert [event["kind"] for event in events] == ["completed"]
