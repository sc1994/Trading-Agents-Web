"""Normalize an analysis request into an allowlisted, JSON-safe task snapshot."""

import re
from datetime import date, datetime, timedelta, timezone

from cli.models import AnalystType, AssetType
from cli.utils import (
    detect_asset_type,
    filter_analysts_for_asset_type,
    is_valid_ticker_input,
    normalize_ticker_symbol,
)
from tradingagents.llm_clients.model_catalog import get_model_options
from web.settings import WEB_PROVIDERS

DEPTH_ROUNDS = {"quick": 1, "standard": 2, "deep": 3}
_MAX_ROUNDS = 5


def _round_count(raw: dict, name: str, depth_rounds: int) -> int:
    count = raw.get(name, depth_rounds)
    if type(count) is not int or not 1 <= count <= _MAX_ROUNDS:
        raise ValueError(f"{name} must be between 1 and {_MAX_ROUNDS}")
    return count


def _model(raw: dict, defaults: dict, provider: str, field: str, mode: str) -> str:
    model = raw.get(field, defaults.get(field))
    if not isinstance(model, str) or not model.strip() or len(model.strip()) > 128:
        raise ValueError(f"{field} must be a supported model")
    model = model.strip()
    options = [value for _, value in get_model_options(provider, mode)]
    if model == "custom" or (model not in options and "custom" not in options):
        raise ValueError(f"{field} must be a supported model")
    return model


def validate_task(raw: dict, defaults: dict) -> dict:
    """Validate a request without carrying labels, credentials, or unknown fields forward."""
    if not isinstance(raw, dict) or not isinstance(defaults, dict):
        raise ValueError("task and defaults must be objects")
    ticker = raw.get("ticker")
    if not isinstance(ticker, str) or not ticker.strip() or not is_valid_ticker_input(ticker):
        raise ValueError("ticker must be a valid stock or asset code")
    ticker = normalize_ticker_symbol(ticker)

    date_text = raw.get("date")
    if not isinstance(date_text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
        raise ValueError("date must be a valid ISO calendar date")
    try:
        analysis_date = date.fromisoformat(date_text)
    except ValueError as exc:
        raise ValueError("date must be a valid ISO calendar date") from exc
    # Browsers submit local calendar dates; UTC+14 can already be on tomorrow.
    # A one-day UTC allowance accepts local today without trusting a client zone.
    if analysis_date > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise ValueError("date must not be in the future")

    asset = raw.get("asset_type", "auto")
    detected_asset_type = detect_asset_type(ticker)
    if asset == "auto":
        asset_type = detected_asset_type
    else:
        try:
            asset_type = AssetType(asset)
        except (ValueError, TypeError) as exc:
            raise ValueError("asset_type must be stock, crypto, or auto") from exc
        if asset_type != detected_asset_type:
            raise ValueError("asset_type conflicts with the ticker")

    requested_analysts = raw.get("analysts", defaults.get("analysts", []))
    if not isinstance(requested_analysts, list) or not requested_analysts:
        raise ValueError("analysts must contain at least one analyst")
    try:
        analysts = [AnalystType(analyst) for analyst in requested_analysts]
    except (ValueError, TypeError) as exc:
        raise ValueError("analysts must contain known analyst types") from exc
    allowed = filter_analysts_for_asset_type(analysts, asset_type)
    if "analysts" in raw and allowed != analysts:
        raise ValueError("analysts contain a type unsupported for this asset")
    if not allowed:
        raise ValueError("analysts must contain at least one supported analyst")

    depth = raw.get("depth", "standard")
    if not isinstance(depth, str) or depth not in DEPTH_ROUNDS:
        raise ValueError("depth must be quick, standard, or deep")
    language = raw.get("language", defaults.get("language", "English"))
    if not isinstance(language, str) or not language.strip() or len(language.strip()) > 64:
        raise ValueError("language must be nonempty and at most 64 characters")
    provider = raw.get("provider", defaults.get("provider"))
    if not isinstance(provider, str):
        raise ValueError("provider must be supported")
    provider = provider.strip().lower()
    if provider not in WEB_PROVIDERS:
        raise ValueError("provider must be supported")
    try:
        get_model_options(provider, "quick")
    except KeyError as exc:
        raise ValueError("provider must be supported") from exc

    return {
        "ticker": ticker,
        "date": analysis_date.isoformat(),
        "asset_type": asset_type.value,
        "analysts": [analyst.value for analyst in allowed],
        "depth": depth,
        "language": language.strip(),
        "provider": provider,
        "quick_model": _model(raw, defaults, provider, "quick_model", "quick"),
        "deep_model": _model(raw, defaults, provider, "deep_model", "deep"),
        "max_debate_rounds": _round_count(raw, "max_debate_rounds", DEPTH_ROUNDS[depth]),
        "max_risk_discuss_rounds": _round_count(raw, "max_risk_discuss_rounds", DEPTH_ROUNDS[depth]),
    }
