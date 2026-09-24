# Provider Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Manage joined built-in and multiple named OpenAI-compatible suppliers without displaying every credential form at once.

**Architecture:** Persist provider metadata and separate keys in private settings storage; expose CRUD through the web API. Resolve custom IDs to the existing generic compatible client only when executing a task. Render joined entries and focused dialogs in Ant Design, then use joined choices in both model selectors.

**Tech Stack:** Python 3, FastAPI/Pydantic, SQLite, pytest; React 19, TypeScript, Ant Design 5, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-09-24-provider-management-design.md`

## Global Constraints

- Custom provider IDs are stable `custom:<uuid>`; names must not be used as IDs.
- Never return full keys or persist them in provider metadata, task params, or reports.
- Accept validated HTTP and HTTPS endpoint URLs, including localhost/private networks; never make network requests on save and never follow redirects on connection tests.
- Deleting the default provider or one used by queued, running, or interrupted tasks must fail.
- Use the current Ant Design language and layout; deliver headless screenshots, never a development URL for user acceptance.
- Follow red-green-refactor for each behavior and run baseline tests before edits; this is already a linked worktree (`alert-dingo`).

## File ownership

- `web/settings.py`: provider metadata validation/persistence, public projection, credential operations, run-time resolution, connection tests.
- `web/store.py`: a targeted query for unfinished tasks using a provider; settings remain in the existing private settings table.
- `web/api.py`: request/response shapes and provider CRUD endpoints.
- `web/validation.py`: joined-provider selection and custom model ID validation.
- `web/client/src/api.ts`: typed CRUD calls; `web/client/src/configuration.tsx`: dynamic option/label helpers.
- `web/client/src/pages/Settings.tsx`: joined list and add/edit dialogs; `Start.tsx`: joined supplier picker and keyless custom handling; `styles.css`: compact list and mobile rules.
- Matching `tests/web/*` and `web/client/src/pages/*.test.tsx` hold behavior tests. `web/client/scripts/acceptance.mjs` covers browser screenshots.

### Task 1: Provider registry and lifecycle

**Files:** Modify `web/settings.py`, `web/store.py`; test `tests/web/test_settings.py`.

**Interfaces:** Produce `SettingsService.add_provider(body: dict) -> dict`, `edit_provider(id: str, body: dict) -> dict`, `remove_provider(id: str) -> dict`, `joined_provider(id: str) -> dict`, and `public()["providers"]: list[dict]`; each entry exposes `id`, `name`, `kind`, `base_url`, and masked `key`.

- [ ] **Step 1: Add failing tests for migration, two custom entries, duplicate names, URL validation, replacement/clear and guarded deletion.** For example:

```python
def test_custom_providers_are_distinct_and_secrets_are_masked(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    first = service.add_provider({"kind": "custom", "name": "Desk", "base_url": "http://127.0.0.1:1234/v1", "key": "secret-12345"})
    second = service.add_provider({"kind": "custom", "name": "Cloud", "base_url": "https://gateway.example/v1", "key": "other-56789"})
    assert first["providers"][-1]["id"] != second["providers"][-1]["id"]
    assert "secret-12345" not in str(service.public())
    assert service.public()["providers"][-2]["key"]["last4"] == "2345"
```

- [ ] **Step 2: Run** `pytest tests/web/test_settings.py -q`; expect missing `add_provider` failure.
- [ ] **Step 3: Implement metadata validation and atomic updates.** Parse stored `providers` JSON; when absent, initialize from default, saved `key:*` names and configured environment keys. Keep metadata JSON secret-free, and store `key:<id>` separately. Apply URL validation with `urllib.parse.urlsplit` (scheme, hostname, userinfo, query, fragment, length), reject malformed ports and whitespace. Update the metadata and key in one `Store.update_settings` call. Add `Store.has_unfinished_tasks_for_provider(provider: str) -> bool` using `json_extract(params, '$.provider')` and `status IN ('queued','running','interrupted')`. Preserve built-in settings-PATCH key compatibility and return masked keys.

```python
def has_unfinished_tasks_for_provider(self, provider: str) -> bool:
    with self.transaction() as db:
        return db.execute(
            "SELECT 1 FROM tasks WHERE json_extract(params, '$.provider')=? "
            "AND status IN ('queued','running','interrupted') LIMIT 1", (provider,)
        ).fetchone() is not None
```

- [ ] **Step 4: Run** `pytest tests/web/test_settings.py -q`; fix failures and add targeted invalid-name, URL, and deletion tests until green.
- [ ] **Step 5: Commit** `git add web/settings.py web/store.py tests/web/test_settings.py && git commit -m "feat: persist joined model providers"`.

### Task 2: HTTP contract and execution mapping

**Files:** Modify `web/api.py`, `web/settings.py`, `web/validation.py`; test `tests/web/test_api.py`, `tests/web/test_settings.py`.

**Interfaces:** Consume Task 1 service methods. Produce `POST /api/settings/providers`, `PATCH /api/settings/providers/{provider_id}`, `DELETE /api/settings/providers/{provider_id}` returning `SettingsView`; `validate_task(raw, defaults)` accepts `defaults["providers"]`.

- [ ] **Step 1: Write failing HTTP and run-config tests.** Exercise POST with custom name/URL/key, GET without raw key, PATCH and DELETE; assert two IDs resolve to different private URLs and keys. Verify selecting an unjoined ID fails, and each custom ID persists in task params while runtime config uses `openai_compatible`.

```python
def test_custom_run_config_uses_generic_client_without_leaking_url(tmp_path):
    service = SettingsService(Store(tmp_path / "web.db"))
    joined = service.add_provider({"kind": "custom", "name": "Gateway", "base_url": "http://localhost:1234/v1", "key": "secret-xyz99"})
    provider = joined["providers"][-1]["id"]
    result = service.resolve_run_config({"provider": provider, "quick_model": "fast", "deep_model": "deep"})
    assert result["config"]["llm_provider"] == "openai_compatible"
    assert result["config"]["backend_url"] == "http://localhost:1234/v1"
    assert result["api_key_env"] == {"OPENAI_COMPATIBLE_API_KEY": "secret-xyz99"}
```

- [ ] **Step 2: Run** `pytest tests/web/test_api.py tests/web/test_settings.py -q`; expect missing routes or wrong provider validation.
- [ ] **Step 3: Extend strict Pydantic input/output types and add the three routes.** Use `kind: Literal["built_in", "custom"]` on create, optional `name`, `base_url`, `key` on edit and explicit `clear_key: bool`; reject conflicting replacement/clear. Ensure path IDs with colon are accepted. Add `providers: list[ProviderView]` to `SettingsView`.

```python
class ProviderView(BaseModel):
    id: str
    name: str
    kind: Literal["built_in", "custom"]
    base_url: str | None
    key: KeyStatus
```

- [ ] **Step 4: Resolve custom IDs through `joined_provider` before model validation; use `openai_compatible` catalog for custom model IDs.** Keep selected ID in returned task params; in private `resolve_run_config` set the generic client, URL and optional key overlay. Update connection tests to use the saved custom URL with timeout `(3,5)`, `allow_redirects=False`, and no raw remote error response. Assert attempts cannot test unjoined IDs.
- [ ] **Step 5: Run** `pytest tests/web/test_api.py tests/web/test_settings.py tests/web/test_runner.py -q`; correct failing contracts.
- [ ] **Step 6: Commit** `git add web/api.py web/settings.py web/validation.py tests/web && git commit -m "feat: route custom providers through compatible client"`.

### Task 3: Typed client and settings management UI

**Files:** Modify `web/client/src/api.ts`, `web/client/src/configuration.tsx`, `web/client/src/pages/Settings.tsx`, `web/client/src/styles.css`, `web/client/src/test/fixtures.ts`; test `web/client/src/pages/Settings.test.tsx`.

**Interfaces:** Consume Task 2 endpoints and `SettingsView.providers`. Expose `WebApi.addProvider(input)`, `editProvider(id, input)`, `removeProvider(id)`; `ModelFields` accepts a custom ID as free-text choice.

- [ ] **Step 1: Write failing component tests for the compact list and custom form.** Assert unjoined providers have no visible key inputs, dialog accepts name/URL/key, save calls typed API, list updates, blank edit key preserves existing key, and removal requires confirmation. Assert default supplier selection contains joined entries only.

```tsx
it("shows joined suppliers without a wall of credential inputs", async () => {
  render(<Settings api={fakeApi} />);
  expect(await screen.findByText("OpenAI")).toBeInTheDocument();
  expect(screen.queryByLabelText("OpenAI API Key")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "加入供应商" }));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});
```

- [ ] **Step 2: Run** `cd web/client && npm test -- --run src/pages/Settings.test.tsx`; expect the add button or dialog assertion to fail.
- [ ] **Step 3: Add API types and calls; fixture responses must include real `providers` metadata.** Use the existing `request()` and explicit JSON bodies to call `/settings/providers` and encoded `/settings/providers/${encodeURIComponent(id)}`. Never write keys to local storage.
- [ ] **Step 4: Replace the providers tab body with a compact list and `Modal` add/edit forms.** Show `PlusOutlined`, `EditOutlined`, `DeleteOutlined`, and `LinkOutlined` actions with accessible labels/tooltips; prevent accidental removal with `Popconfirm`. Keep data-source credential fields unchanged. On API failure leave entered values and show an error. On success replace the settings state and clear password inputs. Use dynamic joined option labels in default-model selector; custom IDs use existing free-text `ModelFields` behavior. Add compact list and dialog CSS at desktop/tablet/mobile widths.
- [ ] **Step 5: Run** `cd web/client && npm test -- --run src/pages/Settings.test.tsx && npm run typecheck`; correct failures.
- [ ] **Step 6: Commit** `git add web/client/src && git commit -m "feat: manage joined suppliers in settings"`.

### Task 4: Analysis selection and behavior

**Files:** Modify `web/client/src/pages/Start.tsx`, `web/client/src/configuration.tsx`, `web/client/src/test/fixtures.ts`; test `web/client/src/pages/Start.test.tsx`.

**Interfaces:** Consume `SettingsView.providers` and dynamic options from Task 3; task POST continues sending the opaque selected provider ID.

- [ ] **Step 1: Write failing component tests.** With a fixture containing a custom provider, assert its name appears in selection, free-text model IDs can be submitted, and a custom keyless endpoint can create a task. Verify a missing built-in key still prompts the user to configure it.

```tsx
it("allows a joined keyless custom endpoint", async () => {
  const provider = "custom:11111111-1111-4111-8111-111111111111";
  vi.mocked(fakeApi.getSettings).mockResolvedValue({
    ...settings,
    provider, quick_model: "local-fast", deep_model: "local-deep",
    providers: [...settings.providers, { id: provider, name: "Local", kind: "custom", base_url: "http://localhost:1234/v1", key: { configured: false, last4: null } }],
  });
  render(<Start api={fakeApi} navigate={navigate} />);
  await userEvent.type(await screen.findByLabelText("股票 / 资产代码"), "F");
  await userEvent.click(screen.getByRole("button", { name: "开始分析" }));
  await waitFor(() => expect(fakeApi.createTask).toHaveBeenCalledWith(
    expect.objectContaining({ provider, quick_model: "local-fast", deep_model: "local-deep" }),
  ));
});
```

- [ ] **Step 2: Run** `cd web/client && npm test -- --run src/pages/Start.test.tsx`; expect the current credential guard to reject the custom provider.
- [ ] **Step 3: Derive `Select` choices from `settings.providers`.** Resolve name from the joined list, not the static label map; bypass built-in key requirement only for custom endpoints, while the server still validates joined IDs. Keep quick/deep IDs required.
- [ ] **Step 4: Run** `cd web/client && npm test -- --run src/pages/Start.test.tsx && npm run build`; correct failures.
- [ ] **Step 5: Commit** `git add web/client/src && git commit -m "feat: select custom suppliers for analysis"`.

### Task 5: Integration verification and screenshots

**Files:** Modify `web/client/scripts/acceptance.mjs` for fixture and screenshot assertions; test existing Python and frontend suites.

**Interfaces:** Task 1-4 outcomes; no new production API.

- [ ] **Step 1: Extend acceptance API fixtures to include joined providers and custom CRUD responses.** Browser assertions should open the join modal, submit a custom provider, observe the compact row, and capture desktop and mobile screenshots to `docs/design/assets/` with descriptive provider-management names.
- [ ] **Step 2: Run** `pytest tests/web -q`, `cd web/client && npm test -- --run`, `cd web/client && npm run build`, then `cd web/client && npm run acceptance`. Read full outputs and fix regressions, including former tests that expected every credential field on initial render.
- [ ] **Step 3: Inspect generated screenshots for overflow/overlap and readable text at desktop/mobile sizes.** Use the image-view tool or equivalent headless pixel inspection; revise CSS if needed and repeat the screenshot run. Deliver the screenshot artifacts to the user, not a local URL.
- [ ] **Step 4: Check** `git diff --check` and `git status --short`; commit scoped fixture and screenshot changes with `git add web/client/scripts/acceptance.mjs docs/design/assets && git commit -m "test: cover provider management in browser"`.
