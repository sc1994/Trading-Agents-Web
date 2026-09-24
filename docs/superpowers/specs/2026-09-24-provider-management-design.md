# Provider Management Design

## Goal and context

Replace the settings page's all-provider credential form with a managed list of joined providers. A user can join a built-in provider or create multiple named OpenAI-compatible providers with distinct API URLs and credentials. The selected providers can be used for default models and new analyses. Existing stored credentials, model defaults, and tasks must remain usable.

## Approach

Use the existing `openai_compatible` model client for all user-defined endpoints, with an opaque stable provider ID (`custom:<uuid>`) in web settings and task parameters. At run time, translate the ID to `llm_provider=openai_compatible`, resolve its saved URL into `backend_url`, and overlay its credential as `OPENAI_COMPATIBLE_API_KEY` only within the runner's existing scoped environment. Do not add user-defined providers to the global model registry: those definitions belong to the web workbench, not the CLI.

An alternative would add each custom name to the shared runtime registry, creating process-global mutable configuration and possible collisions with built-in names. A single generic custom-provider slot would avoid the mapping but would not meet the multiple-provider requirement. The web-scoped mapping preserves stable task identity without changing the core client.

## Persistence and API

- Store joined provider metadata as JSON in the existing private SQLite settings table, using server-generated IDs. Each record has `id`, `name`, `base_url` (custom only), and `kind` (`built_in` or `custom`). Built-in records reference supported catalog IDs; custom records use `custom:<uuid>`. Never store a key inside this JSON document. Store each key separately under `key:<id>` in the existing private settings table.
- `GET /api/settings` adds `providers` (joined metadata plus masked key status); retain the existing `keys` map and default model fields for compatibility. Existing installations are initialized from their current default provider and any stored or environment-provided credentials; preserve existing keys and settings. The response never includes a credential value.
- `POST /api/settings/providers` joins an available built-in provider or creates a custom provider with name, URL, and optional key. `PATCH /api/settings/providers/{id}` changes the custom name/URL and, for either kind, optionally replaces or clears its key. `DELETE /api/settings/providers/{id}` removes the joined entry and its stored key; an environment-provided built-in key remains in the environment. Reject removing the current default or a provider used by queued, running, or interrupted tasks, with a clear response; a user must first change the default or resolve the outstanding task. Do not allow editing the built-in provider name/URL.
- Keep the existing settings PATCH for defaults and data-source keys; credential changes for joined providers use the provider endpoints. The connection-test endpoint accepts only joined providers. Existing API clients sending built-in keys through settings PATCH remain supported.
- Reject duplicate built-in joins and empty/duplicate (case-insensitive) custom names. Validate name length (1-64), URL length (up to 2048), `http` or `https` scheme, hostname, no embedded credentials, query, or fragment; normalize trailing slash. HTTP, including loopback and private network addresses, is intentionally allowed. Key length and newline restrictions match the existing service. Never issue a network request while creating or editing a provider.
- Connection tests use the saved key and the selected custom provider's `{base_url}/models`, with the current bounded timeout and redirects disabled. Redact remote errors and avoid returning URL/key details. Keyless custom endpoints can be used (the existing compatible client supplies its placeholder credential); testing them does not require a saved key.

## Task and model behavior

- `validate_task` accepts joined IDs instead of only catalog IDs. Custom model IDs follow the existing generic catalog rule: nonempty, at most 128 characters, not the literal `custom`. Built-in catalog validation remains unchanged.
- The custom ID remains in saved task params and the default-provider field so the UI can show the user's chosen name. `resolve_run_config` translates it only in the private runtime config. The resolved URL is never copied into the task params, reports, or public task response.
- Choosing a new custom provider in default models or the analysis form requires entering quick and deep model IDs. Existing default model values are preserved when the provider remains unchanged. A joined built-in provider uses current catalog defaults.
- A deleted custom provider cannot be selected for future tasks. Completed historical tasks retain their ID in history; they do not expose its URL or credential. Outstanding tasks block deletion rather than silently failing on resume or execution.

## Interface

- The providers tab shows a compact list of joined providers: name, built-in/custom indicator, masked key status, and edit/test/remove actions. No full key inputs appear in the list. An empty state has a single join action.
- `加入供应商` opens a dialog with a built-in choice or a custom OpenAI-compatible choice. The custom form requests name, API URL, and optional API key. Saving closes the dialog and updates the list; no connection request occurs automatically.
- Editing a provider opens a focused dialog. Password fields start empty and leave the key unchanged when blank; replacing and clearing are explicit actions. The URL/name of a built-in provider are read-only. Removal uses confirmation and explains any default/unfinished-task restriction.
- Default-model and analysis provider selectors display only joined providers and show custom names. Built-in model suggestions remain; custom providers use free-text model IDs. Retain the current Ant Design vocabulary and the existing mobile tab layout; list rows and dialog fields fit narrow screens without horizontal overflow.
- Data-source credentials and analysis preferences stay on their existing tabs. Saving default models remains a separate action from joining/editing providers, with errors and unsaved values retained.

## Verification

- Backend tests cover migration of legacy settings, multiple custom providers, duplicate/invalid input, secret redaction, join/edit/remove lifecycle, run-config isolation, custom model validation, scoped connection tests, and deletion guards. HTTP tests cover request shape and error responses.
- Frontend tests cover the compact initial list, join/edit/remove flows, secret handling, custom selections and model IDs in settings and analysis, responsive behavior. Build/typecheck and relevant Python suites run before completion.
- Generate headless desktop/mobile screenshots of the providers view and join dialog for user review; do not require the user to open a local development URL.
