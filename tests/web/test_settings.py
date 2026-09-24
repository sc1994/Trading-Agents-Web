import os

import pytest
import requests

from web.settings import SettingsService
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
    assert service.test_connection("anthropic") == {
        "ok": False,
        "error": "Credential not configured",
    }
    with pytest.raises(ValueError, match="provider"):
        service.test_connection("openai_compatible")
    with pytest.raises(ValueError, match="supported"):
        service.test_connection("http://127.0.0.1")


@pytest.mark.parametrize(
    "source,url,params,payload",
    [
        (
            "fred",
            "https://api.stlouisfed.org/fred/series",
            {"series_id": "FEDFUNDS", "api_key": "saved-secret", "file_type": "json"},
            {"seriess": [{"id": "FEDFUNDS"}]},
        ),
        (
            "alpha_vantage",
            "https://www.alphavantage.co/query",
            {"function": "TIME_SERIES_DAILY", "symbol": "IBM", "apikey": "saved-secret"},
            {"Time Series (Daily)": {"2026-09-22": {"4. close": "100"}}},
        ),
    ],
)
def test_data_source_connection_uses_saved_key_and_validates_data(
    tmp_path, monkeypatch, source, url, params, payload
):
    monkeypatch.setenv("FRED_API_KEY", "environment-secret")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "environment-secret")
    service = SettingsService(Store(tmp_path / "web.db"))
    service.update({"keys": {source: "saved-secret"}})

    class Response:
        status_code = 200

        def json(self):
            return payload

    def fake_get(request_url, **kwargs):
        assert request_url == url
        assert kwargs["params"] == params
        assert kwargs["timeout"] == (3, 5)
        assert kwargs["allow_redirects"] is False
        return Response()

    monkeypatch.setattr(requests, "get", fake_get)
    assert service.test_connection(source) == {"ok": True}


@pytest.mark.parametrize("source", ["fred", "alpha_vantage"])
def test_data_source_connection_skips_missing_key(tmp_path, monkeypatch, source):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    service = SettingsService(Store(tmp_path / "web.db"))
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: pytest.fail("Unexpected request"))

    assert service.test_connection(source) == {"ok": False, "error": "Credential not configured"}


@pytest.mark.parametrize(
    "source,payload",
    [
        ("fred", {"error_message": "Invalid saved-secret"}),
        ("alpha_vantage", {"Information": "API key saved-secret rate limit reached"}),
        ("alpha_vantage", {"Error Message": "Invalid API key saved-secret"}),
        ("alpha_vantage", {"Global Quote": {}}),
    ],
)
def test_data_source_connection_rejects_error_and_empty_payloads(
    tmp_path, monkeypatch, source, payload
):
    service = SettingsService(Store(tmp_path / "web.db"))
    service.update({"keys": {source: "saved-secret"}})

    class Response:
        status_code = 200

        def json(self):
            return payload

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    result = service.test_connection(source)
    assert result == {"ok": False, "error": "Connection test failed"}
    assert "saved-secret" not in str(result)
