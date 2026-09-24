"""Server-only settings and credential resolution for the web workbench."""

import json
import os
from copy import deepcopy
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS, get_model_options
from web.store import Store

WEB_PROVIDERS = frozenset(MODEL_OPTIONS) - {"openai_compatible"}

_PROVIDER_NAMES = {
    "openai": "OpenAI", "google": "Google Gemini", "xai": "xAI",
    "qwen-cn": "Qwen China", "glm-cn": "GLM China",
    "minimax-cn": "MiniMax China", "nvidia": "NVIDIA NIM",
    "bedrock": "Amazon Bedrock", "openrouter": "OpenRouter",
}

_CREDENTIAL_ENVS = {
    **{provider: env for provider, env in PROVIDER_API_KEY_ENV.items() if env},
    "fred": "FRED_API_KEY",
    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
}
_FIELDS = {
    "provider",
    "quick_model",
    "deep_model",
    "language",
    "checkpoint_enabled",
    "keys",
    "clear_keys",
}


def _masked(value: str | None) -> dict:
    return {"configured": bool(value), "last4": value[-4:] if value and len(value) > 4 else None}


def _built_in(provider: str) -> dict:
    return {"id": provider, "name": _PROVIDER_NAMES.get(provider, provider.title()),
            "kind": "built_in", "base_url": None}


def _provider_name(value: object, providers: list[dict], *, excluding: str = "") -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 64:
        raise ValueError("provider name must be nonempty and at most 64 characters")
    name = value.strip()
    if any(item["id"] != excluding and item["name"].casefold() == name.casefold()
           for item in providers):
        raise ValueError("provider name is already joined")
    return name


def _base_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value
    ) or "?" in value or "#" in value or "\\" in value:
        raise ValueError("invalid provider URL")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.port is not None and not 1 <= parsed.port <= 65535
                or parsed.query or parsed.fragment):
            raise ValueError("invalid provider URL")
    except ValueError as exc:
        raise ValueError("invalid provider URL") from exc
    return value.rstrip("/")


