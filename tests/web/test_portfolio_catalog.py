import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import pytest

from web.portfolio.domain import DomainError
from web.portfolio.market import AShareMarket

NOW = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)


def entry(exchange):
    return {
        "symbol": {"SH": "600519.SS", "SZ": "000001.SZ", "BJ": "920001.BJ"}[exchange],
        "name": f"Fixture {exchange}",
        "exchange": exchange,
        "currency": "CNY",
        "security_type": "A_SHARE",
    }


def provider(operation, payload, timeout):
    assert operation == "catalog"
    return {"instruments": [entry(payload["exchange"])]}


def seed(tmp_path, exchange="SH", age=0):
    folder = tmp_path / "portfolio-market"
    folder.mkdir(exist_ok=True)
    fetched = (NOW - timedelta(days=age)).isoformat()
    (folder / f"catalog-{exchange.lower()}.json").write_text(
        json.dumps(
            {
                "fetched_at": fetched,
                "source": "fixture",
                "instruments": [{**entry(exchange), "verified_at": fetched}],
            }
        )
    )


def test_beijing_failure_does_not_block_verified_shanghai(tmp_path):
    def call(operation, payload, timeout):
        if payload["exchange"] == "BJ":
            raise DomainError("market_timeout")
        return provider(operation, payload, timeout)

    market = AShareMarket(tmp_path, call=call, clock=lambda: NOW)
    market.refresh_catalog()
    assert market.resolve("600519")["symbol"] == "600519.SS"
    result = market.search("600519")
    assert result["results"][0]["supported"] is True
    assert result["unavailable"] is False
    bj = next(s for s in result["catalog_status"] if s["exchange"] == "BJ")
    assert bj["error_code"] == "market_timeout"
    assert bj["state"] == "unavailable"
    with pytest.raises(DomainError, match="catalog_unavailable"):
        market.resolve("920001.BJ")


@pytest.mark.parametrize("age", [1, 6.99])
def test_recent_verified_cache_survives_upstream_failure(tmp_path, age):
    seed(tmp_path, age=age)

    def call(*args):
        raise DomainError("market_timeout")

    market = AShareMarket(tmp_path, call=call, clock=lambda: NOW)
    market.refresh_catalog("SH")
    result = market.search("600519")
    assert result["results"][0]["supported"] is True
    assert result["results"][0]["catalog_state"] == "stale"
    assert result["results"][0]["verified_at"] == (NOW - timedelta(days=age)).isoformat()
    assert market.resolve("600519.SS")["catalog_state"] == "stale"


@pytest.mark.parametrize("age", [7, 8, -1])
def test_expired_or_future_cache_cannot_verify_identity(tmp_path, age):
    seed(tmp_path, age=age)
    market = AShareMarket(tmp_path, call=provider, clock=lambda: NOW)
    with pytest.raises(DomainError, match="catalog_unavailable"):
        market.resolve("600519.SS")


def test_unknown_stock_not_authorized_by_stale_cache(tmp_path):
    seed(tmp_path, age=2)
    market = AShareMarket(tmp_path, call=provider, clock=lambda: NOW)
    with pytest.raises(DomainError, match="instrument_unverified"):
        market.resolve("600999.SS")


def test_invalid_refresh_does_not_replace_last_valid_exchange_cache(tmp_path):
    seed(tmp_path, age=2)
    cache = tmp_path / "portfolio-market/catalog-sh.json"
    before = cache.read_bytes()
    market = AShareMarket(
        tmp_path, call=lambda *args: {"instruments": [entry("BJ")]}, clock=lambda: NOW
    )
    market.refresh_catalog("SH")
    assert cache.read_bytes() == before
    assert market.resolve("600519.SS")["symbol"] == "600519.SS"
    status = market.search("600519")["catalog_status"][0]
    assert status["error_code"] == "catalog_invalid"


