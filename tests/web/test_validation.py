import json
from datetime import date, timedelta

import pytest

from web.validation import validate_task


@pytest.fixture
def defaults():
    return {
        "provider": "openai", "quick_model": "gpt-5.6-luna",
        "deep_model": "gpt-5.6", "analysts": ["market"], "language": "English",
    }


def test_name_is_not_submitted_as_ticker(defaults):
    with pytest.raises(ValueError, match="ticker"):
        validate_task({"ticker": "NVIDIA Corporation", "date": "2026-09-22"}, defaults)


def test_validation_normalizes_and_allowlists_config(defaults):
    config = validate_task({
        "ticker": " btcusd ", "date": "2026-09-22", "depth": "deep",
        "name": "Bitcoin", "api_key": "user secret", "extra": {"api_key": "other secret"},
        "analysts": ["market", "news"], "max_debate_rounds": 4,
    }, {**defaults, "api_key": "default secret"})
    assert config == {
        "ticker": "BTC-USD", "date": "2026-09-22", "asset_type": "crypto",
        "analysts": ["market", "news"], "depth": "deep", "language": "English",
        "provider": "openai", "quick_model": "gpt-5.6-luna", "deep_model": "gpt-5.6",
        "max_debate_rounds": 4, "max_risk_discuss_rounds": 3,
    }
    json.dumps(config)


@pytest.mark.parametrize("value", ["", " ", "a b", 4, None])
def test_validation_rejects_invalid_ticker(value, defaults):
    with pytest.raises(ValueError, match="ticker"):
        validate_task({"ticker": value, "date": "2026-09-22"}, defaults)


@pytest.mark.parametrize("value", ["", "2026-02-30", "20260922", "tomorrow"])
def test_validation_rejects_empty_or_malformed_date(value, defaults):
    with pytest.raises(ValueError, match="date"):
        validate_task({"ticker": "AAPL", "date": value}, defaults)


def test_validation_rejects_future_date(defaults):
    with pytest.raises(ValueError, match="date"):
        validate_task({"ticker": "AAPL", "date": (date.today() + timedelta(days=1)).isoformat()}, defaults)


@pytest.mark.parametrize("override,field", [
    ({"provider": "unknown"}, "provider"),
    ({"quick_model": "wrong-model"}, "quick_model"),
    ({"deep_model": "wrong-model"}, "deep_model"),
    ({"depth": "extreme"}, "depth"),
    ({"depth": []}, "depth"),
    ({"analysts": []}, "analysts"),
    ({"analysts": ["unknown"]}, "analysts"),
    ({"max_debate_rounds": 0}, "max_debate_rounds"),
    ({"max_risk_discuss_rounds": 6}, "max_risk_discuss_rounds"),
    ({"max_debate_rounds": True}, "max_debate_rounds"),
    ({"asset_type": "forex"}, "asset_type"),
])
def test_validation_rejects_invalid_options(override, field, defaults):
    with pytest.raises(ValueError, match=field):
        validate_task({"ticker": "AAPL", "date": "2026-09-22", **override}, defaults)


def test_crypto_cannot_select_fundamentals(defaults):
    with pytest.raises(ValueError, match="analysts"):
        validate_task({"ticker": "BTC-USD", "date": "2026-09-22",
                       "analysts": ["fundamentals"]}, defaults)


@pytest.mark.parametrize("ticker,claimed_type,analysts", [
    ("BTC-USD", "stock", ["fundamentals"]),
    ("AAPL", "crypto", ["market"]),
])
def test_explicit_asset_type_cannot_conflict_with_ticker(ticker, claimed_type, analysts, defaults):
    with pytest.raises(ValueError, match="asset_type"):
        validate_task({"ticker": ticker, "asset_type": claimed_type,
                       "date": "2026-09-22", "analysts": analysts}, defaults)


def test_crypto_filters_incompatible_default_analysts(defaults):
    config = validate_task({"ticker": "BTC-USD", "date": "2026-09-22"},
                           {**defaults, "analysts": ["market", "fundamentals"]})
    assert config["analysts"] == ["market"]


@pytest.mark.parametrize("depth,rounds", [("quick", 1), ("standard", 2), ("deep", 3)])
def test_depth_maps_to_both_round_counts(depth, rounds, defaults):
    config = validate_task({"ticker": "AAPL", "date": "2026-09-22", "depth": depth}, defaults)
    assert (config["max_debate_rounds"], config["max_risk_discuss_rounds"]) == (rounds, rounds)
