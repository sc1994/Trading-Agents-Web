import os
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
import requests

from web.settings import _CREDENTIAL_ENVS, WEB_PROVIDERS, SettingsService
from web.store import Store
from web.validation import validate_task


def test_key_never_echoes(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))

    response = service.update({"provider": "openai", "keys": {"openai": "sk-private-1234"}})

    assert response["keys"]["openai"] == {"configured": True, "last4": "1234"}
    assert "sk-private-1234" not in str(service.public())


def test_replacement_blank_and_explicit_clear(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = SettingsService(Store(tmp_path / "web.db"))
    service.update({"keys": {"openai": "first-secret-1234"}})
    assert service.update({"keys": {"openai": ""}})["keys"]["openai"]["last4"] == "1234"
    assert service.update({"keys": {"openai": "second-secret-5678"}})["keys"]["openai"] == {
        "configured": True,
        "last4": "5678",
    }
    assert service.update({"clear_keys": ["openai"]})["keys"]["openai"] == {
        "configured": False,
        "last4": None,
    }
    assert "first-secret" not in str(service.public())
    assert "second-secret" not in str(service.public())


def test_environment_key_is_masked_and_never_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-only-9876")
    store = Store(tmp_path / "web.db")
    service = SettingsService(store)

    assert service.public()["keys"]["openai"] == {"configured": True, "last4": "9876"}
    assert store.get_settings() == {}


def test_short_stored_key_is_never_returned_whole(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service = SettingsService(Store(tmp_path / "web.db"))

    response = service.update({"keys": {"openai": "abcd"}})

    assert response["keys"]["openai"] == {"configured": True, "last4": None}
    assert "abcd" not in str(service.public())


def test_short_environment_key_is_never_returned_whole(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "abc")
    service = SettingsService(Store(tmp_path / "web.db"))

    assert service.public()["keys"]["openai"] == {"configured": True, "last4": None}
    assert "abc" not in str(service.public())


@pytest.mark.parametrize(
    "change",
    [
        {"keys": {"unexpected": "secret"}},
        {"keys": {"openai": 123}},
        {"clear_keys": ["unexpected"]},
        {"provider": "untrusted"},
        {"backend_url": "http://127.0.0.1/private"},
    ],
)
def test_invalid_settings_are_rejected_without_mutation(tmp_path, change):
    store = Store(tmp_path / "web.db")
    service = SettingsService(store)
    with pytest.raises(ValueError):
        service.update(change)
    assert store.get_settings() == {}


def test_provider_change_selects_its_models_and_persists_defaults(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))

    public = service.update(
        {
            "provider": "anthropic",
            "language": " Chinese ",
            "checkpoint_enabled": False,
            "deep_model": "claude-sonnet-5",
        }
    )

    assert {
        name: public[name]
        for name in ("provider", "quick_model", "deep_model", "language", "checkpoint_enabled")
    } == {
        "provider": "anthropic",
        "quick_model": "claude-sonnet-5",
        "deep_model": "claude-sonnet-5",
        "language": "Chinese",
        "checkpoint_enabled": False,
    }
    assert SettingsService(Store(tmp_path / "web.db")).public() == public


def test_catalog_custom_provider_accepts_bounded_model_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "env-mistral-key")
    service = SettingsService(Store(tmp_path / "web.db"))
    public = service.update(
        {
            "provider": "mistral",
            "quick_model": "mistral-small-latest",
            "deep_model": "mistral-large-latest",
        }
    )
    assert public["quick_model"] == "mistral-small-latest"
    assert (
        service.resolve_run_config(
            {
                "provider": "mistral",
                "quick_model": public["quick_model"],
                "deep_model": public["deep_model"],
            }
        )["config"]["deep_think_llm"]
        == "mistral-large-latest"
    )


def test_custom_model_literal_and_oversized_id_are_rejected(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    with pytest.raises(ValueError, match="quick_model"):
        service.update(
            {"provider": "mistral", "quick_model": "custom", "deep_model": "valid-model"}
        )
    with pytest.raises(ValueError, match="quick_model"):
        service.update(
            {"provider": "mistral", "quick_model": "m" * 129, "deep_model": "valid-model"}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"provider": "openai", "quick_model": "claude-sonnet-5"},
        {"deep_model": "custom"},
        {"language": ""},
        {"checkpoint_enabled": "false"},
        {"keys": {"openai": "valid"}, "deep_model": "invalid"},
    ],
)
def test_invalid_defaults_do_not_save_even_valid_sibling_fields(tmp_path, change):
    store = Store(tmp_path / "web.db")
    with pytest.raises(ValueError):
        SettingsService(store).update(change)
    assert store.get_settings() == {}