def test_background_refresh_does_not_hold_search_or_resolve(tmp_path):
    seed(tmp_path, age=2)
    entered, release = Event(), Event()

    def call(operation, payload, timeout):
        if payload["exchange"] == "SH":
            entered.set()
            assert release.wait(3)
        return provider(operation, payload, timeout)

    market = AShareMarket(tmp_path, call=call, clock=lambda: NOW)
    try:
        market.start()
        assert entered.wait(1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = pool.submit(market.search, "600519").result(timeout=0.5)
            assert result["results"][0]["supported"] is True
            assert (
                pool.submit(market.resolve, "600519.SS").result(timeout=0.5)["symbol"]
                == "600519.SS"
            )
        sh = next(s for s in result["catalog_status"] if s["exchange"] == "SH")
        assert sh["refreshing"] is True
    finally:
        release.set()
        market.stop()


def test_concurrent_refresh_is_single_flight_and_failure_is_throttled(tmp_path):
    entered, release = Event(), Event()
    requests = []
    current = [NOW]

    def call(operation, payload, timeout):
        requests.append(payload["exchange"])
        entered.set()
        assert release.wait(2)
        raise DomainError("market_timeout")

    market = AShareMarket(tmp_path, call=call, clock=lambda: current[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(market.refresh_catalog, "SH")
        assert entered.wait(1)
        second = pool.submit(market.refresh_catalog, "SH")
        release.set()
        first.result(timeout=1)
        second.result(timeout=1)
    market.refresh_catalog("SH")
    assert requests == ["SH"]
    current[0] += timedelta(minutes=5)
    market.refresh_catalog("SH")
    assert requests == ["SH", "SH"]


def test_legacy_cache_migrates_without_changing_verification_date(tmp_path):
    folder = tmp_path / "portfolio-market"
    folder.mkdir()
    fetched = (NOW - timedelta(days=2)).isoformat()
    (folder / "catalog.json").write_text(
        json.dumps(
            {
                "fetched_at": fetched,
                "instruments": [{**entry(e), "verified_at": fetched} for e in ("SH", "SZ", "BJ")],
            }
        )
    )
    market = AShareMarket(tmp_path, call=provider, clock=lambda: NOW)
    assert market.resolve("600519.SS")["verified_at"] == fetched
    assert market.resolve("920001.BJ")["catalog_state"] == "stale"


def test_cache_write_failure_preserves_identity_and_exposes_safe_reason(tmp_path, monkeypatch):
    seed(tmp_path, age=2)
    market = AShareMarket(tmp_path, call=provider, clock=lambda: NOW)

    def denied(*args):
        raise PermissionError("private filesystem path must not leak")

    monkeypatch.setattr(market, "_publish", denied)
    market.refresh_catalog("SH")
    result = market.search("600519")
    assert result["results"][0]["supported"] is True
    assert result["catalog_status"][0]["error_code"] == "cache_write_failed"
    assert "private filesystem" not in json.dumps(result)


def test_calendar_fetch_does_not_hold_identity_readers(tmp_path):
    seed(tmp_path)
    entered, release = Event(), Event()

    def call(*args):
        entered.set()
        assert release.wait(2)
        return {"dates": ["2026-09-29", "2026-09-30"]}

    market = AShareMarket(tmp_path, call=call, clock=lambda: NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calendar = pool.submit(market.calendar)
        assert entered.wait(1)
        try:
            result = pool.submit(market.resolve, "600519.SS").result(timeout=0.5)
            assert result["symbol"] == "600519.SS"
        finally:
            release.set()
        calendar.result(timeout=1)


def test_expired_search_status_keeps_date_but_never_authorizes_stock(tmp_path, monkeypatch):
    seed(tmp_path, age=8)
    monkeypatch.setattr(
        "web.portfolio.market.search_symbols",
        lambda *args: {
            "results": [entry("SH")],
            "unavailable": False,
        },
    )
    market = AShareMarket(tmp_path, call=provider, clock=lambda: NOW)
    result = market.search("600519")
    assert result["results"][0]["supported"] is False
    assert result["catalog_status"][0]["state"] == "expired"
    assert result["catalog_status"][0]["fetched_at"] == "2026-09-22T08:00:00+00:00"


def test_successful_daily_refresh_replaces_removed_identities(tmp_path):
    seed(tmp_path, age=2)
    replacement = {**entry("SH"), "symbol": "600000.SS"}
    market = AShareMarket(
        tmp_path, call=lambda *args: {"instruments": [replacement]}, clock=lambda: NOW
    )
    market.refresh_catalog("SH")
    assert market.resolve("600000.SS")["catalog_state"] == "fresh"
    with pytest.raises(DomainError, match="instrument_unverified"):
        market.resolve("600519.SS")


@pytest.mark.parametrize("exchange", ["SH", "SZ", "BJ"])
def test_catalog_adapter_only_calls_requested_exchange(exchange):
    import pandas as pd

    from web.portfolio.fetch import fetch

    class Upstream:
        def stock_info_sh_name_code(self, symbol):
            assert exchange == "SH"
            code = "600519" if symbol == "主板A股" else "688001"
            return pd.DataFrame([{"证券代码": code, "证券简称": "Fixture SH"}])

        def stock_info_sz_name_code(self, symbol):
            assert exchange == "SZ"
            assert symbol == "A股列表"
            return pd.DataFrame([{"A股代码": "000001", "A股简称": "Fixture SZ"}])

        def stock_info_bj_name_code(self):
            assert exchange == "BJ"
            return pd.DataFrame([{"证券代码": "920001", "证券简称": "Fixture BJ"}])

    result = fetch("catalog", {"exchange": exchange}, Upstream())
    assert {i["exchange"] for i in result["instruments"]} == {exchange}
    assert result["instruments"][0]["symbol"] == entry(exchange)["symbol"]


def test_fresh_catalog_does_not_redownload_on_search(tmp_path):
    current = [NOW]
    requests = []

    def call(operation, payload, timeout):
        requests.append(payload["exchange"])
        return provider(operation, payload, timeout)

    market = AShareMarket(tmp_path, call=call, clock=lambda: current[0])
    market.refresh_catalog("SH")
    market.refresh_catalog("SH")
    market.search("600519")
    market.resolve("600519")
    assert requests == ["SH"]
    current[0] += timedelta(days=1)
    market.refresh_catalog("SH")
    assert requests == ["SH", "SH"]


@pytest.mark.parametrize("items", [[None], ["broken"], [1]])
def test_malformed_legacy_catalog_cannot_break_startup(tmp_path, items):
    folder = tmp_path / "portfolio-market"
    folder.mkdir()
    (folder / "catalog.json").write_text(
        json.dumps({"fetched_at": NOW.isoformat(), "instruments": items})
    )
    market = AShareMarket(tmp_path, call=provider, clock=lambda: NOW)
    with pytest.raises(DomainError, match="catalog_unavailable"):
        market.resolve("600519.SS")


def test_identity_grace_period_does_not_extend_calendar_validity(tmp_path):
    seed(tmp_path, age=2)
    (tmp_path / "portfolio-market/calendar.json").write_text(
        json.dumps(
            {
                "fetched_at": (NOW - timedelta(days=2)).isoformat(),
                "dates": ["2026-09-29", "2026-09-30"],
                "covered_from": "2026-09-29",
                "covered_until": "2026-09-30",
            }
        )
    )

    def unavailable(*args):
        raise DomainError("market_timeout")

    market = AShareMarket(tmp_path, call=unavailable, clock=lambda: NOW)
    assert market.resolve("600519.SS")["catalog_state"] == "stale"
    with pytest.raises(DomainError, match="calendar_unavailable"):
        market.calendar()


def test_stop_reaps_all_background_catalog_children(tmp_path):
    import sys
    from time import monotonic

    from web.portfolio.market import BoundedFetch

    transport = BoundedFetch(command=[sys.executable, "-c", "import time; time.sleep(30)"])
    market = AShareMarket(tmp_path, call=transport)
    try:
        market.start()
        market.start()
        deadline = monotonic() + 2
        while len(transport._children) < 3 and monotonic() < deadline:
            Event().wait(0.01)
        assert len(transport._children) == 3
    finally:
        market.stop()
    assert not transport._children
    assert all(not t.is_alive() for t in market._threads)
