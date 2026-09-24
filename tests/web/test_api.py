import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import FakeRunner, await_task
from web.server import create_app

PARAMS = {"ticker": "nvda", "name": "NVIDIA", "date": "2026-09-22"}


def test_history_and_snapshot_do_not_wait_for_active_analysis_lock(client):
    from web.runner import _RUN_LOCK, GraphRunner

    store = client.app.state.store
    # Stop the test worker before constructing interrupted history.
    client.app.state.worker.stop()
    task_id = store.create_task(PARAMS)
    store.claim_next()
    store.interrupt_running()
    client.app.state.runner = GraphRunner(client.app.state.settings, client.app.state.data_dir)
    with ThreadPoolExecutor(max_workers=1) as pool, _RUN_LOCK:
        pending = pool.submit(client.get, "/api/tasks")
        response = pending.result(timeout=1)
        assert response.status_code == 200
        task = next(task for task in response.json()["tasks"] if task["id"] == task_id)
        assert task["status"] == "interrupted" and task["can_resume"] is False
        response = pool.submit(client.get, f"/api/tasks/{task_id}").result(timeout=1)
        assert response.status_code == 200
        assert response.json()["can_resume"] is False


@pytest.mark.parametrize("method,path", [("POST", "/api/tasks"), ("PATCH", "/api/settings")])
def test_unconfigured_compatible_provider_rejected_without_mutation(client, method, path):
    before = client.app.state.store.get_settings()
    body = {"provider": "openai_compatible", "quick_model": "local-fast", "deep_model": "local-deep"}
    if method == "POST":
        body.update(PARAMS)
    response = client.request(method, path, json=body)
    assert response.status_code == 422
    assert "provider" in response.text
    assert client.get("/api/tasks").json() == {"tasks": []}
    assert client.app.state.store.get_settings() == before


def test_health_and_secret_mask(client):
    assert client.get("/healthz").text == "ok\n"
    response = client.patch("/api/settings", json={"keys": {"openai": "sk-private-1234"}})
    assert response.status_code == 200
    assert response.json()["keys"]["openai"] == {"configured": True, "last4": "1234"}
    assert "sk-private-1234" not in client.get("/api/settings").text
    assert (
        client.patch("/api/settings", json={"backend_url": "http://localhost"}).status_code == 422
    )


def test_provider_routes_manage_custom_metadata_and_mask_credentials(client):
    path = "/api/settings/providers"
    created = client.post(path, json={"kind": "custom", "name": "Gateway",
                                      "base_url": "http://localhost:1234/v1/", "key": "secret-xyz99"})
    assert created.status_code == 200
    entry = next(item for item in created.json()["providers"] if item["name"] == "Gateway")
    provider = entry["id"]
    assert provider.startswith("custom:")
    assert entry == {"id": provider, "name": "Gateway", "kind": "custom",
                     "base_url": "http://localhost:1234/v1",
                     "key": {"configured": True, "last4": "yz99"}}
    assert "secret-xyz99" not in created.text + client.get("/api/settings").text

    edited = client.patch(f"{path}/{provider}", json={"name": "Gateway 2",
                            "base_url": "https://example.test/v1", "key": "replacement-5678"})
    assert edited.status_code == 200
    assert next(item for item in edited.json()["providers"] if item["id"] == provider) == {
        "id": provider, "name": "Gateway 2", "kind": "custom",
        "base_url": "https://example.test/v1", "key": {"configured": True, "last4": "5678"}}
    assert "replacement-5678" not in edited.text
    cleared = client.patch(f"{path}/{provider}", json={"clear_key": True})
    assert cleared.status_code == 200
    assert next(item for item in cleared.json()["providers"] if item["id"] == provider)["key"] == {
        "configured": False, "last4": None}
    removed = client.delete(f"{path}/{provider}")
    assert removed.status_code == 200
    assert provider not in {item["id"] for item in removed.json()["providers"]}


def test_provider_routes_reject_invalid_shapes_and_deletion_guards(client):
    path = "/api/settings/providers"
    for body in ({"kind": "other", "name": "Bad", "base_url": "https://example.test"},
                 {"kind": "custom", "name": "Bad", "base_url": "https://example.test",
                  "unknown": "value"}):
        assert client.post(path, json=body).status_code == 422
    assert client.post(path, json={"kind": "built_in", "id": "mistral"}).status_code == 200
    assert client.patch(f"{path}/mistral", json={"name": "Renamed"}).status_code == 422
    assert client.patch(f"{path}/mistral", json={"key": "replacement",
                                               "clear_key": True}).status_code == 422
    assert client.delete(f"{path}/openai").status_code == 422
    assert client.delete(f"{path}/custom:unknown").status_code == 422