def test_resolve_run_config_uses_only_selected_model_key_and_data_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-anthropic")
    monkeypatch.setenv("FRED_API_KEY", "ambient-fred")
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_LLM_BACKEND_URL", "http://127.0.0.1/private")
    store = Store(tmp_path / "web.db")
    service = SettingsService(store)
    service.update({"keys": {"openai": "stored-openai", "fred": "stored-fred"}})
    params = validate_task(
        {
            "ticker": "NVDA",
            "date": "2026-09-22",
            "analysts": ["fundamentals"],
        },
        {**service.public(), "analysts": ["fundamentals"]},
    )
    task_id = store.create_task(params)

    resolved = service.resolve_run_config(store.get_task(task_id)["params"])

    assert resolved["api_key_env"] == {
        "OPENAI_API_KEY": "stored-openai",
        "FRED_API_KEY": "stored-fred",
    }
    assert resolved["config"]["llm_provider"] == "openai"
    assert resolved["config"]["quick_think_llm"] == "gpt-5.6-luna"
    assert resolved["config"]["deep_think_llm"] == "gpt-5.6"
    assert resolved["config"]["checkpoint_enabled"] is True
    assert resolved["config"]["backend_url"] is None
    assert "stored-openai" not in str(store.get_task(task_id))
    assert "stored-fred" not in str(store.events_after(task_id, 0))


def test_resolve_run_config_rejects_absent_provider_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    service = SettingsService(Store(tmp_path / "web.db"))
    service.update({"provider": "anthropic"})
    with pytest.raises(ValueError, match="not configured"):
        service.resolve_run_config({"provider": "anthropic"})


def test_new_database_directory_and_file_are_private(tmp_path):
    directory = tmp_path / "dedicated"
    db_file = directory / "web.db"

    Store(db_file)

    assert directory.stat().st_mode & 0o777 == 0o700
    assert db_file.stat().st_mode & 0o777 == 0o600


def test_existing_insecure_database_directory_is_not_modified(tmp_path):
    directory = tmp_path / "data"
    directory.mkdir(mode=0o755)
    db_file = directory / "web.db"
    db_file.touch(mode=0o644)
    os.chmod(directory, 0o755)
    os.chmod(db_file, 0o644)

    with pytest.raises(ValueError, match="directory.*private"):
        Store(db_file)

    assert directory.stat().st_mode & 0o777 == 0o755
    assert db_file.stat().st_mode & 0o777 == 0o644


def test_connection_probe_is_bounded_to_provider_endpoint(tmp_path, monkeypatch):
    service = SettingsService(Store(tmp_path / "web.db"))
    service.update({"keys": {"openai": "stored-openai"}})

    class Response:
        status_code = 200

    def fake_get(url, **kwargs):
        assert url == "https://api.openai.com/v1/models"
        assert kwargs["headers"]["Authorization"] == "Bearer stored-openai"
        assert kwargs["timeout"] == (3, 5)
        assert kwargs["allow_redirects"] is False
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    assert service.test_connection("openai") == {"ok": True}


def test_connection_failure_redacts_provider_error(tmp_path, monkeypatch):
    service = SettingsService(Store(tmp_path / "web.db"))
    service.update({"keys": {"openai": "stored-openai"}})

    def fake_get(*args, **kwargs):
        raise requests.RequestException("Request failed with stored-openai in URL")

    monkeypatch.setattr(requests, "get", fake_get)
    response = service.test_connection("openai")
    assert response == {"ok": False, "error": "Connection test failed"}
    assert "stored-openai" not in str(response)


