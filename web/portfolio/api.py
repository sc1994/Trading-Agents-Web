"""Strict portfolio HTTP contracts; research graph inputs remain unchanged."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from web.portfolio.domain import DomainError, summarize

router = APIRouter(prefix="/api/portfolio")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlanInput(Input):
    symbol: str = Field(max_length=32)
    horizon: Literal["short", "medium", "long"]
    shares: int
    cost: str
    reason: str = Field(default="", max_length=2000)
    lower: str | None = None
    upper: str | None = None
    review_date: str | None = None
    cost_pending: bool = False


class PlanPatch(Input):
    revision: int = Field(ge=1)
    horizon: Literal["short", "medium", "long"] | None = None
    shares: int | None = None
    cost: str | None = None
    reason: str | None = Field(default=None, max_length=2000)
    lower: str | None = None
    upper: str | None = None
    review_date: str | None = None
    cost_pending: bool | None = None


class Revision(Input):
    revision: int = Field(ge=1)


class WatchInput(Input):
    symbol: str = Field(max_length=32)
    reason: str = Field(default="", max_length=2000)


class ReasonInput(Input):
    reason: str = Field(max_length=2000)


class SettingsInput(Input):
    automatic: bool | None = None
    concentration_limit: str | None = None


def invoke(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except DomainError as error:
        status = (
            404
            if error.code == "not_found"
            else 409
            if error.code
            in {"revision_conflict", "plan_closed", "watch_exists", "check_not_running"}
            else 503
            if error.code
            in {
                "catalog_unavailable",
                "catalog_loading",
                "calendar_unavailable",
                "market_unavailable",
                "worker_stopped",
            }
            else 422
        )
        raise HTTPException(status, {"code": error.code, "field": error.field}) from None


@router.get("/instruments/search")
def search(request: Request, q: str = Query(min_length=2, max_length=64)):
    return invoke(request.app.state.portfolio_market.search, q)


def save_identity(request, symbol):
    instrument = invoke(request.app.state.portfolio_market.resolve, symbol)
    invoke(request.app.state.portfolio.upsert_instrument, instrument)
    return instrument["symbol"]


@router.get("/plans")
def plans(request: Request):
    return {"plans": request.app.state.portfolio.list_plans()}


@router.post("/plans", status_code=201)
def create_plan(body: PlanInput, request: Request):
    raw = body.model_dump()
    raw["symbol"] = save_identity(request, body.symbol)
    return invoke(request.app.state.portfolio.create_plan, raw)


@router.patch("/plans/{id}")
def update_plan(id: str, body: PlanPatch, request: Request):
    raw = body.model_dump(exclude_unset=True)
    revision = raw.pop("revision")
    return invoke(request.app.state.portfolio.update_plan, id, revision, raw)


@router.post("/plans/{id}/close")
def close_plan(id: str, body: Revision, request: Request):
    return invoke(request.app.state.portfolio.close_plan, id, body.revision)


@router.get("/watchlist")
def watchlist(request: Request):
    return {"watchlist": request.app.state.portfolio.list_watchlist()}


@router.post("/watchlist", status_code=201)
def add_watch(body: WatchInput, request: Request):
    symbol = save_identity(request, body.symbol)
    return invoke(request.app.state.portfolio.add_watch, symbol, body.reason)


@router.patch("/watchlist/{symbol}")
def update_watch(symbol: str, body: ReasonInput, request: Request):
    return invoke(request.app.state.portfolio.update_watch, symbol, body.reason)


@router.delete("/watchlist/{symbol}", status_code=204)
def remove_watch(symbol: str, request: Request):
    invoke(request.app.state.portfolio.remove_watch, symbol)
    return Response(status_code=204)


@router.get("/settings")
def settings(request: Request):
    return request.app.state.portfolio.get_settings()


@router.patch("/settings")
def update_settings(body: SettingsInput, request: Request):
    return invoke(request.app.state.portfolio.update_settings, body.model_dump(exclude_unset=True))


@router.post("/checks", status_code=202)
def create_check(request: Request, body: Input | None = None):
    return invoke(request.app.state.portfolio_worker.request_check)


@router.get("/checks/latest")
def latest_check(request: Request):
    return request.app.state.portfolio.latest_check()


@router.get("/checks/{id}")
def check(id: str, request: Request):
    result = request.app.state.portfolio.get_check(id)
    if result is None:
        raise HTTPException(404, {"code": "not_found", "field": "body"})
    return result


@router.get("/overview")
def overview(request: Request):
    portfolio = request.app.state.portfolio
    current = portfolio.list_plans()
    latest = portfolio.latest_check()
    results = (
        latest["results"]
        if latest and latest["status"] in {"completed", "partial", "failed"}
        else []
    )
    indexed = {r["plan_id"]: r for r in results}
    plans = [
        {
            **p,
            "result": indexed.get(p["id"]),
            "result_obsolete": bool(
                indexed.get(p["id"]) and indexed[p["id"]]["revision"] != p["revision"]
            ),
        }
        for p in current
    ]
    symbols = {p["symbol"] for p in current} | {w["symbol"] for w in portfolio.list_watchlist()}
    reports = {symbol: [] for symbol in symbols}
    tasks = request.app.state.store.list_tasks(status="completed")
    for task in sorted(tasks, key=lambda t: (t["date"], t["finished_at"] or ""), reverse=True):
        symbol = task["ticker"].strip().upper()
        if symbol in reports:
            reports[symbol].append(
                {
                    "id": task["id"],
                    "date": task["date"],
                    "finished_at": task["finished_at"],
                    "rating": task["rating"],
                }
            )
    reference = latest["target_date"] if latest and latest["results"] else None
    return {
        "plans": plans,
        "latest_check": latest,
        "summary": summarize(current, results, portfolio.get_settings()["concentration_limit"]),
        "reports": reports,
        "reference_date": reference,
    }
