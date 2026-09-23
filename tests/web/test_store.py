import pytest

from web.store import Store


def test_claim_and_replay(tmp_path):
    store = Store(tmp_path / "web.db")
    first = store.create_task({"ticker": "NVDA", "date": "2026-09-22"})
    second = store.create_task({"ticker": "AAPL", "date": "2026-09-22"})
    assert store.claim_next()["id"] == first
    assert store.claim_next() is None  # one running task blocks the queue
    event_id = store.append_event(first, "stage", {"name": "analysts"})
    assert store.events_after(first, 0)[0]["id"] == event_id
    assert store.events_after(first, event_id) == []
    store.interrupt_running()
    assert store.get_task(first)["status"] == "interrupted"
    assert store.claim_next()["id"] == second


def test_creation_and_history_filters(tmp_path):
    store = Store(tmp_path / "web.db")
    task_id = store.create_task({"ticker": "NVDA", "name": "NVIDIA", "date": "2026-09-22"})
    task = store.get_task(task_id)
    assert task["status"] == "queued"
    assert task["params"] == {"ticker": "NVDA", "name": "NVIDIA", "date": "2026-09-22"}
    assert task["sections"] == {}
    assert store.list_tasks(query="nvidia") == [task]
    assert store.list_tasks(query="aapl") == []
    assert store.list_tasks(status="queued") == [task]
    assert store.list_tasks(rating="Buy") == []
    assert store.get_task("missing") is None


def test_events_are_task_scoped_and_replay_in_sequence_after_reopening(tmp_path):
    path = tmp_path / "web.db"
    store = Store(path)
    first = store.create_task({"ticker": "NVDA"})
    second = store.create_task({"ticker": "AAPL"})
    first_id = store.append_event(first, "stage", {"name": "analysts"})
    store.append_event(second, "stage", {"name": "other"})
    last_id = store.append_event(first, "report", {"text": "Partial analysis"})
    assert last_id > first_id
    assert Store(path).events_after(first, first_id) == [
        {
            "id": last_id,
            "task_id": first,
            "kind": "report",
            "payload": {"text": "Partial analysis"},
            "created_at": store.events_after(first, first_id)[0]["created_at"],
        }
    ]


def test_sections_overwrite_and_finish_requires_saved_decision(tmp_path):
    store = Store(tmp_path / "web.db")
    task_id = store.create_task({"ticker": "NVDA"})
    store.claim_next()
    with pytest.raises(ValueError, match="decision"):
        store.finish(task_id, "Buy", "Proposed purchase")
    assert store.get_task(task_id)["status"] == "running"
    store.save_section(task_id, "decision", "Initial decision")
    store.save_section(task_id, "decision", "Proposed purchase")
    store.save_section(task_id, "analysts", "Fundamental analysis")
    store.finish(task_id, "Buy", "Proposed purchase")
    task = Store(tmp_path / "web.db").get_task(task_id)
    assert task["sections"] == {
        "decision": "Proposed purchase",
        "analysts": "Fundamental analysis",
    }
    assert task["decision"] == "Proposed purchase"
    assert task["rating"] == "Buy"
    assert task["status"] == "completed"
    assert store.list_tasks(status="completed", rating="Buy") == [task]


@pytest.mark.parametrize("rating", ["BUY", "buy", "", "Strong Buy"])
def test_finish_rejects_invalid_rating_without_mutation(tmp_path, rating):
    store = Store(tmp_path / "web.db")
    task_id = store.create_task({"ticker": "NVDA"})
    store.claim_next()
    store.save_section(task_id, "decision", "Proposed purchase")

    with pytest.raises(ValueError, match="rating"):
        store.finish(task_id, rating, "Proposed purchase")

    task = Store(tmp_path / "web.db").get_task(task_id)
    assert task["status"] == "running"
    assert task["rating"] is None
    assert task["decision"] is None
    assert task["sections"]["decision"] == "Proposed purchase"


def test_failure_keeps_partial_report_and_releases_queue(tmp_path):
    store = Store(tmp_path / "web.db")
    first = store.create_task({"ticker": "NVDA"})
    second = store.create_task({"ticker": "AAPL"})
    store.claim_next()
    store.save_section(first, "analysts", "Partial analysis")
    store.fail(first, "Provider unavailable")
    task = store.get_task(first)
    assert task["status"] == "failed"
    assert task["rating"] is None
    assert task["sections"] == {"analysts": "Partial analysis"}
    assert task["error"] == "Provider unavailable"
    assert store.claim_next()["id"] == second


def test_delete_refuses_running_and_cascades_only_its_own_data(tmp_path):
    store = Store(tmp_path / "web.db")
    first = store.create_task({"ticker": "NVDA"})
    second = store.create_task({"ticker": "AAPL"})
    store.claim_next()
    assert store.delete_task(first) is False
    store.save_section(first, "analysts", "First")
    store.append_event(first, "stage", {"name": "first"})
    store.interrupt_running()
    store.save_section(second, "analysts", "Second")
    store.append_event(second, "stage", {"name": "second"})
    assert store.delete_task(first) is True
    assert store.delete_task(first) is False
    assert store.get_task(first) is None
    assert store.events_after(first, 0) == []
    assert store.get_task(second)["sections"] == {"analysts": "Second"}
    assert len(store.events_after(second, 0)) == 1


@pytest.mark.parametrize(
    "method,payload",
    [
        ("create", {"ticker": "NVDA", "config": {"api_key": "secret"}}),
        ("create", {"ticker": "NVDA", "config": {"openai_api_key": "secret"}}),
        ("event", {"nested": [{"API_KEY": "secret"}]}),
    ],
)
def test_secret_fields_are_rejected_without_persistence(tmp_path, method, payload):
    store = Store(tmp_path / "web.db")
    task_id = store.create_task({"ticker": "NVDA"}) if method == "event" else None
    with pytest.raises(ValueError, match="secret"):
        if method == "create":
            store.create_task(payload)
        else:
            store.append_event(task_id, "stage", payload)
    assert len(store.list_tasks()) == (1 if method == "event" else 0)
    if task_id:
        assert store.events_after(task_id, 0) == []
