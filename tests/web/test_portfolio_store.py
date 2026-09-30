from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.web.test_portfolio_domain import quote
from web.portfolio.domain import DomainError, evaluate
from web.portfolio.store import PortfolioStore
from web.store import Store


def instrument(symbol="600000.SS"):
    return {"symbol": symbol, "name": "Fixture", "exchange": "SH", "currency": "CNY",
            "security_type": "A_SHARE", "verified_at": "2026-09-29T09:00:00Z"}


@pytest.fixture
def portfolio(tmp_path):
    value = PortfolioStore(Store(tmp_path / "private" / "web.db"))
    value.upsert_instrument(instrument())
    return value


def inputs(**changes):
    return {"symbol": "600000.SS", "horizon": "short", "shares": 1000, "cost": "10.2",
            **changes}


def test_portfolio_does_not_replace_existing_tasks(tmp_path):
    store = Store(tmp_path / "private" / "web.db")
    task_id = store.create_task({"ticker": "NVDA", "date": "2026-09-29"})
    value = PortfolioStore(store)
    assert value.list_plans() == []
    assert store.get_task(task_id)["ticker"] == "NVDA"
    assert value.get_settings() == {"automatic": True, "concentration_limit": None}
    PortfolioStore(store)
    assert store.get_task(task_id) is not None


def test_same_stock_plans_and_watchlist_have_independent_lifecycles(portfolio):
    portfolio.add_watch("600000.SS", "watch reason")
    a = portfolio.create_plan(inputs())
    b = portfolio.create_plan(inputs(horizon="long"))
    portfolio.remove_watch("600000.SS")
    assert len(portfolio.list_plans()) == 2
    portfolio.close_plan(a["id"], a["revision"])
    assert [p["id"] for p in portfolio.list_plans()] == [b["id"]]
    assert len(portfolio.list_plans(active_only=False)) == 2


def test_revision_conflict_preserves_saved_plan(portfolio):
    p = portfolio.create_plan(inputs())
    updated = portfolio.update_plan(p["id"], 1, {"shares": 5})
    assert updated["revision"] == 2
    with pytest.raises(DomainError, match="revision_conflict"):
        portfolio.update_plan(p["id"], 1, {"shares": 7})
    with pytest.raises(DomainError, match="revision_conflict"):
        portfolio.close_plan(p["id"], 1)
    assert portfolio.list_plans()[0]["shares"] == 5


def test_unknown_and_unsupported_identity_is_not_saved(portfolio):
    with pytest.raises(DomainError, match="instrument_unverified"):
        portfolio.create_plan(inputs(symbol="000001.SZ"))
    with pytest.raises(DomainError, match="unsupported_market"):
        portfolio.upsert_instrument({**instrument(), "security_type": "ETF"})


def test_check_claim_saves_snapshot_and_later_plan_edits_do_not_mutate_history(portfolio):
    p = portfolio.create_plan(inputs())
    queued = portfolio.enqueue("manual", None)
    assert portfolio.enqueue("manual", None)["id"] == queued["id"]
    claimed = portfolio.claim()
    assert claimed["plans"][0]["shares"] == 1000
    portfolio.update_plan(p["id"], 1, {"shares": 2})
    result = evaluate(claimed["plans"][0], quote(), "2026-09-29")
    portfolio.set_target(claimed["id"], "2026-09-29")
    done = portfolio.complete(claimed["id"], [result], "completed")
    assert done["results"][0]["plan_snapshot"]["shares"] == 1000
    reopened = PortfolioStore(Store(portfolio.store.path))
    assert reopened.get_check(done["id"])["results"][0]["revision"] == 1


def test_concurrent_enqueue_and_recovery_allow_only_one_pending_check(portfolio):
    with ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(lambda _: portfolio.enqueue("manual", None), range(8)))
    assert len({c["id"] for c in checks}) == 1
    assert portfolio.claim()["status"] == "running"
    assert portfolio.claim() is None
    portfolio.recover()
    assert portfolio.latest_check()["status"] == "interrupted"
    assert portfolio.enqueue("manual", None)["id"] != checks[0]["id"]


def test_automatic_attempt_identity_persists(portfolio):
    c = portfolio.enqueue("automatic", "2026-09-29", 1)
    portfolio.claim()
    portfolio.fail(c["id"], "calendar_unavailable")
    assert portfolio.enqueue("automatic", "2026-09-29", 1)["id"] == c["id"]
    assert len(portfolio.automatic_attempts("2026-09-29")) == 1


def test_watchlist_limit_counts_distinct_active_stocks(portfolio):
    for number in range(100):
        symbol = f"{600000 + number}.SS"
        portfolio.upsert_instrument(instrument(symbol))
        portfolio.add_watch(symbol, "")
    portfolio.create_plan(inputs())
    portfolio.upsert_instrument(instrument("600100.SS"))
    with pytest.raises(DomainError, match="stock_limit"):
        portfolio.create_plan(inputs(symbol="600100.SS"))
    assert len(portfolio.list_watchlist()) == 100


def test_settings_are_separate_and_threshold_validated(portfolio):
    assert portfolio.update_settings({"automatic": False, "concentration_limit": "30"}) == {
        "automatic": False, "concentration_limit": "30"}
    with pytest.raises(DomainError):
        portfolio.update_settings({"concentration_limit": "101"})
    assert portfolio.store.get_settings() == {}
