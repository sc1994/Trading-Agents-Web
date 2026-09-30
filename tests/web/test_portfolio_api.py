from datetime import datetime
from threading import Event
from time import monotonic
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from tests.web.conftest import FakeRunner
from tests.web.test_portfolio_market import catalog
from tests.web.test_portfolio_worker import Market
from web.portfolio.domain import DomainError
from web.server import create_app


class FixtureMarket(Market):
    def resolve(self, symbol):
        for item in catalog()["instruments"]:
            if symbol in {item["symbol"], item["symbol"][:6]}:
                return {**item, "verified_at": "2026-09-29T09:00:00Z"}
        raise DomainError("unsupported_market", "symbol")

    def search(self, query):
        return {
            "results": [{**self.resolve("600000"), "supported": True, "support_code": None}],
            "unavailable": False,
        }


@pytest.fixture
def portfolio_client(tmp_path):
    with TestClient(
        create_app(
            data_dir=tmp_path,
            executor=FakeRunner(),
            portfolio_market=FixtureMarket(),
            portfolio_clock=lambda: datetime(2026, 9, 29, 17, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
    ) as client:
        client.patch("/api/portfolio/settings", json={"automatic": False})
        yield client


def body(**changes):
    return {"symbol": "600000", "horizon": "short", "shares": 1000, "cost": "10.2", **changes}


def test_non_a_share_plan_rejected_without_mutation(portfolio_client):
    response = portfolio_client.post("/api/portfolio/plans", json=body(symbol="NVDA"))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_market"
    assert portfolio_client.get("/api/portfolio/plans").json()["plans"] == []


def test_plan_lifecycle_revision_and_watch_independence(portfolio_client):
    c = portfolio_client
    response = c.post("/api/portfolio/plans", json=body())
    assert response.status_code == 201
    p = response.json()
    assert p["symbol"] == "600000.SS"
    assert (
        c.post(
            "/api/portfolio/watchlist", json={"symbol": "600000", "reason": "fixture"}
        ).status_code
        == 201
    )
    assert c.delete("/api/portfolio/watchlist/600000.SS").status_code == 204
    updated = c.patch(f"/api/portfolio/plans/{p['id']}", json={"revision": 1, "shares": 2})
    assert updated.json()["shares"] == 2
    assert (
        c.patch(f"/api/portfolio/plans/{p['id']}", json={"revision": 1, "shares": 3}).status_code
        == 409
    )
    assert c.post(f"/api/portfolio/plans/{p['id']}/close", json={"revision": 2}).status_code == 200
    assert c.get("/api/portfolio/plans").json()["plans"] == []
    assert c.get("/api/tasks").json() == {"tasks": []}


@pytest.mark.parametrize(
    "changes",
    [
        {"shares": True},
        {"shares": 1.5},
        {"cost": 10},
        {"cost": "NaN"},
        {"cost": "1e1"},
        {"unknown": "bad"},
    ],
)
def test_strict_invalid_inputs_do_not_mutate(portfolio_client, changes):
    assert portfolio_client.post("/api/portfolio/plans", json=body(**changes)).status_code == 422
    assert portfolio_client.get("/api/portfolio/plans").json()["plans"] == []


def test_check_and_modified_plan_show_incomplete_summary(portfolio_client):
    c = portfolio_client
    p = c.post("/api/portfolio/plans", json=body(lower="10")).json()
    response = c.post("/api/portfolio/checks")
    assert response.status_code == 202
    deadline = monotonic() + 3
    while monotonic() < deadline:
        check = c.get(f"/api/portfolio/checks/{response.json()['id']}").json()
        if check["status"] == "completed":
            break
        Event().wait(0.01)
    assert check["results"][0]["signals"] == ["lower"]
    overview = c.get("/api/portfolio/overview").json()
    assert overview["summary"]["market_value"] == "10000"
    assert overview["reference_date"] == "2026-09-29"
    assert (
        c.patch(f"/api/portfolio/plans/{p['id']}", json={"revision": 1, "shares": 4}).status_code
        == 200
    )
    overview = c.get("/api/portfolio/overview").json()
    assert overview["summary"]["complete"] is False
    assert overview["plans"][0]["result_obsolete"] is True


def test_static_routes_and_fixed_errors(portfolio_client):
    for route in ["/holdings", "/watchlist"]:
        assert portfolio_client.get(route).status_code == 200
    assert portfolio_client.get("/api/portfolio/checks/missing").status_code == 404
    assert portfolio_client.get("/api/portfolio/checks/latest").json() is None
    assert (
        portfolio_client.post(
            "/api/portfolio/checks", headers={"sec-fetch-site": "cross-site"}
        ).status_code
        == 403
    )


def test_client_cannot_override_the_server_owned_check_date(portfolio_client):
    response = portfolio_client.post("/api/portfolio/checks", json={"target_date": "2020-01-01"})
    assert response.status_code == 422
    assert portfolio_client.get("/api/portfolio/checks/latest").json() is None


def test_report_association_uses_exact_stock_and_analysis_date(portfolio_client):
    c = portfolio_client
    c.post("/api/portfolio/plans", json=body())
    store = c.app.state.store
    c.app.state.worker.stop()
    for ticker, date in [
        ("600000.SS", "2026-09-29"),
        ("600000.SS", "2026-09-28"),
        ("600001.SS", "2026-09-30"),
    ]:
        task = store.create_task({"ticker": ticker, "date": date, "name": "fixture"})
        store.claim_next()
        store.save_section(task, "decision", "generic research")
        store.finish(task, "Hold", "generic research")
    reports = c.get("/api/portfolio/overview").json()["reports"]["600000.SS"]
    assert [r["date"] for r in reports] == ["2026-09-29", "2026-09-28"]
