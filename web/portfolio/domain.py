"""Validated financial inputs and deterministic observation rules."""

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext


class DomainError(ValueError):
    def __init__(self, code: str, field: str = "body"):
        self.code, self.field = code, field
        super().__init__(code)


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def positive_decimal(value, field: str) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?", value)
        or Decimal(value) <= 0
    ):
        raise DomainError("invalid_decimal", field)
    return decimal_text(Decimal(value))


def iso_date(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DomainError("invalid_date", field)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise DomainError("invalid_date", field) from None
    return value


def reason_text(value) -> str:
    if not isinstance(value, str) or len(value) > 2000:
        raise DomainError("invalid_reason", "reason")
    return value.strip()


def validate_plan(raw: dict) -> dict:
    defaults = {
        "reason": "",
        "lower": None,
        "upper": None,
        "review_date": None,
        "cost_pending": False,
    }
    if not isinstance(raw, dict) or set(raw) - {"symbol", "horizon", "shares", "cost", *defaults}:
        raise DomainError("invalid_fields")
    value = {**defaults, **raw}
    if not isinstance(value.get("symbol"), str) or not re.fullmatch(
        r"\d{6}\.(?:SS|SZ|BJ)", value["symbol"]
    ):
        raise DomainError("unsupported_market", "symbol")
    if value.get("horizon") not in {"short", "medium", "long"}:
        raise DomainError("invalid_horizon", "horizon")
    if type(value.get("shares")) is not int or not 1 <= value["shares"] <= 1000000000:
        raise DomainError("invalid_shares", "shares")
    value["cost"] = positive_decimal(value.get("cost"), "cost")
    value["reason"] = reason_text(value["reason"])
    if type(value["cost_pending"]) is not bool:
        raise DomainError("invalid_boolean", "cost_pending")
    for field in ("lower", "upper"):
        if value[field] is not None:
            value[field] = positive_decimal(value[field], field)
    if value["lower"] and value["upper"] and Decimal(value["lower"]) >= Decimal(value["upper"]):
        raise DomainError("invalid_bounds", "lower")
    if value["review_date"] is not None:
        iso_date(value["review_date"], "review_date")
    return value


def evaluate(plan: dict, quote: dict | None, target_date: str) -> dict:
    quality, error = "valid", None
    if plan["cost_pending"]:
        quality, error = "cost_pending", "cost_pending"
    elif not quote:
        quality, error = "missing", "missing_quote"
    elif quote.get("error_code"):
        error = quote["error_code"]
        quality = "stale" if error == "stale_quote" else "missing"
    elif quote.get("price_date") != target_date:
        quality, error = "stale", "stale_quote"
    elif quote.get("symbol") != plan["symbol"] or quote.get("currency") != "CNY":
        quality, error = "missing", "invalid_quote"
    else:
        try:
            positive_decimal(quote.get("close"), "close")
        except DomainError:
            quality, error = "missing", "invalid_quote"
    signals, value, pnl = [], None, None
    if quality == "valid":
        close = Decimal(quote["close"])
        if plan.get("lower") and close <= Decimal(plan["lower"]):
            signals.append("lower")
        if plan.get("upper") and close >= Decimal(plan["upper"]):
            signals.append("upper")
        with localcontext() as ctx:
            ctx.prec = 40
            value = decimal_text(close * plan["shares"])
            pnl = decimal_text((close - Decimal(plan["cost"])) * plan["shares"])
    if plan.get("review_date") and target_date >= plan["review_date"]:
        signals.append("review_date")
    state = (
        "review"
        if signals
        else "unavailable"
        if quality != "valid"
        else (
            "not_triggered"
            if any(plan.get(field) for field in ("lower", "upper", "review_date"))
            else "no_conditions"
        )
    )
    return {
        "plan_id": plan["id"],
        "revision": plan["revision"],
        "plan_snapshot": deepcopy(plan),
        "target_date": target_date,
        "quote": deepcopy(quote),
        "quality": quality,
        "error_code": error,
        "signals": signals,
        "state": state,
        "market_value": value,
        "unrealized_pnl": pnl,
    }


def summarize(plans: list[dict], results: list[dict], concentration_limit: str | None) -> dict:
    incomplete = {
        "complete": False,
        "market_value": None,
        "unrealized_pnl": None,
        "concentrations": [],
    }
    active = [p for p in plans if p["status"] == "active"]
    if not active:
        return {"complete": True, "market_value": "0", "unrealized_pnl": "0", "concentrations": []}
    matched = {r["plan_id"]: r for r in results}
    selected = []
    for p in active:
        r = matched.get(p["id"])
        if not r or r["revision"] != p["revision"] or r["quality"] != "valid":
            return incomplete
        selected.append(r)
    if len({r["target_date"] for r in selected}) != 1:
        return incomplete
    with localcontext() as ctx:
        ctx.prec = 40
        total = sum((Decimal(r["market_value"]) for r in selected), Decimal(0))
        pnl = sum((Decimal(r["unrealized_pnl"]) for r in selected), Decimal(0))
        stocks = {}
        for r in selected:
            symbol = r["plan_snapshot"]["symbol"]
            stocks[symbol] = stocks.get(symbol, Decimal(0)) + Decimal(r["market_value"])
        concentrations = []
        for symbol, value in sorted(stocks.items(), key=lambda item: (-item[1], item[0])):
            percent = value / total * 100
            concentrations.append(
                {
                    "symbol": symbol,
                    "percent": decimal_text(percent.quantize(Decimal("0.01"))),
                    "triggered": concentration_limit is not None
                    and percent >= Decimal(concentration_limit),
                }
            )
    return {
        "complete": True,
        "market_value": decimal_text(total),
        "unrealized_pnl": decimal_text(pnl),
        "concentrations": concentrations,
    }