def _credential(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 4096 or "\n" in value or "\r" in value:
        raise ValueError("credential must be a string without line breaks")
    return value if value.strip() else None


def _model_id(provider: str, mode: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 128:
        raise ValueError(f"{mode}_model must be a supported model")
    model = value.strip()
    options = {option for _, option in get_model_options(provider, mode)}
    if model == "custom" or (model not in options and "custom" not in options):
        raise ValueError(f"{mode}_model must be a supported model")
    return model


class SettingsService:
    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def _providers(saved: dict[str, str]) -> list[dict]:
        if "providers" in saved:
            return json.loads(saved["providers"])
        # Legacy credentials may be stored or supplied by environment. A read
        # does not persist ambient credentials or automatically rejoin deletions.
        ids = {saved.get("provider", "openai")}
        ids.update(provider for provider in WEB_PROVIDERS if saved.get(f"key:{provider}"))
        ids.update(provider for provider in WEB_PROVIDERS
                   if (env := _CREDENTIAL_ENVS.get(provider)) and os.environ.get(env))
        return [_built_in(provider) for provider in sorted(ids) if provider in WEB_PROVIDERS]

    @staticmethod
    def _public_providers(providers: list[dict], saved: dict[str, str]) -> list[dict]:
        return [
            {**item, "key": _masked(saved.get(f"key:{item['id']}") or
              (os.environ.get(_CREDENTIAL_ENVS[item["id"]])
               if item["kind"] == "built_in" and item["id"] in _CREDENTIAL_ENVS else None))}
            for item in providers
        ]

    def joined_provider(self, id: str) -> dict:
        saved = self.store.get_settings()
        for item in self._public_providers(self._providers(saved), saved):
            if item["id"] == id:
                return item
        raise ValueError("provider is not joined")

    def add_provider(self, body: dict) -> dict:
        if not isinstance(body, dict) or body.get("kind") not in ("built_in", "custom"):
            raise ValueError("provider kind must be supported")
        saved = self.store.get_settings()
        providers = self._providers(saved)
        if body["kind"] == "built_in":
            if set(body) - {"kind", "id", "key"}:
                raise ValueError("unsupported provider field")
            id = body.get("id")
            if not isinstance(id, str) or id not in WEB_PROVIDERS:
                raise ValueError("provider must be supported")
            if any(item["id"] == id for item in providers):
                raise ValueError("provider is already joined")
            item = _built_in(id)
            _provider_name(item["name"], providers)
        else:
            if set(body) - {"kind", "name", "base_url", "key"}:
                raise ValueError("unsupported provider field")
            item = {"id": f"custom:{uuid4()}", "kind": "custom",
                    "name": _provider_name(body.get("name"), providers),
                    "base_url": _base_url(body.get("base_url"))}
        changes = {"providers": json.dumps([*providers, item], ensure_ascii=False)}
        if "key" in body and (key := _credential(body["key"])):
            changes[f"key:{item['id']}"] = key
        self.store.update_settings(changes)
        return self.public()

    def edit_provider(self, id: str, body: dict) -> dict:
        if not isinstance(body, dict) or set(body) - {"name", "base_url", "key", "clear_key"}:
            raise ValueError("unsupported provider field")
        saved = self.store.get_settings()
        providers = self._providers(saved)
        item = next((item for item in providers if item["id"] == id), None)
        if item is None:
            raise ValueError("provider is not joined")
        if item["kind"] == "built_in" and ({"name", "base_url"} & body.keys()):
            raise ValueError("built-in provider name and URL cannot be changed")
        if "name" in body:
            item["name"] = _provider_name(body["name"], providers, excluding=id)
        if "base_url" in body:
            item["base_url"] = _base_url(body["base_url"])
        if "clear_key" in body and type(body["clear_key"]) is not bool:
            raise ValueError("clear_key must be a boolean")
        if body.get("clear_key") and "key" in body:
            raise ValueError("key replacement and clear_key are mutually exclusive")
        changes = {"providers": json.dumps(providers, ensure_ascii=False)}
        if "key" in body and (key := _credential(body["key"])):
            changes[f"key:{id}"] = key
        if body.get("clear_key"):
            changes[f"key:{id}"] = None
        self.store.update_settings(changes)
        return self.public()

    def remove_provider(self, id: str) -> dict:
        saved = self.store.get_settings()
        providers = self._providers(saved)
        if not any(item["id"] == id for item in providers):
            raise ValueError("provider is not joined")
        if saved.get("provider", "openai") == id:
            raise ValueError("cannot remove the default provider")
        if self.store.has_unfinished_tasks_for_provider(id):
            raise ValueError("cannot remove provider used by unfinished tasks")
        self.store.update_settings({
            "providers": json.dumps([item for item in providers if item["id"] != id],
                                    ensure_ascii=False),
            f"key:{id}": None,
        })
        return self.public()

    def public(self) -> dict:
        saved = self.store.get_settings()
        provider = saved.get("provider", "openai")
        return {
            "provider": provider,
            "quick_model": saved.get("quick_model", get_model_options(provider, "quick")[0][1]),
            "deep_model": saved.get("deep_model", get_model_options(provider, "deep")[0][1]),
            "language": saved.get("language", "English"),
            "checkpoint_enabled": saved.get("checkpoint_enabled", "true") == "true",
            "keys": {
                name: _masked(saved.get(f"key:{name}") or os.environ.get(env))
                for name, env in _CREDENTIAL_ENVS.items()
            },
            "providers": self._public_providers(self._providers(saved), saved),
        }

    def update(self, changes: dict) -> dict:
        if not isinstance(changes, dict) or set(changes) - _FIELDS:
            raise ValueError("unsupported setting")
        current = self.public()
        provider = changes.get("provider", current["provider"])
        if not isinstance(provider, str) or provider not in WEB_PROVIDERS:
            raise ValueError("provider must be supported")
        update = {}
        if "provider" in changes:
            update["provider"] = provider
        for field, mode in (("quick_model", "quick"), ("deep_model", "deep")):
            fallback = next(
                (value for _, value in get_model_options(provider, mode) if value != "custom"), None
            )
            model = changes.get(
                field, fallback if provider != current["provider"] else current[field]
            )
            model = _model_id(provider, mode, model)
            if field in changes or provider != current["provider"]:
                update[field] = model
        if "language" in changes:
            language = changes["language"]
            if not isinstance(language, str) or not language.strip() or len(language.strip()) > 64:
                raise ValueError("language must be nonempty and at most 64 characters")
            update["language"] = language.strip()
        if "checkpoint_enabled" in changes:
            enabled = changes["checkpoint_enabled"]
            if type(enabled) is not bool:
                raise ValueError("checkpoint_enabled must be a boolean")
            update["checkpoint_enabled"] = "true" if enabled else "false"
        keys = changes.get("keys", {})
        clear_keys = changes.get("clear_keys", [])
        if not isinstance(keys, dict) or not isinstance(clear_keys, list):
            raise ValueError("keys and clear_keys must have valid shapes")
        if set(keys) - _CREDENTIAL_ENVS.keys() or any(
            not isinstance(name, str) or name not in _CREDENTIAL_ENVS for name in clear_keys
        ):
            raise ValueError("unsupported credential")
        for name, value in keys.items():
            if key := _credential(value):
                update[f"key:{name}"] = key
        for name in clear_keys:
            update[f"key:{name}"] = None
        newly_joined = [name for name in keys if name in WEB_PROVIDERS
                        and f"key:{name}" in update]
        providers = self._providers(self.store.get_settings())
        for name in newly_joined:
            if not any(item["id"] == name for item in providers):
                item = _built_in(name)
                _provider_name(item["name"], providers)
                providers.append(item)
                update["providers"] = json.dumps(providers, ensure_ascii=False)
        self.store.update_settings(update)
        return self.public()

    def resolve_run_config(self, params: dict) -> dict:
        """Return server-only graph config and env overlay; never persist this result."""
        if not isinstance(params, dict):
            raise ValueError("run params must be an object")
        defaults = self.public()
        provider = params.get("provider", defaults["provider"])
        if not isinstance(provider, str) or provider not in WEB_PROVIDERS:
            raise ValueError("provider must be supported")
        models = {}
        for field, mode in (("quick_model", "quick"), ("deep_model", "deep")):
            model = params.get(field, defaults[field])
            models[field] = _model_id(provider, mode, model)
        config = deepcopy(DEFAULT_CONFIG)
        config.update(
            {
                "llm_provider": provider,
                "quick_think_llm": models["quick_model"],
                "deep_think_llm": models["deep_model"],
                "backend_url": None,
                "output_language": params.get("language", defaults["language"]),
                "checkpoint_enabled": params.get(
                    "checkpoint_enabled", defaults["checkpoint_enabled"]
                ),
            }
        )
        if not isinstance(config["output_language"], str) or not config["output_language"].strip():
            raise ValueError("language must be nonempty")
        if type(config["checkpoint_enabled"]) is not bool:
            raise ValueError("checkpoint_enabled must be a boolean")
        for key in ("max_debate_rounds", "max_risk_discuss_rounds"):
            if key in params:
                count = params[key]
                if type(count) is not int or not 1 <= count <= 5:
                    raise ValueError(f"{key} must be between 1 and 5")
                config[key] = count
        saved = self.store.get_settings()
        names = (provider, "fred", "alpha_vantage")
        credentials = {
            _CREDENTIAL_ENVS[name]: value
            for name in names
            if name in _CREDENTIAL_ENVS
            if (value := saved.get(f"key:{name}") or os.environ.get(_CREDENTIAL_ENVS[name]))
        }
        provider_env = PROVIDER_API_KEY_ENV.get(provider)
        if provider_env and provider_env not in credentials:
            raise ValueError(f"credential for {provider} is not configured")
        return {"config": config, "api_key_env": credentials}

    def test_connection(self, provider: str) -> dict:
        if not isinstance(provider, str) or provider not in WEB_PROVIDERS:
            raise ValueError("provider must be supported")
        if provider in {"ollama", "azure", "bedrock"}:
            return {"ok": False, "error": "Connection test unavailable for this provider"}
        env = PROVIDER_API_KEY_ENV.get(provider)
        saved = self.store.get_settings()
        credential = saved.get(f"key:{provider}") or (os.environ.get(env) if env else None)
        if not credential:
            return {"ok": False, "error": "Credential not configured"}
        if provider == "anthropic":
            url = "https://api.anthropic.com/v1/models"
            headers = {"x-api-key": credential, "anthropic-version": "2023-06-01"}
        elif provider == "google":
            url = "https://generativelanguage.googleapis.com/v1beta/models"
            headers = {"x-goog-api-key": credential}
        else:
            from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS

            base_url = OPENAI_COMPATIBLE_PROVIDERS[provider].base_url or "https://api.openai.com/v1"
            if not base_url.startswith("https://"):
                return {"ok": False, "error": "Connection test unavailable for this provider"}
            url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {credential}"}
        try:
            response = requests.get(url, headers=headers, timeout=(3, 5), allow_redirects=False)
            if 200 <= response.status_code < 300:
                return {"ok": True}
        except Exception:
            pass
        return {"ok": False, "error": "Connection test failed"}