def test_task_accepts_joined_custom_id_but_never_exposes_its_url(client):
    joined = client.post("/api/settings/providers", json={"kind": "custom", "name": "Desk",
                         "base_url": "http://localhost:1234/v1", "key": "secret-xyz99"}).json()
    provider = joined["providers"][-1]["id"]
    body = {**PARAMS, "provider": provider, "quick_model": "local-fast", "deep_model": "local-deep"}
    response = client.post("/api/tasks", json=body)
    assert response.status_code == 201
    assert response.json()["params"]["provider"] == provider
    assert "localhost:1234" not in response.text
    assert "secret-xyz99" not in response.text
    assert client.post("/api/tasks", json={**body, "provider": "custom:unknown"}).status_code == 422
    assert client.post("/api/tasks", json={**body, "quick_model": "custom"}).status_code == 422


def test_task_normalizes_case_of_legacy_built_in_provider(client):
    response = client.post("/api/tasks", json={**PARAMS, "provider": "OPENAI"})
    assert response.status_code == 201
    assert response.json()["params"]["provider"] == "openai"


def test_task_creation_rechecks_provider_after_stale_api_precheck(client, monkeypatch):
    service = client.app.state.settings
    store = client.app.state.store
    service.update({"keys": {"anthropic": "test-anthropic-secret"}})
    original_create = store.create_task

    def remove_before_insert(params):
        service.remove_provider("anthropic")
        return original_create(params)

    monkeypatch.setattr(store, "create_task", remove_before_insert)
    response = client.post("/api/tasks", json={**PARAMS, "provider": "anthropic",
                                               "quick_model": "claude-sonnet-5",
                                               "deep_model": "claude-sonnet-5"})

    assert response.status_code == 422
    assert "provider" in response.text
    assert store.list_tasks() == []
    assert "anthropic" not in {item["id"] for item in service.public()["providers"]}


def test_rerun_rechecks_provider_after_stale_api_precheck(client, monkeypatch):
    client.app.state.worker.stop()
    service = client.app.state.settings
    store = client.app.state.store
    service.update({"keys": {"anthropic": "test-anthropic-secret"}})
    task_id = store.create_task({"provider": "anthropic", "ticker": "NVDA",
                                 "quick_model": "claude-sonnet-5", "deep_model": "claude-sonnet-5"})
    with store.transaction(immediate=True) as db:
        db.execute("UPDATE tasks SET status='failed' WHERE id=?", (task_id,))
    original_create = store.create_task

    def remove_before_insert(params):
        service.remove_provider("anthropic")
        return original_create(params)

    monkeypatch.setattr(store, "create_task", remove_before_insert)
    response = client.post(f"/api/tasks/{task_id}/rerun")

    assert response.status_code == 422
    assert "provider" in response.text
    assert len(store.list_tasks()) == 1


def test_create_filters_history_and_exports_only_persisted_public_report(client):
    response = client.post("/api/tasks", json=PARAMS)
    assert response.status_code == 201
    task_id = response.json()["id"]
    task = await_task(client, task_id)
    assert task["ticker"] == "NVDA"
    assert task["name"] == "NVIDIA"
    assert task["params"]["checkpoint_enabled"] is True
    assert task["rating"] == "Overweight"
    assert task["can_resume"] is False
    assert (
        client.get("/api/tasks?q=nvidia&status=completed&rating=Overweight").json()["tasks"][0][
            "id"
        ]
        == task_id
    )
    assert client.get("/api/tasks?rating=Sell").json() == {"tasks": []}
    report = client.get(f"/api/tasks/{task_id}/report")
    assert report.json()["decision"]["rating"] == "Overweight"
    assert report.json()["decision"]["executive_summary"] == "Source summary"
    assert "price_target" not in report.json()["decision"]
    markdown = client.get(f"/api/tasks/{task_id}/report.md")
    assert markdown.status_code == 200
    assert "Source market evidence" in markdown.text
    assert "Source summary" in markdown.text
    assert markdown.headers["content-disposition"].startswith(
        'attachment; filename="NVDA-2026-09-22-'
    )
    assert "private-raw-state" not in json.dumps(task) + report.text + markdown.text


