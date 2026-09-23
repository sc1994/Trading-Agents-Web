# Gitea Gateway Auto-Deploy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically deploy the exact Gitea `main` push SHA on the gateway, preserving the existing local port and deployment rollback.

**Architecture:** GitHub remains the source and syncs `main` to Gitea. Gitea's `gateway` Runner responds only to its own repository's `main` push, verifies checkout SHA, and calls the existing deployment script. The script no longer requires dispatch-only manual attestations but retains SHA validation and candidate/rollback behavior.

**Tech Stack:** Gitea Actions YAML, Bash, Docker Compose, pytest with existing fake-command infrastructure.

**Spec:** `docs/superpowers/specs/2026-09-23-gitea-gateway-auto-deploy-design.md`

## Global Constraints

- Keep `127.0.0.1:7681:8080`, project `trading-agents-web`, service `web`, runner `gateway`.
- Keep repository and server identity guard, complete lowercase SHA checks, pinned checkout, read-only checkout permissions, revision label, candidate verification, serial deployment, and rollback.
- Do not change proxy, TLS, domain, application authentication, persistent volumes, production host configuration, or GitHub source/sync workflow.
- The workbench has no login; loopback binding does not prevent exposure via a separately configured reverse proxy. Do not assert that this change protects ingress.
- Do not trigger production deployment; merge/sync to `main` is the future deployment trigger, after the PR is reviewed.

---

### Task 1: Remove Dispatch Attestations From The Deployment Script

**Files:**
- Modify: `scripts/deploy_gateway_web.sh:10-35`
- Modify/Test: `tests/infra/test_gateway_web_deployment.py:529-595`

**Interfaces:**
- Consumes: one positional, exact lowercase 40-character SHA; no release/ingress environment variables.
- Produces: same `bash scripts/deploy_gateway_web.sh "$DEPLOY_SHA"` interface for Task 2.

- [ ] **Step 1: Write a failing behavioral test.** Replace the four manual-attestation parameter cases with a test that calls the fake-command deployment using `MANUAL_RELEASE_SHA=""` and `PRIVATE_INGRESS_VERIFIED_SHA=""`, asserts exit status 0, and asserts the fake recorded a `docker build` followed by a `docker-compose up`. Leave the existing invalid-SHA-before-Docker and candidate/rollback tests intact.

```python
def test_deploy_from_push_needs_no_manual_attestations(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(MANUAL_RELEASE_SHA="", PRIVATE_INGRESS_VERIFIED_SHA="")
    assert result.returncode == 0, result.stderr
    invoked = commands(fake_commands.calls())
    assert any(call[:2] == ["docker", "build"] for call in invoked)
    assert any(call[0] == "docker-compose" and "up" in call for call in invoked)
```

- [ ] **Step 2: Confirm RED.** Run `pytest -q tests/infra/test_gateway_web_deployment.py::test_deploy_from_push_needs_no_manual_attestations`; expect failure from the old release approval guard, before any fake external command.
- [ ] **Step 3: Remove only the two environment-variable SHA attestations and the now-inaccurate comment from the script.** Keep positional count/SHA validation and all later code unchanged. Remove the two default attestation entries from `FakeCommands.run`'s test environment; the new test's explicit blank overrides remain to prove no stale gate is consulted.
- [ ] **Step 4: Confirm GREEN and regression.** Run `pytest -q tests/infra/test_gateway_web_deployment.py` and `bash -n scripts/deploy_gateway_web.sh`; both exit 0. Check that `test_rejects_short_or_uppercase_sha_before_docker` and rollback tests still execute.
- [ ] **Step 5: Commit.** `git add scripts/deploy_gateway_web.sh tests/infra/test_gateway_web_deployment.py` then `git commit -m 'fix(deploy): allow exact-SHA push releases'`.

### Task 2: Trigger Gitea Main Push And Update Release Documentation

**Files:**
- Modify: `.gitea/workflows/deploy-gateway-web.yml:1-50`
- Modify/Test: `tests/infra/test_gateway_web_deployment.py:45-105`
- Modify: `docs/operations/gateway-web-deployment.md:1-27`

**Interfaces:**
- Consumes: Task 1's positional deployment script and SHA validation.
- Produces: Gitea `main` push -> SHA-checked `gateway` deploy; no manual workflow inputs or attestations.

- [ ] **Step 1: Rewrite the workflow tests to assert the new contract.** Keep PINNED_CHECKOUT, read-only permissions, serial group, secrets exclusion, exact checkout and script call. The event test requires `set(workflow["on"]) == {"push"}`, `workflow["on"]["push"]["branches"] == ["main"]`, runner `gateway`, and the existing server/repository/ref guard ending in `github.event_name == 'push'`. The deploy environment must equal `{"DEPLOY_SHA": "${{ github.sha }}"}`; no manual input expressions anywhere in the workflow command data.

```python
assert set(workflow["on"]) == {"push"}
assert workflow["on"]["push"]["branches"] == ["main"]
assert deploy["env"] == {"DEPLOY_SHA": "${{ github.sha }}"}
assert "github.event.inputs" not in json.dumps(workflow_command_data(workflow))
```

- [ ] **Step 2: Confirm RED.** Run `pytest -q tests/infra/test_gateway_web_deployment.py::test_gitea_workflow_is_restricted_to_gateway_main tests/infra/test_gateway_web_deployment.py::test_gitea_workflow_deploys_only_the_checked_out_full_sha`; expect failures on old dispatch/attestation contract.
- [ ] **Step 3: Change the workflow only as required.** Rename to reflect automatic gateway release; use `on: push: branches: [main]`, retain pinned checkout, fixed repository/server/ref condition and change event guard to `'push'`. Remove `workflow_dispatch.inputs` and the two manual env entries; keep `DEPLOY_SHA` and the existing checkout/validation/script call unchanged. Maintain the existing `concurrency` and `permissions` blocks.
- [ ] **Step 4: Update the runbook's current-policy introduction.** Replace the first section's claims that production may only use manual dispatch and its instructions to enter release/ingress SHAs with an explicit automatic Gitea `main` push description. State that the workbench has no login, that public proxy exposure is a separate operator decision, and that `127.0.0.1:7681` is not a privacy guarantee. Label the later historical first-release phases as legacy reference, not steps to execute for the current auto-release. Preserve backup and rollback instructions rather than rewriting history.
- [ ] **Step 5: Confirm GREEN and integration.** Run `pytest -q tests/infra/test_gateway_web_deployment.py`, `pytest -q`, `ruff check .`, `git diff --check`, and `bash -n scripts/deploy_gateway_web.sh`. Inspect the diff to ensure no production operations, proxy/port edits, or hidden manual env requirements.
- [ ] **Step 6: Commit.** `git add .gitea/workflows/deploy-gateway-web.yml tests/infra/test_gateway_web_deployment.py docs/operations/gateway-web-deployment.md` then `git commit -m 'ci: deploy gateway web on Gitea main push'`.

## Handoff

Request a separate spec and code-quality review after each task and a whole-branch review. Push a new GitHub PR branch only after local verification; PR CI does not deploy. Once the user merges, observe the GitHub sync, Gitea run, and gateway service read-only. No production deployment is authorized by this plan itself.
