"""Server-only settings and credential resolution for the web workbench."""

import os
from copy import deepcopy

import requests

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients.api_key_env import PROVIDER_API_KEY_ENV
from tradingagents.llm_clients.model_catalog import MODEL_OPTIONS, get_model_options
from web.store import Store

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
    return {"configured": bool(value), "last4": value[-4:] if value else None}


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
        }

    def update(self, changes: dict) -> dict:
        if not isinstance(changes, dict) or set(changes) - _FIELDS:
            raise ValueError("unsupported setting")
        current = self.public()
        provider = changes.get("provider", current["provider"])
        if not isinstance(provider, str) or provider not in MODEL_OPTIONS:
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
            if not isinstance(value, str) or len(value) > 4096 or "\n" in value or "\r" in value:
                raise ValueError("credential must be a string without line breaks")
            if value.strip():
                update[f"key:{name}"] = value
        for name in clear_keys:
            update[f"key:{name}"] = None
        self.store.update_settings(update)
        return self.public()

    def resolve_run_config(self, params: dict) -> dict:
        """Return server-only graph config and env overlay; never persist this result."""
        if not isinstance(params, dict):
            raise ValueError("run params must be an object")
        defaults = self.public()
        provider = params.get("provider", defaults["provider"])
        if not isinstance(provider, str) or provider not in MODEL_OPTIONS:
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
        if provider_env and provider != "openai_compatible" and provider_env not in credentials:
            raise ValueError(f"credential for {provider} is not configured")
        return {"config": config, "api_key_env": credentials}

    def test_connection(self, provider: str) -> dict:
        if not isinstance(provider, str) or provider not in MODEL_OPTIONS:
            raise ValueError("provider must be supported")
        if provider in {"ollama", "openai_compatible", "azure", "bedrock"}:
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