@pytest.mark.parametrize(
    "changes",
    [
        {"ticker": "NVIDIA Corporation"},
        {"date": "2999-01-01"},
        {"analysts": []},
        {"api_key": "input-secret"},
        {"ticker": {"key": "input-secret"}},
    ],
)
def test_invalid_requests_are_not_queued_or_echoed(client, changes):
    response = client.post("/api/tasks", json={**PARAMS, **changes})
    assert response.status_code == 422
    assert "input-secret" not in response.text
    assert client.get("/api/tasks").json() == {"tasks": []}


def test_missing_provider_key_rejected_before_enqueue(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.post("/api/tasks", json=PARAMS)
    assert response.status_code == 422
    assert "credential" in response.text
    assert client.get("/api/tasks").json() == {"tasks": []}


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/tasks", PARAMS),
        ("PATCH", "/api/settings", {}),
        ("DELETE", "/api/tasks/missing", None),
        ("POST", "/api/settings/test-connection", {"provider": "openai"}),
        ("POST", "/api/tasks/missing/resume", None),
        ("POST", "/api/tasks/missing/rerun", None),
    ],
)
def test_cross_origin_writes_are_rejected(client, method, path, body):
    for headers in (
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
    ):
        response = client.request(method, path, json=body, headers=headers)
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers


def test_same_origin_writes_and_secret_safe_connection_test(client, monkeypatch):
    assert (
        client.patch("/api/settings", json={}, headers={"Origin": "http://testserver"}).status_code
        == 200
    )

    def fail(*args, **kwargs):
        raise RuntimeError("private-provider-secret")

    monkeypatch.setattr("web.settings.requests.get", fail)
    response = client.post("/api/settings/test-connection", json={"provider": "openai"})
    assert response.json()["ok"] is False
    assert "private-provider-secret" not in response.text
    assert (
        client.post(
            "/api/settings/test-connection", json={"provider": "openai", "url": "http://localhost"}
        ).status_code
        == 422
    )


def test_search_maps_results_and_validates_query(client, monkeypatch):
    monkeypatch.setattr(
        "web.search._yahoo_lookup",
        lambda query: [
            {
                "symbol": "NVDA",
                "shortname": "NVIDIA",
                "exchDisp": "NASDAQ",
                "quoteType": "EQUITY",
                "private": "hidden",
            }
        ],
    )
    assert client.get("/api/assets/search?q=nvda").json() == {
        "results": [{"symbol": "NVDA", "name": "NVIDIA", "exchange": "NASDAQ", "type": "EQUITY"}],
        "unavailable": False,
    }
    assert client.get("/api/assets/search?q=a").status_code == 422


