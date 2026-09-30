# A-Share Holdings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manually maintained A-share holdings/watchlists and trustworthy end-of-day observation checks to the private research workbench.

**Architecture:** Add an isolated `web/portfolio/` package over the existing private SQLite database. Pure Decimal rules consume immutable plan/quote snapshots; a separate durable worker resolves trading dates and obtains quotes without using the LLM runner lock. New APIs and Ant Design views reuse instrument search and the existing analysis/report workflow without adding portfolio fields to graph inputs.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, Decimal, zoneinfo, AKShare from the existing search extra, React 19, TypeScript, Ant Design 5, pytest, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-30-a-share-holdings-design.md` (user approved).

## Global Constraints

- Only verified mainland A-share ordinary equities in SH/SZ/BJ with CNY denomination are supported by the new workflow; retain all existing analysis markets and routes.
- Share count is an integer in `[1, 1000000000]`; positive decimal inputs are strings with at most 12 integer and 6 fractional digits; reject exponent syntax, nonfinite values and unexpected request fields.
- Plan horizons are `short`, `medium`, `long`; conditions are optional and have no default stop-loss or concentration threshold.
- The check date is server-owned, in `Asia/Shanghai`, with a 16:30 cutoff and verified calendar coverage. Automatic checks make at most three attempts per date, at least 30 minutes apart.
- Bound all market calls; no LLM inference of financial facts, no process-environment mutation, no graph runner lock, no new service dependency.
- At most 100 distinct stocks across watchlist and active plans. Check each stock once per run. Use Decimal, nonadjusted closes, immutable input snapshots, explicit missing-data states, and optimistic plan revisions.
- A closed plan keeps history. A watchlist deletion never deletes a plan/report. Never put real financial data in logs, screenshots, fixtures or Git.
- New reports remain generic research, not personalized portfolio advice. Preserve user confirmation before creating analysis tasks.
- Verify desktop/mobile headlessly and deliver screenshots, not a local URL. Update PR #23 before coding delivery; do not merge or deploy.

## File Map

| Module | Responsibility |
| --- | --- |
| `web/portfolio/domain.py` | Fixed domain errors, input validation, pure plan rules and complete-data aggregation |
| `web/portfolio/store.py` | Incremental schema and transactional portfolio/check lifecycle |
| `web/portfolio/market.py`, `fetch.py` | Trusted A-share catalog/calendar/close normalization, caches and killable subprocess calls |
| `web/portfolio/worker.py` | Date resolution, durable queue, snapshots, retries and lifecycle |
| `web/portfolio/api.py` | Strict portfolio HTTP contract, overview and report association |
| `web/server.py` | Lifespan wiring and static route allowlist only |
| `web/client/src/portfolio/api.ts` | Separate portfolio types/client and fixed business-error messages |
| `web/client/src/portfolio/PlanForm.tsx`, `InstrumentPicker.tsx` | Shared verified-instrument selector and focused plan editor |
| `web/client/src/pages/Holdings.tsx`, `Watchlist.tsx` | Scan-first holdings and watchlist views |
| `web/client/src/App.tsx`, `styles.css`, `pages/Start.tsx` | Navigation, responsive styling and explicit analysis prefill |
| `tests/web/test_portfolio_*.py`, frontend colocated tests | Deterministic verification without live market requests |
| `web/client/scripts/portfolio-acceptance.mjs` | Headless fixture screenshots and workflow checks |

## Task 1: Validated Plans and Pure Risk Rules

**Files:** Create `web/portfolio/__init__.py`, `web/portfolio/domain.py`, `tests/web/test_portfolio_domain.py`.

**Interfaces:** `DomainError(code: str, field: str = "body")`; `validate_plan(raw: dict) -> dict`; `evaluate(plan: dict, quote: dict | None, target_date: str) -> dict`; `summarize(plans: list[dict], results: list[dict], concentration_limit: str | None) -> dict`.

Plans carry `id`, `symbol`, `horizon`, `shares`, `cost`, `reason`, `lower`, `upper`, `review_date`, `cost_pending`, `revision`, `status`. Quotes carry `symbol`, `price_date`, `close`, `currency`, `source`, `fetched_at`, `error_code`. Results carry plan ID/revision/snapshot, quote, quality (`valid`, `missing`, `stale`, `cost_pending`), signals, state (`review`, `not_triggered`, `no_conditions`, `unavailable`), market_value and unrealized_pnl decimal strings or null.

- [x] Write failing boundary tests, including this equality case:

```python
from web.portfolio.domain import evaluate

