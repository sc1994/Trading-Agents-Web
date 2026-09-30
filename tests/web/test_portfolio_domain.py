from copy import deepcopy

import pytest

from web.portfolio.domain import DomainError, evaluate, summarize, validate_plan


def plan(**changes):
    return {
        "id": "p1",
        "symbol": "600000.SS",
        "horizon": "short",
        "shares": 1000,
        "cost": "10.2",
        "reason": "fixture",
        "lower": "10",
        "upper": None,
        "review_date": None,
        "cost_pending": False,
        "revision": 1,
        "status": "active",
        **changes,
    }


def quote(**changes):
    return {
        "symbol": "600000.SS",
        "price_date": "2026-09-29",
        "close": "10",
        "currency": "CNY",
        "source": "fixture",
        "fetched_at": "2026-09-29T09:00:00Z",
        "error_code": None,
        **changes,
    }


def test_lower_equality_triggers_review_without_float_error():
    result = evaluate(plan(), quote(), "2026-09-29")
    assert result["state"] == "review"
    assert result["signals"] == ["lower"]
    assert result["unrealized_pnl"] == "-200"
    assert result["market_value"] == "10000"


def test_upper_and_date_conditions_are_inclusive():
    result = evaluate(plan(lower=None, upper="10", review_date="2026-09-29"), quote(), "2026-09-29")
    assert result["signals"] == ["upper", "review_date"]


def test_missing_quote_preserves_date_signal_without_claiming_valid_prices():
    result = evaluate(plan(review_date="2026-09-29"), None, "2026-09-29")
    assert result["state"] == "review"
    assert result["quality"] == "missing"
    assert result["signals"] == ["review_date"]
    assert result["unrealized_pnl"] is None


def test_explicit_fetch_failure_keeps_its_reason_without_becoming_stale():
    result = evaluate(
        plan(), quote(price_date=None, close=None, error_code="market_timeout"), "2026-09-29"
    )
    assert result["quality"] == "missing"
    assert result["error_code"] == "market_timeout"


@pytest.mark.parametrize(
    "changes",
    [
        {"price_date": "2026-09-28"},
        {"symbol": "000001.SZ"},
        {"currency": "USD"},
        {"close": "NaN"},
        {"close": "0"},
        {"close": "inf"},
        {"error_code": "suspended"},
    ],
)
def test_invalid_quotes_never_trigger_price_rules(changes):
    result = evaluate(plan(), quote(**changes), "2026-09-29")
    assert result["state"] == "unavailable"
    assert result["market_value"] is None
    assert result["signals"] == []


def test_pending_cost_pauses_price_checks():
    result = evaluate(plan(cost_pending=True), quote(), "2026-09-29")
    assert result["quality"] == "cost_pending"
    assert result["state"] == "unavailable"


def test_no_conditions_is_not_a_safety_claim_and_snapshot_is_independent():
    original = plan(lower=None)
    result = evaluate(original, quote(), "2026-09-29")
    original["shares"] = 20
    assert result["state"] == "no_conditions"
    assert result["plan_snapshot"]["shares"] == 1000


@pytest.mark.parametrize(
    "field,value",
    [
        ("cost", "1e2"),
        ("cost", "NaN"),
        ("cost", "0"),
        ("cost", "-1"),
        ("cost", "1000000000000"),
        ("cost", "1.1234567"),
        ("cost", 10.2),
        ("shares", True),
        ("shares", 0),
        ("shares", 1000000001),
        ("shares", 1.5),
        ("horizon", "forever"),
        ("lower", "11"),
        ("review_date", "2026-02-30"),
        ("cost_pending", "false"),
        ("reason", "x" * 2001),
    ],
)
def test_plan_validation_rejects_invalid_or_ambiguous_values(field, value):
    raw = {
        "symbol": "600000.SS",
        "horizon": "short",
        "shares": 1,
        "cost": "10",
        "lower": "9",
        "upper": "10",
        field: value,
    }
    with pytest.raises(DomainError):
        validate_plan(raw)


def test_validation_applies_defaults_and_normalizes_decimal_strings():
    result = validate_plan(
        {"symbol": "600000.SS", "horizon": "long", "shares": 5, "cost": "10.200000"}
    )
    assert result["cost"] == "10.2"
    assert result["lower"] is None
    assert result["cost_pending"] is False


def test_validation_rejects_extra_fields():
    with pytest.raises(DomainError):
        validate_plan(
            {
                "symbol": "600000.SS",
                "horizon": "long",
                "shares": 5,
                "cost": "10",
                "api_key": "not-a-real-key",
            }
        )


def test_summary_groups_same_stock_and_uses_only_entered_holdings():
    plans = [
        plan(),
        plan(id="p2", horizon="long", shares=2000, cost="9.1"),
        plan(id="p3", symbol="000001.SZ", shares=1000, cost="10"),
    ]
    results = [evaluate(p, quote(symbol=p["symbol"]), "2026-09-29") for p in plans]
    summary = summarize(plans, results, "70")
    assert summary["complete"] is True
    assert summary["market_value"] == "40000"
    assert summary["unrealized_pnl"] == "1600"
    assert summary["concentrations"] == [
        {"symbol": "600000.SS", "percent": "75", "triggered": True},
        {"symbol": "000001.SZ", "percent": "25", "triggered": False},
    ]


def test_summary_suppresses_mixed_date_and_obsolete_results():
    original = plan()
    result = evaluate(original, quote(), "2026-09-29")
    updated = deepcopy(original)
    updated["revision"] = 2
    for plans, results in [
        ([updated], [result]),
        ([original], []),
        (
            [original, plan(id="p2")],
            [result, evaluate(plan(id="p2"), quote(price_date="2026-09-28"), "2026-09-28")],
        ),
    ]:
        summary = summarize(plans, results, "30")
        assert summary["complete"] is False
        assert summary["concentrations"] == []
        assert summary["market_value"] is None
