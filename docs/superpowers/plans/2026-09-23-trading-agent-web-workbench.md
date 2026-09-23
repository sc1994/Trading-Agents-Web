# Trading Agent Web Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blank Web page with a private, single-user, desktop-and-mobile TradingAgents research workbench.

**Architecture:** One FastAPI process serves a Vite-built React/Ant Design app and a serial in-process task executor. SQLite persists settings, task snapshots, events and reports; the existing TradingAgents graph streams node results and retains its own Markdown reports and LangGraph checkpoints. The browser reads snapshots, then subscribes to replayable SSE events.

**Tech Stack:** Python 3.12 runtime (retain the repository's Python >=3.10 package floor), FastAPI/Uvicorn, SQLite, yfinance, LangGraph, React, TypeScript, Vite, Ant Design, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-23-trading-agent-web-workbench-design.md`; product decisions and approved screenshots: `docs/design/trading-agent-web-product-definition.md` and `docs/design/assets/trading-agent-web-*.png`.

## Global Constraints

- Private single-user deployment only; do not add accounts, real orders, live portfolio, active cancellation, dark mode, PWA or notifications.
- A single application process and a single execution thread run at most one task at once; the rest remain queued.
- Ratings are `Buy`, `Overweight`, `Hold`, `Underweight`, `Sell`, or `REVIEW`; do not invent confidence/strength or source evidence.
- API keys remain on the server, are never returned whole, and are not recorded in task/event/report snapshots.
- The data directory is persistent and writable by the non-root container user; the image remains read-only with dropped capabilities and no application API keys in build/CI.
- Retain `/healthz` and adjust existing gateway-web CI/deployment assertions intentionally rather than disabling them.
- Search supports codes and English names through bounded `yfinance.Search`, plus manual valid-code fallback.
- Use Ant Design components as the only UI kit; mobile has full functional parity, with bottom navigation and no obscured controls.
- Use the existing `DEFAULT_CONFIG`, `get_model_options`, ticker helpers, `TradingAgentsGraph`, `Propagator`, `SignalProcessor`, and graph checkpoint lifecycle rather than duplicating core financial logic.
- Run focused red/green tests at each task and commit independently; final verification includes `pytest -q`, `ruff check .`, frontend build and desktop/mobile screenshots.

## File Map And Contracts

`web/server.py` becomes the Uvicorn entrypoint, exporting `create_app(data_dir: Path | None = None, executor: GraphRunner | None = None) -> FastAPI`. `web/api.py` owns HTTP validation and response formatting; `web/store.py` owns transactional SQLite persistence; `web/settings.py` owns redacted settings and secret access; `web/search.py` owns bounded cached symbol search; `web/runner.py` owns the TradingAgents stream adapter; `web/worker.py` owns the single task loop and recovery; `web/reports.py` owns source-backed display sections and exports. Keep files limited to their stated responsibilities. `web/__init__.py` makes this importable as a package.

`web/client/` contains the Vite React app: `src/api.ts` typed fetch/SSE client, `src/App.tsx` routing and layout, `src/pages/Start.tsx`, `Run.tsx`, `Report.tsx`, `History.tsx`, `Settings.tsx`, and `src/styles.css` responsive tokens. `web/Dockerfile`, `docker-compose.gateway-web.yml`, the gateway deployment script/workflow tests, `pyproject.toml`, `README.md` and `docs/operations/gateway-web-deployment.md` change only when their respective deliverable needs it. Use `tests/web/` for isolated Web tests. Avoid changing upstream TradingAgents modules unless a focused, tested API defect actually blocks integration.

The frontend exports a `WebApi` interface plus production `webApi` from `src/api.ts`. Page components receive `api: WebApi` for deterministic tests; `App.tsx` passes the production instance. API integration tests share `tests/web/conftest.py`'s `FakeRunner`: `run(task, emit, resume=False)` emits no events and returns `({"final_trade_decision": "Unparseable"}, "REVIEW")`, and `can_resume(task)` returns `False`; tests needing progress or checkpoints supply their own runner. `web/client/src/test/fixtures.ts` implements every `WebApi` method with `vi.fn()` and exports a resettable `fakeApi` and `navigate` spy.

Internal contracts used below (method signatures, not implementation stubs):

- `Store(path: Path)`; `create_task(params: dict) -> str`; `get_task(task_id: str) -> dict | None`; `list_tasks(*, query: str = "", status: str = "", rating: str = "") -> list[dict]`; `claim_next() -> dict | None`.
- `Store.append_event(task_id: str, kind: str, payload: dict) -> int`; `events_after(task_id: str, last_id: int) -> list[dict]`; `save_section(task_id: str, section: str, text: str) -> None`; `finish(task_id: str, rating: str, decision: str) -> None`; `fail(task_id: str, error: str) -> None`; `interrupt_running() -> None`; `delete_task(task_id: str) -> bool`.
- `GraphRunner.run(task: dict, emit: Callable[[str, dict], None], *, resume: bool = False) -> tuple[dict, str]`; `can_resume(task: dict) -> bool`. Callback payloads contain only display-safe sections and statuses.

## Task 1: Persist Tasks, Events And Reports

**Files:** Create `web/__init__.py`, `web/store.py`, `tests/web/test_store.py`; modify `pyproject.toml` only to include `web*` in package discovery if tests/build require it.

**Interfaces:** Produces the `Store` methods in the file map; callers pass JSON-safe config without secrets. A task ID is a UUID string. SQLite foreign keys and transactions enforce all-or-nothing updates; new tasks start `queued`.

- [ ] **Step 1: Write failing tests** for creation/claim order, restart interruption, event cursors, section overwrite and scoped delete. Start with:

```python
def test_claim_and_replay(tmp_path):
    store = Store(tmp_path / "web.db")
    first = store.create_task({"ticker": "NVDA", "date": "2026-09-22"})
    second = store.create_task({"ticker": "AAPL", "date": "2026-09-22"})
    assert store.claim_next()["id"] == first
    assert store.claim_next() is None  # one running task blocks the queue
    event_id = store.append_event(first, "stage", {"name": "analysts"})
    assert store.events_after(first, 0)[0]["id"] == event_id
    assert store.events_after(first, event_id) == []
    store.interrupt_running()
    assert store.get_task(first)["status"] == "interrupted"
    assert store.claim_next()["id"] == second
```

- [ ] **Step 2: Run** `pytest -q tests/web/test_store.py`; expect import failure for `web.store`.
- [ ] **Step 3: Implement** SQLite schema with `tasks`, `events`, `sections`, `settings` tables; use `PRAGMA foreign_keys=ON`, busy timeout and short `BEGIN IMMEDIATE` transactions. `claim_next` first checks running count and atomically claims oldest queued task. Store ISO UTC timestamps, serialize only allowlisted JSON and reject any `api_key` field before persistence. Add tests for `finish` requiring saved decision, `delete_task` refusing running tasks and leaving another task untouched.

```python
with self.transaction(immediate=True) as db:
    running = db.execute("SELECT 1 FROM tasks WHERE status='running' LIMIT 1").fetchone()
    if running:
        return None
    row = db.execute("SELECT id FROM tasks WHERE status='queued' ORDER BY created_at, id LIMIT 1").fetchone()
    if row:
        db.execute("UPDATE tasks SET status='running' WHERE id=?", (row["id"],))
return self.get_task(row["id"]) if row else None
```
- [ ] **Step 4: Run** `pytest -q tests/web/test_store.py` and `ruff check web/store.py tests/web/test_store.py`; expect zero failures.
- [ ] **Step 5: Commit** `web/store.py`, package init, tests and any packaging change with `feat(web): persist research tasks and events`.

## Task 2: Validate Input And Search Symbols

**Files:** Create `web/search.py`, `web/validation.py`, `tests/web/test_search.py`, `tests/web/test_validation.py`.

**Interfaces:** `validate_task(raw: dict, defaults: dict) -> dict` returns a safe normalized task config with `ticker`, `date`, `asset_type`, `analysts`, `depth`, `language`, `provider`, `quick_model`, `deep_model` and debate/risk rounds. `search_symbols(query: str, lookup: Callable | None = None) -> dict` returns `{"results": [{"symbol", "name", "exchange", "type"}], "unavailable": bool}`.

- [ ] **Step 1: Write failing tests** with injected Yahoo lookup, no network:

```python
def test_search_extracts_safe_fields():
    lookup = lambda query, **kwargs: [{"symbol": "NVDA", "shortname": "NVIDIA", "exchDisp": "NASDAQ", "quoteType": "EQUITY", "unsafe": "ignored"}]
    assert search_symbols("NVIDIA", lookup=lookup) == {"results": [
        {"symbol": "NVDA", "name": "NVIDIA", "exchange": "NASDAQ", "type": "EQUITY"}
    ], "unavailable": False}

def test_name_is_not_submitted_as_ticker():
    with pytest.raises(ValueError, match="ticker"):
        validate_task({"ticker": "NVIDIA Corporation", "date": "2026-09-22"}, {
            "provider": "openai", "quick_model": "gpt-5.6-luna",
            "deep_model": "gpt-5.6", "analysts": ["market"], "language": "English",
        })
```

- [ ] **Step 2: Run** `pytest -q tests/web/test_search.py tests/web/test_validation.py`; expect missing-module failures.
- [ ] **Step 3: Implement** bounded lookup using `yfinance.Search(q, max_results=8, news_count=0, lists_count=0, recommended=0, timeout=5)`, ten-minute query cache and 2-64 character server limit. The injectable `lookup(q, **kwargs)` returns the raw quote list; the production adapter returns `yf.Search(...).quotes`. Return `{"results": [], "unavailable": True}` on timeout/rate-limit and `{"results": [], "unavailable": False}` for successful empty search; a separately valid typed ticker remains allowed. Use existing `is_valid_ticker_input`, `normalize_ticker_symbol`, `detect_asset_type`, `filter_analysts_for_asset_type`, `get_model_options`, `date.fromisoformat`, reject empty/future dates, unsupported provider/model, zero analysts, and unsupported depth. Map quick/standard/deep to documented round counts 1/2/3 and allow explicit bounded overrides from advanced settings; validate crypto analyst selection. Keep user-supplied labels out of execution config.

```python
def _yahoo_lookup(query: str, **kwargs) -> list[dict]:
    return yf.Search(query, max_results=8, news_count=0, lists_count=0,
                     recommended=0, timeout=5).quotes

DEPTH_ROUNDS = {"quick": 1, "standard": 2, "deep": 3}
if not ticker.strip() or not is_valid_ticker_input(ticker):
    raise ValueError("ticker must be a valid stock or asset code")
```
- [ ] **Step 4: Run** focused tests and `ruff check web/search.py web/validation.py tests/web/test_search.py tests/web/test_validation.py`; expect pass.
- [ ] **Step 5: Commit** with `feat(web): validate analyses and search instruments`.

## Task 3: Store Settings And Secrets Without Echoing Them

**Files:** Create `web/settings.py`, `tests/web/test_settings.py`; modify `web/store.py` settings primitives if needed.

**Interfaces:** `SettingsService(store: Store)` exposes `public() -> dict`, `update(changes: dict) -> dict`, `resolve_run_config(params: dict) -> dict` and `test_connection(provider: str) -> dict`. Only `resolve_run_config` sees plaintext keys; `public` returns `configured`, `last4` and non-secret defaults.

- [ ] **Step 1: Write failing tests** for replacement, clearing, masked return, absent key and secret-free task data:

```python
def test_key_never_echoes(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    response = service.update({"provider": "openai", "keys": {"openai": "sk-private-1234"}})
    assert response["keys"]["openai"] == {"configured": True, "last4": "1234"}
    assert "sk-private-1234" not in str(service.public())
```

- [ ] **Step 2: Run** `pytest -q tests/web/test_settings.py`; expect import failure.
- [ ] **Step 3: Implement** settings allowlist (provider, model IDs from catalog, language, checkpoint flag, supported credential names). Keep SQLite file in a server-only mode `0700` directory and set database file mode `0600`; never put a stored key into JSON task params or logs. Update key only when explicitly supplied; blank input means unchanged, a dedicated clear operation removes it. Resolve per-run provider credentials without leaking them into event/error payloads; a connection test may perform one bounded provider call, catches and redacts provider errors, and accepts only configured providers/endpoints allowed by the product configuration. Cover environment-provided keys without copying values into browser responses.

```python
def masked_key(value: str | None) -> dict:
    return {"configured": bool(value), "last4": value[-4:] if value else None}

if "openai" in changes.get("clear_keys", []):
    store.delete_setting("key:openai")
elif changes.get("keys", {}).get("openai"):
    store.put_setting("key:openai", changes["keys"]["openai"])
```
- [ ] **Step 4: Run** `pytest -q tests/web/test_settings.py` and `ruff check web/settings.py tests/web/test_settings.py`; expect pass.
- [ ] **Step 5: Commit** with `feat(web): manage private provider settings`.

## Task 4: Convert Graph Stream Into Verifiable Events

**Files:** Create `web/runner.py`, `web/reports.py`, `tests/web/test_runner.py`, `tests/web/test_reports.py`.

**Interfaces:** `GraphRunner.run(task, emit, resume=False) -> (final_state, rating)` and `GraphRunner.can_resume(task) -> bool` conform to file-map contracts; `report_sections(state: dict) -> dict[str, str]` maps only existing report keys; `decision_view(markdown: str) -> dict` returns original five-tier rating/`REVIEW` plus actual known Markdown fields.

- [ ] **Step 1: Write failing tests** using a fake graph stream that emits analyst, debate and final-decision states; assert no invented strength:

```python
def test_report_view_does_not_invent_confidence():
    view = decision_view("**Rating**: Buy\n\n**Executive Summary**: Evidence-based plan")
    assert view["rating"] == "Buy"
    assert "confidence" not in view
    assert "strength" not in view
    assert decision_view("unparseable")["rating"] == "REVIEW"
```

- [ ] **Step 2: Run** `pytest -q tests/web/test_runner.py tests/web/test_reports.py`; expect missing-module failures.
- [ ] **Step 3: Implement** graph adapter following `cli/main.py:run_analysis` and `TradingAgentsGraph._run_graph`: create `TradingAgentsGraph(debug=False, config=run_config, selected_analysts=task["analysts"])`; construct initial state via `graph.propagator.create_initial_state` with instrument context and point-in-time memory context; call `begin_checkpoint`, stream `graph.graph.stream(graph.checkpoint_input(initial), **args)`, and `end_checkpoint` in `finally`. Since `Propagator.get_graph_args()` uses `stream_mode="values"`, compare successive state snapshots and emit only newly changed sections. On completion, preserve `propagate()` post-run semantics: `_log_state`, `memory_log.store_decision`, `clear_checkpoint_on_success` and `save_reports` scoped under a safe task-ID directory; verify each is called once in tests, or introduce a narrowly tested public finalize helper in `tradingagents/graph/trading_graph.py` shared with `propagate` if private-method reuse proves brittle. Do not expose raw message/tool payloads or hidden reasoning as SSE. `can_resume` uses the graph's signature and `checkpoint_step` without constructing a real LLM in the cheap check path.

```python
thread = graph.begin_checkpoint(task["ticker"], task["date"], task["asset_type"])
args = graph.propagator.get_graph_args()
if thread:
    args["config"].setdefault("configurable", {})["thread_id"] = thread
try:
    previous: dict[str, str] = {}
    for state in graph.graph.stream(graph.checkpoint_input(initial), **args):
        for section, content in report_sections(state).items():
            if content and previous.get(section) != content:
                previous[section] = content
                emit("section", {"section": section, "text": content})
finally:
    graph.end_checkpoint()
```
- [ ] **Step 4: Run** focused tests and `ruff check web/runner.py web/reports.py tests/web/test_runner.py tests/web/test_reports.py`; expect pass.
- [ ] **Step 5: Commit** with `feat(web): stream source-backed analysis reports`.

## Task 5: Execute One Task, Restart And Resume Safely

**Files:** Create `web/worker.py`, `tests/web/test_worker.py`; modify `web/store.py` state-transition methods where required.

**Interfaces:** `TaskWorker(store: Store, runner: GraphRunner)` exposes `start()`, `stop()`, `resume(task_id: str) -> dict`, and `rerun(task_id: str) -> dict`; startup calls `store.interrupt_running()` before new claims. The worker owns background execution independently of an HTTP connection.

- [ ] **Step 1: Write failing tests** with blocking/failing fake runners:

```python
def test_worker_serializes_and_preserves_partial_reports(tmp_path):
    store = Store(tmp_path / "web.db")
    first = store.create_task({"ticker": "NVDA", "date": "2026-09-22"})
    second = store.create_task({"ticker": "AAPL", "date": "2026-09-22"})
    runner = RecordingRunner(block_first=True)
    worker = TaskWorker(store, runner)
    worker.start()
    assert runner.wait_until_started(first)
    assert store.get_task(second)["status"] == "queued"
    runner.release_first()
    assert runner.wait_until_started(second)
    worker.stop()
```

- [ ] **Step 2: Run** `pytest -q tests/web/test_worker.py`; expect import failure.
- [ ] **Step 3: Implement** bounded worker wakeups and atomic claim; `emit` first persists each changed section/event then notifies SSE subscribers. On success persist sections and rating/decision before completed event; on error retain sections, mark failed with a redacted category/message and continue queue. At startup mark abandoned running entries interrupted and leave queued entries available. Resume requires interrupted state and compatible checkpoint; requeue same task preserving its ID and original graph-shape params. Rerun creates a different ID and may never inherit the old checkpoint; reject or safely isolate stale same-symbol/date graph threads before starting it. Reject deleting running tasks and prevent deletion of another task's shared checkpoint; do not add active cancellation. Define `RecordingRunner` in the test with `threading.Event` gates for first-start, release and second-start, plus bounded waits and deterministic cleanup; its `run` returns a state with `final_trade_decision` after release.

```python
task = store.claim_next()
if task is not None:
    def emit(kind: str, payload: dict) -> None:
        if kind == "section":
            store.save_section(task["id"], payload["section"], payload["text"])
        store.append_event(task["id"], kind, payload)
        self.notify(task["id"])
    state, rating = runner.run(task, emit, resume=bool(task["resume_requested"]))
    store.finish(task["id"], rating, state["final_trade_decision"])
    store.append_event(task["id"], "completed", {"rating": rating})
```
- [ ] **Step 4: Run** focused tests, including restart/absence of checkpoint, and `ruff check web/worker.py tests/web/test_worker.py`; expect pass.
- [ ] **Step 5: Commit** with `feat(web): run and recover queued analyses`.

## Task 6: Serve JSON API, SSE And Static App

**Files:** Create `web/api.py`, `tests/web/conftest.py`, `tests/web/test_api.py`; modify `web/server.py`, `tests/infra/test_gateway_web.py`, `pyproject.toml` for FastAPI/Uvicorn/httpx dependency.

**Interfaces:** `create_app(data_dir: Path | None = None, executor: GraphRunner | None = None) -> FastAPI` wires store/settings/search/worker into lifespan; `GET /api/tasks/{id}/events` replays `Store.events_after` using SSE `id:` and `data:` and then subscribes to new events.

- [ ] **Step 1: Write failing API tests** with `TestClient`, a temporary database and `FakeRunner` from `tests/web/conftest.py`; assert root, health, POST/GET tasks, search, settings masking, SSE reconnect, 404 and same-origin write protection:

```python
def test_health_and_secret_mask(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, executor=FakeRunner())) as client:
        assert client.get("/healthz").text == "ok\n"
        client.patch("/api/settings", json={"keys": {"openai": "sk-private-1234"}})
        assert "sk-private-1234" not in client.get("/api/settings").text
```

- [ ] **Step 2: Run** `pytest -q tests/web/test_api.py tests/infra/test_gateway_web.py`; expect old handler/import contract failures.
- [ ] **Step 3: Implement** request/response Pydantic models and all spec routes, including `GET /api/tasks/{id}/report.md` exporting persisted source-backed Markdown with a safe download filename. For SSE, read `Last-Event-ID`, send stored events in ascending sequence, heartbeat at a bounded interval, and close on terminal state; test reconnection and no duplicate IDs. Enforce same-origin `Origin` check for all writes; reject cross-origin writes and do not enable wildcard CORS. Serve hashed Vite assets with correct MIME and immutable caching, SPA routes from `index.html`, and preserve `/healthz` body and HEAD behavior. Until Task 7 creates the Vite bundle, serve the existing checked-in `web/index.html` as a development fallback; assert Task 9's production image fails build if the Vite bundle is missing. Migrate gateway tests away from byte-equality with the former blank `web/index.html` while retaining status, security headers, unknown API 404 and port validation coverage.

```python
@router.get("/api/tasks/{task_id}/events")
async def events(task_id: str, request: Request):
    cursor = int(request.headers.get("last-event-id", "0"))
    async def stream():
        for event in store.events_after(task_id, cursor):
            yield f"id: {event['id']}\nevent: {event['kind']}\ndata: {json.dumps(event['payload'])}\n\n"
        # Continue with bounded async notifications and periodic ': ping' heartbeats.
    return StreamingResponse(stream(), media_type="text/event-stream")
```
- [ ] **Step 4: Run** `pytest -q tests/web tests/infra/test_gateway_web.py` and `ruff check web tests/web tests/infra/test_gateway_web.py`; expect pass.
- [ ] **Step 5: Commit** with `feat(web): expose workbench API and event stream`.

## Task 7: Build Responsive Start And Settings Pages

**Files:** Create `web/client/package.json`, `web/client/package-lock.json`, `web/client/index.html`, `web/client/tsconfig.json`, `web/client/vite.config.ts`, `web/client/src/main.tsx`, `App.tsx`, `api.ts`, `styles.css`, `test/fixtures.ts`, `pages/Start.tsx`, `pages/Settings.tsx`, `web/client/src/pages/Start.test.tsx` and `Settings.test.tsx`.

**Interfaces:** `api.ts` exports `WebApi` and `webApi` with `searchSymbols(q)`, `createTask(params)`, `getSettings()`, `saveSettings(changes)` and `testConnection(provider)` with Task 6 routes. App routes `/`, `/tasks/:id`, `/reports/:id`, `/history`, `/settings`; Task 7 initially renders a navigation-safe Ant Design `Empty` state for the three pages implemented in Task 8. `src/test/fixtures.ts` exports a `fakeApi: WebApi` with `vi.fn()` methods and `navigate = vi.fn()`.

- [ ] **Step 1: Create failing React Testing Library tests** for search debounce/selection/manual fallback and masked keys:

```tsx
it('submits selected symbol, not display name', async () => {
  render(<Start api={fakeApi} navigate={navigate} />);
  await userEvent.type(screen.getByLabelText('股票 / 资产代码'), 'NVIDIA');
  await userEvent.click(await screen.findByText('NVDA'));
  await userEvent.click(screen.getByRole('button', { name: '开始分析' }));
  expect(fakeApi.createTask).toHaveBeenCalledWith(expect.objectContaining({ ticker: 'NVDA' }));
});
```

- [ ] **Step 2: Run** `npm --prefix web/client test -- --run`; expect missing test setup/components. Install `react`, `react-dom`, `antd`, `@ant-design/icons`, `react-router-dom`, `vite`, `typescript`, `vitest`, `@testing-library/react`, `@testing-library/user-event`, `jsdom`; lock exact resolved versions in the lockfile.
- [ ] **Step 3: Implement** ConfigProvider semantic color/radius tokens, Ant Design layout/form/select/segmented controls and mobile bottom navigation. Start page uses remote AutoComplete with >=2-character, ~300ms debounce and request cancellation; its value becomes a code only on selection or passes manual-code validation. Advanced settings preserve selected defaults; show inline validation and clear unavailable-search state. Settings uses `Input.Password` with blank meaning unchanged and explicit clear command; never prefill a secret, only show configured/last4. Use Ant Design icons with tooltips and implement loading, empty and error states. Self-host any chosen font, avoid extra UI kit and do not show unimplemented confidence.

```tsx
<ConfigProvider theme={{ token: { colorPrimary: '#1f7a55', borderRadius: 8 } }}>
  <RouterProvider router={router} />
</ConfigProvider>
// AutoComplete onSelect stores option.symbol; onSearch debounces api.searchSymbols(q) by 300ms.
// Submit only a selected symbol or validated manually entered ticker.
```
- [ ] **Step 4: Run** `npm --prefix web/client test -- --run`, `npm --prefix web/client run build` and `npm --prefix web/client run typecheck`; expect success.
- [ ] **Step 5: Commit** with `feat(web): add responsive analysis and settings UI`.

## Task 8: Build Run, Report And History Pages

**Files:** Create `web/client/src/pages/Run.tsx`, `Report.tsx`, `History.tsx`, and matching `.test.tsx`; modify `web/client/src/api.ts`, `App.tsx`, `styles.css`.

**Interfaces:** `api.ts` adds `getTask`, `listTasks`, `subscribeTask(taskId, lastEventId)`, `getReport`, `resumeTask`, `rerunTask`, `deleteTask`; Task 6 routes provide all server data. Live view merges sequenced SSE updates and refreshes server snapshot after disconnect.

- [ ] **Step 1: Write failing component tests** for stage updates, disconnect/replay, `REVIEW`, missing fields, history filters, confirmation delete and mobile accessible nav:

```tsx
it('does not present REVIEW as Hold', async () => {
  const api = { ...fakeApi, getReport: vi.fn().mockResolvedValue({ rating: 'REVIEW', sections: {} }) };
  render(<Report api={api} taskId="task-1" />);
  expect(await screen.findByText('需复核')).toBeInTheDocument();
  expect(screen.queryByText('持有')).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run** `npm --prefix web/client test -- --run`; expect missing-page failures.
- [ ] **Step 3: Implement** grouped stage track and current available report (no estimated percent); SSE reconnect with event ID cursor, stale connection/terminal states and snapshot fallback. Report renders only source-backed executive summary, thesis, optional price target, risk excerpts and real sections using a safe Markdown renderer with raw HTML disabled; use five distinct translated rating labels and `REVIEW`. Include Markdown download from `/api/tasks/{id}/report.md` and a copy-parameters action creating a new task. History offers filters, status-specific action, rerun, resume availability and confirmation before delete. Desktop multi-column layout collapses to single column under 768px; bottom navigation must not cover actionable content; long reports scroll normally on mobile.

```tsx
const ratingLabel: Record<string, string> = {
  Buy: '买入', Overweight: '增持', Hold: '持有',
  Underweight: '减持', Sell: '卖出', REVIEW: '需复核',
};
// Install react-markdown; render <ReactMarkdown skipHtml>{section.text}</ReactMarkdown>.
// Do not infer a strength, risk, target or percentage from stage count.
```
- [ ] **Step 4: Run** client tests, typecheck, build, then use headless Playwright screenshots at `1440x1000` and `390x844` for all five pages and inspect them for clipped text/controls. Use fixture APIs, not live model calls; save acceptance screenshots under a task-specific `docs/design/assets/` prefix only when they represent implemented UI, separate from concept sketches.
- [ ] **Step 5: Commit** with `feat(web): add live tasks reports and history`.

## Task 9: Package, Deploy And Verify Without Application Secrets

**Files:** Modify `web/Dockerfile`, `docker-compose.gateway-web.yml`, `scripts/deploy_gateway_web.sh`, `tests/infra/test_gateway_web_deployment.py`, `tests/infra/test_gateway_web.py`, `.github/workflows/ci.yml` or `.gitea/workflows/deploy-gateway-web.yml` only where current assertions require a real application image, plus `README.md`, `docs/operations/gateway-web-deployment.md`. Add `tests/web/test_runtime_image.py` if useful.

**Interfaces:** Image starts `uvicorn web.server:app` with exactly one worker, non-root. `TRADINGAGENTS_WEB_DATA_DIR` is a durable mounted directory shared by Web SQLite, Markdown reports, memory and graph checkpoints. Existing `/healthz`, port 8080 and loopback-only public binding remain.

- [ ] **Step 1: Write failing deployment checks** asserting `web/Dockerfile` copies built assets and Python package, compose mounts a writable named volume at the data directory while retaining read-only root/cap-drop/no-new-privileges, and gateway smoke works without LLM keys:

```python
def test_web_compose_persists_data():
    compose = load_yaml(COMPOSE)
    web = compose["services"]["web"]
    assert web["read_only"] is True
    assert any("/var/lib/tradingagents-web" in item for item in web["volumes"])
```

- [ ] **Step 2: Run** `pytest -q tests/infra/test_gateway_web.py tests/infra/test_gateway_web_deployment.py`; expect failure on missing volume/runtime.
- [ ] **Step 3: Implement** multi-stage Node frontend build plus Python runtime dependency installation in `web/Dockerfile`, include package/compiled assets, keep non-root and revision label. Add named persistent volume with a one-time owner/migration procedure documented in operations notes; use read-only root plus writable mounted data and small `/tmp`. Preserve CI's no-key health smoke and immutable SHA/revision safeguards, changing only the exact tests/workflow lines incompatible with new image contents. Document private-network-only operation, backup/restore of DB and checkpoint/report dirs, storage permissions and upgrade path; do not invoke production deployment in this task without separate authorization.

```dockerfile
FROM node:22-alpine AS ui
WORKDIR /src/web/client
COPY web/client/package*.json ./
RUN npm ci
COPY web/client/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY tradingagents ./tradingagents
COPY cli ./cli
COPY web ./web
RUN pip install --no-cache-dir . fastapi uvicorn
COPY --from=ui /src/web/client/dist /app/web/client/dist
RUN groupadd --system web && useradd --system --gid web web && \
    mkdir -p /var/lib/tradingagents-web && chown web:web /var/lib/tradingagents-web
USER web
CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```
- [ ] **Step 4: Run** `pytest -q`, `ruff check .`, `npm --prefix web/client test -- --run`, `npm --prefix web/client run typecheck`, `npm --prefix web/client run build`, `docker build -f web/Dockerfile -t trading-agent-web:verification .`, then run the image with a temporary dedicated volume and no application keys to check `/`, `/healthz`, API validation and non-root identity. Inspect desktop/mobile Playwright screenshots and exercise a fake-runner end-to-end flow. If Docker is unavailable, report the unverified container checks rather than claiming them.
- [ ] **Step 5: Commit** with `feat(web): package and verify private workbench` only after the checks and screenshots are reviewed.

## Completion Review

- [ ] Reconcile every requirement in the spec with Tasks 1-9, including phone parity, secret handling, report provenance, checkpoint collision prevention and deployment security.
- [ ] Compare the delivered UI with all approved sketches, documenting intentional deviations where the sketch depicts fields the engine does not provide.
- [ ] Confirm no unrelated changes were overwritten, `git diff --check` succeeds and the worktree status is understood before claiming completion.