def test_sse_reconnect_replays_ordered_ids_without_raw_state(client):
    task_id = client.post("/api/tasks", json=PARAMS).json()["id"]
    await_task(client, task_id)
    response = client.get(f"/api/tasks/{task_id}/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert len(ids) == 4 and ids == sorted(set(ids))
    assert response.text.count("event: completed") == 1
    assert "private-raw-state" not in response.text
    replay = client.get(f"/api/tasks/{task_id}/events", headers={"Last-Event-ID": str(ids[1])})
    assert [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")] == ids[
        2:
    ]
    assert client.get(f"/api/tasks/{task_id}/events?after={ids[-1]}").text == ""
    assert (
        client.get(f"/api/tasks/{task_id}/events", headers={"Last-Event-ID": "invalid"}).status_code
        == 422
    )


def test_live_sse_wait_does_not_block_other_requests(tmp_path, monkeypatch):
    runner = FakeRunner(blocked=True)
    app = create_app(data_dir=tmp_path, executor=runner)
    with TestClient(app) as client, ThreadPoolExecutor(2) as pool:
        task_id = client.post("/api/tasks", json=PARAMS).json()["id"]
        assert runner.started.wait(3)
        waiting = Event()
        original = app.state.worker.wait_for_events

        def wait(*args, **kwargs):
            waiting.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(app.state.worker, "wait_for_events", wait)
        stream = pool.submit(client.get, f"/api/tasks/{task_id}/events")
        try:
            assert waiting.wait(3)
            assert pool.submit(client.get, "/healthz").result(1).text == "ok\n"
        finally:
            runner.release.set()
        assert "event: completed" in stream.result(3).text


def test_rerun_and_delete_preserve_other_tasks_and_shared_data(client, tmp_path):
    task_id = client.post("/api/tasks", json=PARAMS).json()["id"]
    old = await_task(client, task_id)
    new_id = client.post(f"/api/tasks/{task_id}/rerun").json()["id"]
    assert new_id != task_id
    new = await_task(client, new_id)
    assert new["params"] == old["params"]
    assert client.get(f"/api/tasks/{task_id}").json() == old
    own = tmp_path / "reports" / task_id
    own.mkdir(parents=True)
    (own / "decision.md").write_text("source")
    shared = tmp_path / "memory"
    shared.mkdir()
    (shared / "memory.md").write_text("shared")
    assert client.delete(f"/api/tasks/{task_id}").status_code == 204
    assert not own.exists()
    assert (shared / "memory.md").read_text() == "shared"
    assert client.get(f"/api/tasks/{new_id}").status_code == 200
    assert client.get(f"/api/tasks/{task_id}").status_code == 404


def test_running_task_cannot_be_deleted_and_failed_reports_are_preserved(tmp_path):
    runner = FakeRunner(blocked=True, fail=True)
    with TestClient(create_app(data_dir=tmp_path, executor=runner)) as client:
        task_id = client.post("/api/tasks", json=PARAMS).json()["id"]
        try:
            assert runner.started.wait(3)
            assert client.delete(f"/api/tasks/{task_id}").status_code == 409
        finally:
            runner.release.set()
        task = await_task(client, task_id, "failed")
        assert task["rating"] is None
        report = client.get(f"/api/tasks/{task_id}/report").json()
        assert report["sections"] == {"market_report": "Source market evidence"}
        assert report["decision"] is None
        assert "private-provider-secret" not in json.dumps(task)


@pytest.mark.parametrize("resumable", [True, False])
def test_restart_and_resume_requires_compatible_checkpoint(tmp_path, resumable):
    from web.store import Store

    store = Store(tmp_path / "web.db")
    task_id = store.create_task(PARAMS)
    store.claim_next()
    store.save_section(task_id, "news_report", "Previous evidence")
    with TestClient(
        create_app(data_dir=tmp_path, executor=FakeRunner(resumable=resumable))
    ) as client:
        task = client.get(f"/api/tasks/{task_id}").json()
        assert task["status"] == "interrupted"
        assert task["can_resume"] is resumable
        response = client.post(f"/api/tasks/{task_id}/resume")
        assert response.status_code == (200 if resumable else 409)
        if resumable:
            assert await_task(client, task_id)["sections"]["news_report"] == "Previous evidence"


@pytest.mark.parametrize("suffix", ["", "/events", "/report", "/report.md"])
def test_missing_task_returns_404(client, suffix):
    assert client.get(f"/api/tasks/missing{suffix}").status_code == 404


@pytest.mark.parametrize("cursor", ["-1", "9223372036854775808", "9" * 100])
def test_sse_rejects_out_of_range_cursors_without_server_error(client, cursor):
    task_id = client.post("/api/tasks", json=PARAMS).json()["id"]
    await_task(client, task_id)
    assert (
        client.get(f"/api/tasks/{task_id}/events", headers={"Last-Event-ID": cursor}).status_code
        == 422
    )
    assert client.get(f"/api/tasks/{task_id}/events?after={cursor}").status_code == 422


def test_idle_stream_sends_heartbeat_then_completes(tmp_path, monkeypatch):
    runner = FakeRunner(blocked=True)
    app = create_app(data_dir=tmp_path, executor=runner)
    monkeypatch.setattr("web.api.HEARTBEAT_SECONDS", 0.01)
    with TestClient(app) as client:
        task_id = client.post("/api/tasks", json=PARAMS).json()["id"]
        assert runner.started.wait(3)
        original = app.state.worker.wait_for_events
        idle = False

        def wait(*args, **kwargs):
            nonlocal idle
            if idle:
                runner.release.set()
            batch = original(*args, **kwargs)
            if not batch:
                idle = True
            return batch

        monkeypatch.setattr(app.state.worker, "wait_for_events", wait)
        try:
            response = client.get(f"/api/tasks/{task_id}/events")
        finally:
            runner.release.set()
        assert ": ping\n\n" in response.text
        assert "event: completed" in response.text


def test_checkpoint_probe_does_not_block_health(tmp_path):
    from web.store import Store

    store = Store(tmp_path / "web.db")
    task_id = store.create_task(PARAMS)
    store.claim_next()
    probing, release = Event(), Event()

    class BlockingProbe(FakeRunner):
        def can_resume(self, task):
            probing.set()
            return release.wait(5)

    with (
        TestClient(create_app(data_dir=tmp_path, executor=BlockingProbe())) as client,
        ThreadPoolExecutor(2) as pool,
    ):
        pending = pool.submit(client.get, f"/api/tasks/{task_id}")
        try:
            assert probing.wait(3)
            assert pool.submit(client.get, "/healthz").result(1).text == "ok\n"
        finally:
            release.set()
        assert pending.result(3).json()["can_resume"] is True