def test_connection_test_does_not_probe_unconfigured_or_custom_endpoints(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    service = SettingsService(Store(tmp_path / "web.db"))

    def forbidden_get(*args, **kwargs):
        pytest.fail("No request should be made")

    monkeypatch.setattr(requests, "get", forbidden_get)
    with pytest.raises(ValueError, match="joined"):
        service.test_connection("anthropic")
    with pytest.raises(ValueError, match="provider"):
        service.test_connection("openai_compatible")
    with pytest.raises(ValueError, match="supported"):
        service.test_connection("http://127.0.0.1")


def test_custom_run_config_uses_distinct_private_urls_and_keys(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    first = service.add_provider({"kind": "custom", "name": "Gateway",
                 "base_url": "http://localhost:1234/v1", "key": "secret-xyz99"})["providers"][-1]["id"]
    second = service.add_provider({"kind": "custom", "name": "Cloud",
                 "base_url": "https://gateway.example/v1", "key": "other-secret-6789"})["providers"][-1]["id"]
    for provider, url, key in ((first, "http://localhost:1234/v1", "secret-xyz99"),
                               (second, "https://gateway.example/v1", "other-secret-6789")):
        result = service.resolve_run_config({"provider": provider,
                                             "quick_model": "fast", "deep_model": "deep"})
        assert result["config"]["llm_provider"] == "openai_compatible"
        assert result["config"]["backend_url"] == url
        assert result["api_key_env"]["OPENAI_COMPATIBLE_API_KEY"] == key
        assert key not in str(service.public())
    with pytest.raises(ValueError, match="joined"):
        service.resolve_run_config({"provider": "custom:unknown", "quick_model": "fast",
                                    "deep_model": "deep"})


def test_keyless_custom_run_shadows_ambient_generic_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "other-endpoint-secret")
    service = SettingsService(Store(tmp_path / "web.db"))
    provider = service.add_provider({"kind": "custom", "name": "Local",
               "base_url": "http://localhost:1234/v1"})["providers"][-1]["id"]

    resolved = service.resolve_run_config({"provider": provider,
                                           "quick_model": "fast", "deep_model": "deep"})

    assert resolved["api_key_env"]["OPENAI_COMPATIBLE_API_KEY"] == ""
    assert "other-endpoint-secret" not in str(resolved)


def test_custom_connection_uses_saved_endpoint_without_redirects_or_remote_errors(tmp_path, monkeypatch):
    service = SettingsService(Store(tmp_path / "web.db"))
    provider = service.add_provider({"kind": "custom", "name": "Gateway",
               "base_url": "http://localhost:1234/v1", "key": "secret-xyz99"})["providers"][-1]["id"]

    class Response:
        status_code = 500
        text = "private remote error secret-xyz99"

    def fake_get(url, **kwargs):
        assert url == "http://localhost:1234/v1/models"
        assert kwargs == {"headers": {"Authorization": "Bearer secret-xyz99"},
                          "timeout": (3, 5), "allow_redirects": False}
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    assert service.test_connection(provider) == {"ok": False, "error": "Connection test failed"}
    with pytest.raises(ValueError, match="joined"):
        service.test_connection("custom:unknown")


def test_keyless_custom_connection_uses_placeholder(tmp_path, monkeypatch):
    service = SettingsService(Store(tmp_path / "web.db"))
    provider = service.add_provider({"kind": "custom", "name": "Local",
               "base_url": "http://localhost:1234/v1"})["providers"][-1]["id"]

    class Response:
        status_code = 200

    def fake_get(url, **kwargs):
        assert url == "http://localhost:1234/v1/models"
        assert kwargs == {"headers": {"Authorization": "Bearer EMPTY"},
                          "timeout": (3, 5), "allow_redirects": False}
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    assert service.test_connection(provider) == {"ok": True}


def test_custom_defaults_require_explicit_models_and_task_uses_generic_catalog(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    provider = service.add_provider({"kind": "custom", "name": "Gateway",
               "base_url": "http://localhost:1234/v1"})["providers"][-1]["id"]
    with pytest.raises(ValueError, match="quick_model"):
        service.update({"provider": provider})
    public = service.update({"provider": provider, "quick_model": "local-fast",
                             "deep_model": "local-deep"})
    assert public["provider"] == provider
    assert service.update({"language": "Chinese"})["quick_model"] == "local-fast"
    task = validate_task({"ticker": "NVDA", "date": "2026-09-22", "provider": provider,
                          "quick_model": "local-fast", "deep_model": "local-deep"},
                         {**public, "analysts": ["market"]})
    assert task["provider"] == provider
    assert task["quick_model"] == "local-fast"
    with pytest.raises(ValueError, match="provider"):
        validate_task({"ticker": "NVDA", "date": "2026-09-22", "provider": "custom:unknown"},
                      {**public, "analysts": ["market"]})


def test_legacy_defaults_stored_keys_and_environment_keys_are_joined(tmp_path, monkeypatch):
    for provider in WEB_PROVIDERS:
        if env := _CREDENTIAL_ENVS.get(provider):
            monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "ambient-google-9876")
    store = Store(tmp_path / "web.db")
    store.update_settings({"provider": "anthropic", "key:openai": "stored-openai-1234"})
    service = SettingsService(store)

    providers = service.public()["providers"]
    assert {item["id"] for item in providers} == {"anthropic", "openai", "google"}
    assert all(item["kind"] == "built_in" and item["base_url"] is None for item in providers)
    assert next(item for item in providers if item["id"] == "openai")["key"] == {
        "configured": True, "last4": "1234"
    }
    assert "ambient-google-9876" not in str(providers)
    assert "providers" not in store.get_settings()


def test_custom_providers_have_stable_distinct_ids_and_secret_free_metadata(tmp_path):
    store = Store(tmp_path / "web.db")
    service = SettingsService(store)
    first = service.add_provider({"kind": "custom", "name": "Desk", "base_url": "http://127.0.0.1:1234/v1/", "key": "secret-12345"})
    second = service.add_provider({"kind": "custom", "name": "Cloud", "base_url": "https://gateway.example/v1", "key": "other-56789"})
    entries = [item for item in second["providers"] if item["kind"] == "custom"]

    assert {item["name"] for item in entries} == {"Desk", "Cloud"}
    assert all(item["id"].startswith("custom:") for item in entries)
    assert entries[0]["id"] != entries[1]["id"]
    assert service.joined_provider(entries[0]["id"])["base_url"] == "http://127.0.0.1:1234/v1"
    assert entries[0]["key"] == {"configured": True, "last4": "2345"}
    assert "secret-12345" not in str(first) + str(second) + store.get_settings()["providers"]
    assert store.get_settings()[f"key:{entries[0]['id']}"] == "secret-12345"
    assert SettingsService(Store(tmp_path / "web.db")).public()["providers"] == second["providers"]


@pytest.mark.parametrize("name", ["", "   ", "X" * 65, "openai", "DESK"])
def test_custom_name_must_be_unique_nonempty_and_bounded(tmp_path, name):
    service = SettingsService(Store(tmp_path / "web.db"))
    service.add_provider({"kind": "custom", "name": "Desk", "base_url": "https://example.test/v1"})
    before = service.store.get_settings()
    with pytest.raises(ValueError, match="name"):
        service.add_provider({"kind": "custom", "name": name, "base_url": "https://example.test/v1"})
    assert service.store.get_settings() == before


@pytest.mark.parametrize("url", ["", "ftp://example.com", "https://", "https://user:pass@example.com", "https://example.com/?x=1", "https://example.com/#hash", "http://example.com:xyz", "http://example.com:", "http://example.com:65536", "https://example.com/a b", "https://example.com\\other/path", "https://example.com/" + "a" * 2048])
def test_custom_url_rejects_invalid_endpoints_without_mutation(tmp_path, url):
    store = Store(tmp_path / "web.db")
    with pytest.raises(ValueError, match="URL"):
        SettingsService(store).add_provider({"kind": "custom", "name": "Desk", "base_url": url})
    assert store.get_settings() == {}


def test_built_in_join_is_unique_and_name_url_cannot_be_edited(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    joined = service.add_provider({"kind": "built_in", "id": "mistral", "key": "mistral-secret"})
    assert service.joined_provider("mistral") in joined["providers"]
    with pytest.raises(ValueError, match="already joined"):
        service.add_provider({"kind": "built_in", "id": "mistral"})
    with pytest.raises(ValueError, match="supported"):
        service.add_provider({"kind": "built_in", "id": "openai_compatible"})
    with pytest.raises(ValueError, match="name|built-in"):
        service.edit_provider("mistral", {"name": "Renamed"})
    assert service.joined_provider("mistral")["key"]["last4"] == "cret"


def test_join_rejects_name_collision_with_custom_provider(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    service.add_provider({"kind": "custom", "name": "MISTRAL", "base_url": "https://gateway.example/v1"})
    with pytest.raises(ValueError, match="name"):
        service.add_provider({"kind": "built_in", "id": "mistral"})


def test_edit_validation_keeps_metadata_and_key_unchanged(tmp_path):
    store = Store(tmp_path / "web.db")
    service = SettingsService(store)
    service.add_provider({"kind": "custom", "name": "Desk", "base_url": "https://example.test/v1", "key": "before"})
    provider = service.public()["providers"][-1]["id"]
    before = store.get_settings()
    with pytest.raises(ValueError, match="URL"):
        service.edit_provider(provider, {"name": "Renamed", "base_url": "https://example.test:bad"})
    assert store.get_settings() == before
    with pytest.raises(ValueError, match="credential"):
        service.edit_provider(provider, {"key": "key\nsecret"})
    assert store.get_settings() == before


def test_legacy_settings_patch_can_join_a_builtin_provider(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    service.add_provider({"kind": "custom", "name": "Desk", "base_url": "https://example.test/v1"})
    service.update({"keys": {"mistral": "legacy-key-1234"}})
    assert service.joined_provider("mistral")["key"] == {"configured": True, "last4": "1234"}


def test_legacy_default_patch_joins_provider_without_key(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    service.add_provider({"kind": "custom", "name": "Desk", "base_url": "https://example.test/v1"})
    result = service.update({"provider": "anthropic"})
    assert result["provider"] == "anthropic"
    assert service.joined_provider("anthropic") in result["providers"]


def test_concurrent_joins_preserve_both_metadata_and_keys(tmp_path):
    barrier = threading.Barrier(2)

    class InterleavedStore(Store):
        def get_settings(self):
            result = super().get_settings()
            if threading.current_thread().name.startswith("join") and not getattr(
                threading.current_thread(), "first_read_done", False
            ):
                threading.current_thread().first_read_done = True
                barrier.wait(timeout=5)
            return result

    store = InterleavedStore(tmp_path / "web.db")
    service = SettingsService(store)
    service.add_provider({"kind": "custom", "name": "Initial", "base_url": "https://initial.example/v1"})

    def join(name):
        service.add_provider({"kind": "custom", "name": name,
                              "base_url": "https://gateway.example/v1", "key": name + "-secret"})

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="join") as executor:
        futures = [executor.submit(join, name) for name in ("Desk", "Cloud")]
        for future in futures:
            future.result(timeout=10)
    providers = service.public()["providers"]
    assert {item["name"] for item in providers if item["kind"] == "custom"} == {
        "Initial", "Desk", "Cloud"
    }
    assert all(f"key:{item['id']}" in store.get_settings()
               for item in providers if item["name"] in {"Desk", "Cloud"})


def test_task_arriving_at_delete_transaction_prevents_removal(tmp_path, monkeypatch):
    store = Store(tmp_path / "web.db")
    service = SettingsService(store)
    service.add_provider({"kind": "custom", "name": "Desk", "base_url": "https://gateway.example/v1",
                          "key": "desk-secret"})
    id = service.public()["providers"][-1]["id"]
    original = store.transaction
    injected = False

    @contextmanager
    def interleaved_transaction(*, immediate=False):
        nonlocal injected
        if immediate and not injected:
            injected = True
            store.create_task({"provider": id})
        with original(immediate=immediate) as db:
            yield db

    monkeypatch.setattr(store, "transaction", interleaved_transaction)
    with pytest.raises(ValueError, match="unfinished"):
        service.remove_provider(id)
    assert store.has_unfinished_tasks_for_provider(id)
    assert service.joined_provider(id)["key"]["configured"]


def test_edit_replaces_or_clears_key_without_leaking_it(tmp_path, monkeypatch):
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    store = Store(tmp_path / "web.db")
    service = SettingsService(store)
    service.add_provider({"kind": "built_in", "id": "mistral", "key": "old-secret-1234"})
    assert service.edit_provider("mistral", {"key": ""})["providers"][-1]["key"]["last4"] == "1234"
    replaced = service.edit_provider("mistral", {"key": "new-secret-5678"})
    assert service.joined_provider("mistral")["key"]["last4"] == "5678"
    assert "new-secret-5678" not in str(replaced)
    assert service.edit_provider("mistral", {"clear_key": True})["providers"][-1]["key"] == {
        "configured": False, "last4": None
    }
    assert "key:mistral" not in store.get_settings()
    with pytest.raises(ValueError, match="key"):
        service.edit_provider("mistral", {"key": "replacement", "clear_key": True})


@pytest.mark.parametrize("status", ["queued", "running", "interrupted"])
def test_removal_is_blocked_by_unfinished_task(tmp_path, status):
    store = Store(tmp_path / "web.db")
    service = SettingsService(store)
    service.add_provider({"kind": "custom", "name": "Desk", "base_url": "http://localhost:1234/v1", "key": "private-key"})
    provider = service.public()["providers"][-1]["id"]
    task_id = store.create_task({"provider": provider})
    with store.transaction(immediate=True) as db:
        db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    with pytest.raises(ValueError, match="unfinished"):
        service.remove_provider(provider)
    assert store.has_unfinished_tasks_for_provider(provider)
    with store.transaction(immediate=True) as db:
        db.execute("UPDATE tasks SET status='completed' WHERE id=?", (task_id,))
    assert not store.has_unfinished_tasks_for_provider(provider)
    service.remove_provider(provider)
    assert provider not in {item["id"] for item in service.public()["providers"]}
    assert f"key:{provider}" not in store.get_settings()


def test_default_provider_cannot_be_removed_and_unknown_id_is_rejected(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    with pytest.raises(ValueError, match="default"):
        service.remove_provider("openai")
    with pytest.raises(ValueError, match="joined"):
        service.joined_provider("custom:missing")
    with pytest.raises(ValueError, match="joined"):
        service.remove_provider("custom:missing")
