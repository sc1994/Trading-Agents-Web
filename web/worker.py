"""One background graph run at a time, independent of HTTP/SSE connections."""

from threading import Condition, Event, RLock, Thread
from time import monotonic
from typing import TYPE_CHECKING

from web.store import Store

if TYPE_CHECKING:
    from web.runner import GraphRunner


class TaskWorker:
    def __init__(self, store: Store, runner: "GraphRunner"):
        self.store = store
        self.runner = runner
        self._lifecycle = RLock()
        self._changed = Condition()
        self._stopping = Event()
        self._wake = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lifecycle:
            if self._thread is not None and self._thread.is_alive():
                return
            # Only startup recovery may mark an abandoned run interrupted.
            interrupted = self.store.interrupt_running()
            for task_id in interrupted:
                self.notify(task_id)
            self._stopping.clear()
            self._thread = Thread(target=self._run_queue, name="analysis-worker", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop future claims; allow the active run to finish without cancellation.

        Joining is bounded so shutdown is not held hostage by an external API.
        If the process exits before the run finishes, startup recovers its state.
        """
        with self._lifecycle:
            self._stopping.set()
            self._wake.set()
            thread = self._thread
        with self._changed:
            self._changed.notify_all()
        if thread is not None:
            thread.join(timeout=1)

    def resume(self, task_id: str) -> dict:
        task = self._get_task(task_id)
        if task["status"] != "interrupted":
            raise ValueError("only interrupted tasks can resume")
        if not self.runner.can_resume(task):
            raise ValueError("No compatible checkpoint is available")
        task = self.store.requeue_interrupted(task_id)
        self.notify(task_id)
        self._wake.set()
        return task

    def rerun(self, task_id: str) -> dict:
        task = self._get_task(task_id)
        new_id = self.store.create_task(task["params"])
        # Fresh tasks have no resume flag. GraphRunner clears their shared thread
        # under its run lock before constructing or streaming the graph.
        result = self._get_task(new_id)
        self._wake.set()
        return result

    def _get_task(self, task_id: str) -> dict:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError("Task not found")
        return task

    def notify(self, task_id: str) -> None:
        """Wake subscribers only after a persisted event is available."""
        with self._changed:
            self._changed.notify_all()

    def wait_for_events(self, task_id: str, last_id: int, timeout: float = 15) -> list[dict]:
        """Read durable cursor events, waiting at most timeout seconds for a change.

        Async HTTP handlers should call this blocking method in a thread. The
        cursor, not an in-memory subscription, is authoritative after reconnect.
        """
        deadline = monotonic() + timeout
        with self._changed:
            while True:
                events = self.store.events_after(task_id, last_id)
                if events:
                    return events
                task = self.store.get_task(task_id)
                if task is None or task["status"] in {"completed", "failed", "interrupted"}:
                    # A terminal transaction may have committed between these
                    # two reads. Deliver its event before closing a subscriber.
                    return self.store.events_after(task_id, last_id)
                remaining = deadline - monotonic()
                if remaining <= 0 or self._stopping.is_set():
                    return []
                self._changed.wait(remaining)

    def _run_queue(self) -> None:
        while True:
            with self._lifecycle:
                if self._stopping.is_set():
                    return
                task = self.store.claim_next()
            if task is None:
                self._wake.wait(0.25)
                self._wake.clear()
                continue
            self._execute(task)

    def _execute(self, task: dict) -> None:
        task_id = task["id"]

        def emit(kind: str, payload: dict) -> None:
            # GraphRunner emits display-safe text; never serialize its returned
            # internal state or attempt to recover missing text from raw state.
            if kind == "section":
                self.store.save_section(task_id, payload["section"], payload["text"])
            self.store.append_event(task_id, kind, payload)
            self.notify(task_id)

        try:
            self.store.append_event(task_id, "running", {})
            self.notify(task_id)
            _state, rating = self.runner.run(task, emit, resume=bool(task["resume_requested"]))
            decision = self._get_task(task_id)["sections"].get("decision", "")
            # finish atomically saves terminal state and its completion event.
            self.store.finish(task_id, rating, decision)
        except Exception:
            # Exception messages and class names are not a safe public channel.
            self.store.fail(task_id, "Analysis failed; partial reports were preserved")
        self.notify(task_id)
