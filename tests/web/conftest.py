from threading import Event
from time import monotonic

import pytest
from fastapi.testclient import TestClient


class FakeRunner:
    """Replace only the external graph, keeping API/storage/worker real."""

    def __init__(self, *, blocked=False, resumable=False, fail=False):
        self.started = Event()
        self.release = Event()
        if not blocked:
            self.release.set()
        self.resumable = resumable
        self.fail = fail

    def can_resume(self, task):
        return self.resumable

    def run(self, task, emit, *, resume=False):
        emit("section", {"section": "market_report", "text": "Source market evidence"})
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("Test runner was not released")
        if self.fail:
            raise RuntimeError("private-provider-secret")
        emit(
            "section",
            {
                "section": "decision",
                "text": "**Rating**: [REDACTED]\n\n**Executive Summary**: Source summary",
            },
        )
        return {"final_trade_decision": "Overweight private-raw-state"}, "Overweight"


@pytest.fixture
def client(tmp_path):
    from web.server import create_app

    with TestClient(create_app(data_dir=tmp_path, executor=FakeRunner())) as client:
        yield client


def await_task(client, task_id, status="completed"):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] == status:
            return task
        Event().wait(0.01)
    pytest.fail(f"Task did not reach {status}: {task}")