def test_lower_equality_triggers_review():
    plan = {"id": "p1", "symbol": "600000.SS", "horizon": "short",
            "shares": 1000, "cost": "10.2", "lower": "10", "upper": None,
            "review_date": None, "cost_pending": False, "revision": 1,
            "reason": "fixture", "status": "active"}
    quote = {"symbol": "600000.SS", "price_date": "2026-09-29", "close": "10",
             "currency": "CNY", "source": "fixture", "fetched_at": "2026-09-29T09:00:00Z",
             "error_code": None}
    result = evaluate(plan, quote, "2026-09-29")
    assert result["state"] == "review"
    assert result["signals"] == ["lower"]
    assert result["unrealized_pnl"] == "-200"
```

- [x] Run `pytest tests/web/test_portfolio_domain.py -q`; expect missing-module failure before implementation.
- [x] Implement `validate_plan` with allowed-field/type checks and `re.fullmatch(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?", value)` plus Decimal positivity. Apply `close <= lower`, `close >= upper`, and target-date comparison. Invalid/stale quotes cannot produce price signals; a valid date signal can coexist with unavailable price quality. Use Decimal quantization/string normalization, not float conversion.
- [x] Add tests for upper equality, date-only review, no conditions, invalid currency/symbol/date, nonfinite and exponent inputs, plan limits, pending cost, mixed quality, identical-stock grouping and revision mismatch suppression. Aggregation requires a matching valid result for every active plan and excludes no missing plan silently.
- [x] Run the entire domain file, then commit `feat: add validated portfolio plans and observation rules`.

## Task 2: Portfolio Persistence and Durable Snapshots

**Files:** Create `web/portfolio/store.py`, `tests/web/test_portfolio_store.py`.

**Interfaces:** `PortfolioStore(store: web.store.Store)` initializes schema transactionally. Methods: `upsert_instrument(instrument: dict) -> dict`; `add_watch(symbol: str, reason: str) -> dict`; `update_watch(symbol: str, reason: str) -> dict`; `remove_watch(symbol: str) -> None`; `list_watchlist() -> list[dict]`; `create_plan(raw: dict) -> dict`; `update_plan(id: str, revision: int, raw: dict) -> dict`; `close_plan(id: str, revision: int) -> dict`; `list_plans(active_only: bool = True) -> list[dict]`; `get_settings() -> dict`; `update_settings(raw: dict) -> dict`; `enqueue(source: str, target_date: str | None, attempt: int = 0) -> dict`; `claim() -> dict | None`; `complete(id: str, results: list[dict], status: str) -> dict`; `fail(id: str, code: str) -> dict`; `get_check(id: str) -> dict | None`; `latest_check() -> dict | None`; `recover() -> None`; `automatic_attempts(target_date: str) -> list[dict]`.

- [ ] Write a failing migration/persistence test:

```python
from web.store import Store
from web.portfolio.store import PortfolioStore

def test_portfolio_does_not_replace_existing_tasks(tmp_path):
    store = Store(tmp_path / "private" / "web.db")
    task_id = store.create_task({"ticker": "NVDA", "date": "2026-09-29"})
    portfolio = PortfolioStore(store)
    assert portfolio.list_plans() == []
    assert store.get_task(task_id)["ticker"] == "NVDA"
    assert portfolio.get_settings() == {"automatic": True, "concentration_limit": None}
```

- [ ] Run `pytest tests/web/test_portfolio_store.py -q`; verify the new import fails.
- [ ] Add tables from the spec using the existing Store transaction context, foreign keys, UUID IDs, decimal text and schema idempotence. Enforce a partial unique index for a single queued/running check and `(target_date, attempt)` uniqueness for automatic checks. `claim` snapshots active plans in the same short transaction. `complete` atomically saves immutable snapshots/results and the terminal status.
- [ ] Test same-stock multiple horizons; watch deletion independence; revision conflict and close guards; inactive plans; 100-stock union limit under concurrent writes; idempotent enqueue; recovery of running rows; no calls to external services within transactions; reopening the database preserves historical results after plan changes.
- [ ] Run store/domain tests and existing `tests/web/test_store.py`; commit `feat: persist portfolio plans and close-check history`.

## Task 3: Verified A-Share Market Data with Bounded Calls

**Files:** Create `web/portfolio/market.py`, `web/portfolio/fetch.py`, `tests/web/test_portfolio_market.py`.

**Interfaces:** `AShareMarket(data_dir: Path, call: Callable | None = None)`; `search(query: str) -> dict`; `resolve(symbol: str) -> dict`; `calendar() -> dict`; `quote(instrument: dict, target_date: str) -> dict`; `stop() -> None`. Calendar carries sorted ISO `dates`, `covered_from`, `covered_until`, `source`, `fetched_at`. Instrument carries canonical `symbol`, `name`, `exchange`, `currency="CNY"`, `security_type="A_SHARE"`, `verified_at`. `call(operation: str, payload: dict, timeout: float) -> dict` is the injectable fetch boundary.

- [ ] Write failing market tests using an injected callable; no production network requests:

```python
from web.portfolio.market import AShareMarket

def test_stale_close_is_not_a_valid_quote(tmp_path):
    def call(operation, payload, timeout):
        assert operation == "quote"
        return {"symbol": "600000.SS", "price_date": "2026-09-28", "close": "10",
                "currency": "CNY", "source": "fixture"}
    market = AShareMarket(tmp_path, call=call)
    quote = market.quote({"symbol": "600000.SS", "exchange": "SH",
                          "currency": "CNY", "security_type": "A_SHARE"}, "2026-09-29")
    assert quote["error_code"] == "stale_quote"
```

- [ ] Run `pytest tests/web/test_portfolio_market.py -q`; confirm red.
- [ ] Implement trusted catalog adapters using `stock_info_sh_name_code` (A-share main board and STAR), `stock_info_sz_name_code` (A shares), and `stock_info_bj_name_code`; use `tool_trade_date_hist_sina` for calendar and `stock_zh_a_hist(period="daily", adjust="")` for nonadjusted bars. Validate the installed AKShare signatures in adapter tests. `fetch.py` runs via `[sys.executable, "-m", "web.portfolio.fetch", operation]`; write JSON payload to stdin, cap the child normalized JSON output at 4 MiB, use `communicate(timeout=20)`, terminate then kill and reap on timeout. Track active children for `stop`; never shell-interpolate user text. Return fixed error codes instead of upstream traces.
- [ ] Cache catalog/calendar atomically under the private data directory. Publish a catalog only after validating nonempty SH/SZ/BJ coverage and identities; keep previous complete cache after refresh failure. Resolve naked or explicit symbols only against verified entries. Calendar coverage comes from the fetched range, not a fabricated future year-end; missing working-day coverage fails closed. Search decorates existing results with `supported` and `support_code`, and can find BJ entries from the catalog.
- [ ] Test catalog outage, guessed prefixes, SH/SZ/BJ identity, non-A shares and ETF/B-share rejection, partial catalog, cache publication, stale/suspended quotes, currency mismatch, wrong symbol, malformed bars, nonadjusted provider argument, child timeout and child shutdown. Missing AKShare returns a fixed `market_dependency_missing` code, not an empty healthy catalog.
- [ ] Run market tests and existing search/catalog tests; commit `feat: add verified bounded A-share close data`.

## Task 4: Independent End-of-Day Check Worker

**Files:** Create `web/portfolio/worker.py`, `tests/web/test_portfolio_worker.py`.

**Interfaces:** `completed_date(now: datetime, calendar: dict) -> str` (raises DomainError on unverified coverage); `CloseCheckWorker(store: PortfolioStore, market: AShareMarket, clock: Callable[[], datetime] | None = None)`; `start()`, `stop()`, `request_check() -> dict`, `tick() -> None`. `tick` is deterministic and testable without starting a polling thread; `request_check` only enqueues and returns, with date resolution performed outside HTTP/DB transactions.

- [ ] Write a failing cutoff test:

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from web.portfolio.worker import completed_date

def test_before_cutoff_uses_previous_completed_session():
    now = datetime(2026, 9, 29, 16, 29, tzinfo=ZoneInfo("Asia/Shanghai"))
    calendar = {"dates": ["2026-09-28", "2026-09-29", "2026-09-30"],
                "covered_from": "2026-09-28", "covered_until": "2026-09-30"}
    assert completed_date(now, calendar) == "2026-09-28"
```

- [ ] Run `pytest tests/web/test_portfolio_worker.py -q`; confirm red.
- [ ] Implement one independent worker with bounded wake/shutdown, Store recovery and clock injection. Resolve dates from verified coverage, claim snapshots, fetch each distinct instrument once, evaluate every plan, then finish as completed/partial/failed. Preserve date signals alongside missing quote quality. Calendar failure sets check failure without normal price results.
- [ ] Schedule current-session automatic runs at/after 16:30; skip weekends/verified holidays, empty portfolios and successful current-date checks. Record automatic attempt identity durably; three total attempts separated by 30 minutes. On restart recover running checks and do not backfill historical plans. Repeated manual calls reuse pending checks.
- [ ] Test weekend/holiday/unknown calendar, cutoff equality, restart catch-up, no historical backfill, three-attempt ceiling, manual success suppression, retry intervals, duplicate enqueue, plan edits during fetch, missing quotes, cost pending, independent execution while `_RUN_LOCK` is held, and bounded stop that reaps children.
- [ ] Run worker/domain/store/market tests; commit `feat: schedule durable end-of-day portfolio checks`.

## Task 5: Portfolio HTTP Contracts and Lifespan Wiring

**Files:** Create `web/portfolio/api.py`, `tests/web/test_portfolio_api.py`; modify `web/server.py`, `tests/web/conftest.py`.

**Interfaces:** router prefix `/api/portfolio`; request models use `extra="forbid"` and strict fields. Routes: GET instruments/search; GET/POST watchlist; PATCH/DELETE watchlist/{symbol}; GET/POST plans; PATCH plans/{id}; POST plans/{id}/close (revision body); GET/PATCH settings; POST checks; GET checks/latest; GET checks/{id}; GET overview. Responses expose the dictionary fields from Tasks 1-4, structured errors `{code, field}`, and overview `{plans, latest_check, summary, reports, reference_date}`. `reports` are completed generic reports grouped by canonical symbol, ordered by analysis date then completion time; `reference_date` is verified or null.

`create_app(..., portfolio_market: AShareMarket | None = None, portfolio_clock: Callable | None = None)` is the injection boundary. Retain executor semantics and all prior endpoints. No background requests for a fresh empty portfolio; legacy tests inject a market fake to remain network-free.

- [ ] Write the failing non-A-share API test:

```python
def test_non_a_share_plan_rejected_without_mutation(portfolio_client):
    response = portfolio_client.post("/api/portfolio/plans", json={
        "symbol": "NVDA", "horizon": "long", "shares": 10, "cost": "100"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_market"
    assert portfolio_client.get("/api/portfolio/plans").json()["plans"] == []
```

- [ ] Add `portfolio_client` with verified fixture market/calendar/quotes. Run `pytest tests/web/test_portfolio_api.py -q`; confirm endpoint/import failure before implementation.
- [ ] Wire independent store/market/worker into lifespan, stop both workers reliably, include the router, and add `/holdings` and `/watchlist` to the SPA allowlist. Use explicit 201 creation, 202 checks, 404 missing rows, 409 revision conflict, 422 unsupported/input failures and 503 unavailable market identity. Overview is cache/DB-only and marks obsolete result revisions rather than aggregating them.
- [ ] Cover all CRUD, watch-to-plan identity, invalid fields/decimals, close conflicts, queue progress, partial/failure quality, security headers/cross-site writes, response privacy, exact report matching and analysis-date ordering. Verify current task deletion/rerun/report behavior stays unchanged.
- [ ] Run `pytest tests/web -q` and portfolio domain/market/worker suites; commit `feat: expose portfolio management and check APIs`.

## Task 6: Holdings, Watchlist and Explicit Research Handoff

**Files:** Create `web/client/src/portfolio/api.ts`, `InstrumentPicker.tsx`, `PlanForm.tsx`, their colocated tests, `pages/Holdings.tsx`, `pages/Watchlist.tsx`, page tests; modify `App.tsx`, `styles.css`, `pages/Start.tsx`, `pages/Start.test.tsx`, `App.test.tsx`.

**Interfaces:** separate `PortfolioApi` mirrors Task 5 routes; `PlanInput` carries symbol/horizon/shares/cost/reason/lower/upper/review_date/cost_pending. `PlanForm({api, plan?, onSaved, onCancel})` preserves failed values and revision. `InstrumentPicker({api, value?, onChange})` rejects unsupported selections. `Holdings({api, navigate})` and `Watchlist({api, navigate})` consume the portfolio client separately from existing WebApi. `Start` accepts optional `{symbol,name,date}` prefill passed via React Router location state; missing verified date does not silently use an unverified portfolio date.

- [ ] Write failing UI tests using fixture PortfolioApi, including visible disabled non-A-share options:

```tsx
it("explains why a non-A-share result cannot be selected", async () => {
  const api = fixturePortfolioApi();
  api.searchInstruments = vi.fn().mockResolvedValue({results: [{
    symbol: "NVDA", name: "NVIDIA", exchange: "US", supported: false,
    support_code: "unsupported_market"}], unavailable: false});
  render(<InstrumentPicker api={api} onChange={vi.fn()} />);
  await userEvent.type(screen.getByRole("combobox"), "NVDA");
  expect(await screen.findByText("当前持仓与收盘检查仅支持 A 股")).toBeVisible();
});
```

`fixturePortfolioApi()` is a typed local test helper defining every PortfolioApi method with inert or fixture results; create it with the first UI test, not as an undeclared production dependency.

- [ ] Run `npm --prefix web/client test -- --run src/portfolio`; confirm import/component failure.
- [ ] Implement API types and fixed Chinese error mapping without changing existing ApiError semantics. Use Ant Design icons, horizon Segmented, InputNumber stringMode for decimals, switches for booleans, explicit close confirmation and loading/empty/failure states. Preserve unsaved values after validation/conflict; do not auto-submit research.
- [ ] Build holdings as unframed page bands and repeated plan rows grouped by stock, with check status/date/source, editable conditions and incomplete-summary notices. Display generic-research disclaimer near report links. Poll only while a check is pending and stop on unmount/terminal state. Build watchlist CRUD plus creation of a plan using verified identity.
- [ ] Add routes/nav without moving the existing analysis root. Initialize prefill only after model settings load and retain it on retry; selection must match the prefilled instrument. Show unsupported BJ generic research if the existing data vendor cannot provide it rather than claiming guaranteed research coverage.
- [ ] Cover create/edit/close, simultaneous same-stock horizons, condition toggles, pending-cost state, unavailable/stale check, revision mismatch, check retry, watchlist-to-plan, report association, preserved form inputs, defaults and prefill. Run `npm --prefix web/client test -- --run` and `npm --prefix web/client run build`; commit `feat: add holdings and watchlist workbench views`.

## Task 7: Headless Acceptance and PR Delivery

**Files:** Create `web/client/scripts/portfolio-acceptance.mjs`; add fictitious screenshots under `docs/design/assets/`; modify README and the implementation plan progress boxes.

- [ ] Add an acceptance script using the existing Playwright toolchain and a fixture HTTP server. Intercept market/portfolio endpoints with a verified fake 600000.SS short/long example plus stale data. Throw on console/page errors, failed assets, unexpected requests and body scroll-width overflow.
- [ ] Run desktop 1440x1000 and mobile 390x844 workflows: view grouped plans, add a plan, reject NVDA, edit a threshold, close a plan, add a watch, transfer to a plan, enqueue/finish/partially fail checks, and inspect research prefill without creating an LLM task. Save holdings/watchlist/form screenshots using fictitious data only. Follow the existing acceptance harness for serving built assets; never give the user the private local URL.
- [ ] Run fresh verification: `pytest tests/web -q`; `npm --prefix web/client test -- --run`; `npm --prefix web/client run build`; `node web/client/scripts/portfolio-acceptance.mjs`; `git diff --check`. Run relevant core symbol/report regression suites and existing acceptance script where dependencies are available; record actual commands/results, not presumed success.
- [ ] Review the diff against every spec section, especially market rejection, calendar coverage, quote freshness, automatic retry durability, financial data privacy, calculation口径 and missing-data messages. Resolve defects with a failing regression test before changing code.
- [ ] Commit docs/screenshots and verified changes, push the branch, update PR #23 with implementation scope and evidence, and mark it ready for review. Do not merge or deploy. Deliver the PR link and representative desktop/mobile screenshots; call out non-trading-grade source limitations and manual holding maintenance.

## Self-Review Mapping

Spec market/identity boundary -> Tasks 3, 5, 6; persistence/Decimal/revisions -> Tasks 1, 2; data quality/timeouts/company-action limitation -> Tasks 1, 3, 6; calendar/schedule/retries/snapshots -> Tasks 2, 4; APIs/privacy/legacy compatibility -> Task 5; interface/research handoff -> Task 6; headless screenshots/PR/no deployment -> Task 7. Opportunity ranking, live trading, imports and personalized graph inputs remain out of scope.
