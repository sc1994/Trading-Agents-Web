from datetime import datetime, timedelta
from threading import Event
from zoneinfo import ZoneInfo

import pytest

from tests.web.test_portfolio_domain import quote
from tests.web.test_portfolio_store import inputs, instrument
from web.portfolio.domain import DomainError
from web.portfolio.store import PortfolioStore
from web.portfolio.worker import CloseCheckWorker, completed_date
from web.store import Store

CALENDAR = {
    "dates": ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-09"],
    "covered_from": "2026-09-25",
    "covered_until": "2026-10-09",
}


def now(day=29, hour=16, minute=30):
    return datetime(2026, 9, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))


class Market:
    def __init__(self, *, broken=False, calendar_error=False):
        self.broken, self.calendar_error = broken, calendar_error
        self.calls = []

    def calendar(self):
        if self.calendar_error:
            raise DomainError("calendar_unavailable")
        return CALENDAR

    def quote(self, item, date):
        self.calls.append(item["symbol"])
        return quote(
            symbol=item["symbol"],
            price_date=date,
            error_code="missing_quote" if self.broken else None,
        )

    def stop(self):
        pass


def setup(tmp_path, market=None, clock=None):
    store = PortfolioStore(Store(tmp_path / "private" / "web.db"))
    store.upsert_instrument(instrument())
    store.create_plan(inputs())
    market = market or Market()
    worker = CloseCheckWorker(store, market, clock=clock or (lambda: now()))
    return store, worker, market


@pytest.mark.parametrize(
    "time,want",
    [(now(minute=29), "2026-09-28"), (now(), "2026-09-29"), (now(day=27), "2026-09-25")],
)
def test_cutoff_and_weekend_use_latest_completed_session(time, want):
    assert completed_date(time, CALENDAR) == want


def test_unknown_working_day_fails_closed():
    with pytest.raises(DomainError, match="calendar_unavailable"):
        completed_date(now(day=30), {**CALENDAR, "covered_until": "2026-09-29"})


def test_same_stock_is_fetched_once_and_automatic_success_does_not_repeat(tmp_path):
    store, worker, market = setup(tmp_path)
    store.create_plan(inputs(horizon="long"))
    worker.tick()
    assert store.latest_check()["status"] == "completed"
    assert len(store.latest_check()["results"]) == 2
    worker.tick()
    assert market.calls == ["600000.SS"]


def test_manual_requests_are_idempotent_and_do_not_fetch_synchronously(tmp_path):
    store, worker, market = setup(tmp_path)
    a, b = worker.request_check(), worker.request_check()
    assert a["id"] == b["id"]
    assert market.calls == []
    worker.tick()
    assert store.get_check(a["id"])["status"] == "completed"


def test_retry_ceiling_and_half_hour_spacing(tmp_path):
    times = [now()]
    store, worker, market = setup(tmp_path, Market(broken=True), lambda: times[0])
    worker.tick()
    assert store.latest_check()["status"] == "failed"
    times[0] += timedelta(minutes=29)
    worker.tick()
    assert len(market.calls) == 1
    times[0] += timedelta(minutes=1)
    worker.tick()
    times[0] += timedelta(minutes=30)
    worker.tick()
    times[0] += timedelta(minutes=30)
    worker.tick()
    assert len(market.calls) == 3
    assert len(store.automatic_attempts("2026-09-29")) == 3


def test_preclose_and_weekend_do_not_backfill_automatic_checks(tmp_path):
    for index, time in enumerate([now(minute=29), now(day=27)]):
        store, worker, market = setup(tmp_path / str(index), clock=lambda time=time: time)
        worker.tick()
        assert store.latest_check() is None
        assert market.calls == []


def test_calendar_failure_is_recorded_not_misrepresented_as_valid(tmp_path):
    store, worker, market = setup(tmp_path, Market(calendar_error=True))
    worker.request_check()
    worker.tick()
    assert store.latest_check()["status"] == "failed"
    assert store.latest_check()["error_code"] == "calendar_unavailable"
    assert market.calls == []


def test_shutdown_and_recovery_do_not_use_llm_lock(tmp_path):
    from web.runner import _RUN_LOCK

    store, worker, _ = setup(tmp_path)
    c = worker.request_check()
    store.claim()
    with _RUN_LOCK:
        worker.start()
        deadline = Event()
        deadline.wait(0.05)
        worker.stop()
    assert store.get_check(c["id"])["status"] == "interrupted"
