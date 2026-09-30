import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from time import monotonic

import pytest

from web.portfolio.domain import DomainError
from web.portfolio.market import AShareMarket, BoundedFetch


def catalog(exchange=None):
    value = {
        "instruments": [
            {
                "symbol": "600000.SS",
                "name": "Fixture SH",
                "exchange": "SH",
                "currency": "CNY",
                "security_type": "A_SHARE",
            },
            {
                "symbol": "000001.SZ",
                "name": "Fixture SZ",
                "exchange": "SZ",
                "currency": "CNY",
                "security_type": "A_SHARE",
            },
            {
                "symbol": "920001.BJ",
                "name": "Fixture BJ",
                "exchange": "BJ",
                "currency": "CNY",
                "security_type": "A_SHARE",
            },
        ]
    }
    if exchange:
        value["instruments"] = [i for i in value["instruments"] if i["exchange"] == exchange]
    return value


def catalog_call(operation, payload, timeout):
    return catalog(payload["exchange"])


def test_stale_close_is_not_a_valid_quote(tmp_path):
    market = AShareMarket(
        tmp_path,
        call=lambda *args: {
            "symbol": "600000.SS",
            "price_date": "2026-09-28",
            "close": "10",
            "currency": "CNY",
            "source": "fixture",
        },
    )
    result = market.quote(catalog()["instruments"][0], "2026-09-29")
    assert result["error_code"] == "stale_quote"


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "000001.SZ"},
        {"close": "NaN"},
        {"close": "0"},
        {"currency": "USD"},
    ],
)
def test_malformed_quotes_cannot_be_used(tmp_path, changes):
    market = AShareMarket(
        tmp_path,
        call=lambda *args: {
            "symbol": "600000.SS",
            "price_date": "2026-09-29",
            "close": "10",
            "currency": "CNY",
            **changes,
        },
    )
    result = market.quote(catalog()["instruments"][0], "2026-09-29")
    assert result["error_code"] == "invalid_quote"


def test_identity_requires_catalog_not_prefix_guessing(tmp_path):
    market = AShareMarket(tmp_path, call=catalog_call)
    market.refresh_catalog()
    assert market.resolve("600000")["symbol"] == "600000.SS"
    assert market.resolve("920001.BJ")["exchange"] == "BJ"
    for symbol, code in [
        ("600999.SS", "instrument_unverified"),
        ("NVDA", "unsupported_market"),
        ("900901.SS", "instrument_unverified"),
    ]:
        with pytest.raises(DomainError, match=code):
            market.resolve(symbol)


def test_partial_catalog_never_overwrites_complete_cache(tmp_path):
    now = datetime.now(timezone.utc)
    market = AShareMarket(tmp_path, call=catalog_call, clock=lambda: now)
    market.refresh_catalog()
    market.resolve("600000")
    path = tmp_path / "portfolio-market" / "catalog-sh.json"
    before = path.read_bytes()
    bad = AShareMarket(
        tmp_path, call=lambda *args: {"instruments": []}, clock=lambda: now + timedelta(days=2)
    )
    bad.refresh_catalog("SH")
    assert path.read_bytes() == before
    assert bad.resolve("600000.SS")["catalog_state"] == "stale"


def test_outage_does_not_silently_validate_new_identity(tmp_path):
    def unavailable(*args):
        raise DomainError("market_timeout")

    with pytest.raises(DomainError, match="catalog_unavailable"):
        AShareMarket(tmp_path, call=unavailable).resolve("600000")


def test_calendar_does_not_claim_unpublished_future_coverage(tmp_path):
    market = AShareMarket(tmp_path, call=lambda *args: {"dates": ["2026-09-28", "2026-09-29"]})
    value = market.calendar()
    assert value["covered_until"] == "2026-09-29"
    assert value["covered_from"] == "2026-09-28"


def test_search_supports_verified_bj_and_rejects_non_a_share(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "web.portfolio.market.search_symbols",
        lambda *args, **kwargs: {
            "results": [{"symbol": "NVDA", "name": "NVIDIA", "exchange": "US", "type": "EQUITY"}],
            "unavailable": False,
        },
    )
    market = AShareMarket(tmp_path, call=catalog_call)
    market.refresh_catalog()
    assert market.search("920001")["results"][0]["supported"] is True
    result = market.search("NVDA")["results"][0]
    assert result["supported"] is False
    assert result["support_code"] == "unsupported_market"


def test_fetch_child_timeout_is_reaped():
    fetch = BoundedFetch(command=[sys.executable, "-c", "import time; time.sleep(30)"])
    with pytest.raises(DomainError, match="market_timeout"):
        fetch("calendar", {}, 0.05)
    assert not fetch._children


def test_fetch_transport_preserves_dependency_error():
    fetch = BoundedFetch(
        command=[sys.executable, "-c", 'print(\'{"error_code": "market_dependency_missing"}\')']
    )
    with pytest.raises(DomainError, match="market_dependency_missing"):
        fetch("calendar", {}, 1)


def test_stop_reaps_a_fetch_already_waiting_in_another_thread():
    fetch = BoundedFetch(command=[sys.executable, "-c", "import time; time.sleep(30)"])
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(fetch, "calendar", {}, 20)
        deadline = monotonic() + 1
        while not fetch._children and monotonic() < deadline:
            Event().wait(0.001)
        fetch.stop()
        with pytest.raises(DomainError):
            pending.result(timeout=1)
    assert not fetch._children


def test_quote_fetch_requests_unadjusted_daily_data():
    import pandas as pd

    from web.portfolio.fetch import fetch

    class Upstream:
        @staticmethod
        def stock_zh_a_hist(**kwargs):
            assert kwargs == {
                "symbol": "600000",
                "period": "daily",
                "start_date": "20260929",
                "end_date": "20260929",
                "adjust": "",
                "timeout": 10,
            }
            return pd.DataFrame([{"日期": "2026-09-29", "收盘": 10.0, "成交量": 100}])

    result = fetch("quote", {"symbol": "600000.SS", "target_date": "2026-09-29"}, Upstream())
    assert result["close"] == "10.0"
    assert result["source"] == "akshare_eastmoney_unadjusted"


def test_missing_dependency_child_does_not_return_healthy_empty_data():
    # The minimal interpreter has no site packages, including AKShare.
    result = subprocess.run(
        [sys.executable, "-S", "-m", "web.portfolio.fetch", "calendar"],
        input="{}",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert json.loads(result.stdout)["error_code"] == "market_dependency_missing"
