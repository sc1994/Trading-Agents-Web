# Gitea Gateway Web Deployment Design

## Context

`sc1994/Trading-Agents-Web` is authoritative on GitHub. The repository
currently contains a CLI application and does not expose a long-running HTTP
service. The first deployed web surface is intentionally an empty HTML page;
its purpose is to establish a tested, auditable build-and-deploy path before
product web features exist.

The gateway host is `billsys` (`192.168.31.2`). Its Gitea repository
`suncheng/Trading-Agents-Web` currently has one unrelated root commit,
`052251b1a133a3aef9506b864c30d96c628c45be`, whose tree contains only an empty
`README.md`. It has no workflows and has recorded zero Actions runs, jobs, or
schedules. GitHub `main` is therefore not yet synchronized to Gitea.

The gateway has a running Gitea Actions runner currently identified as
`gitea-runner-gatway`. Nginx Proxy Manager already routes
`trading.suncheng.online` to `127.0.0.1:7681`; that port is currently closed.
Historical TradingAgents Dockge stacks and images exist on the host but are
stopped and are not artifacts of this repository.

This design extends, and where necessary supersedes, the prior local-image-only
design. It does not turn the TradingAgents CLI into a web application.

## Goals

- Keep GitHub `main` as the only authoritative source.
- Make normal GitHub `main` pushes synchronize to Gitea `main` without force.
- Use a gateway-specific Gitea runner label to build and deploy the web image.
- Serve an empty HTML page at `trading.suncheng.online`.
- Expose a dependency-free `/healthz` endpoint for deployment verification.
- Bind the application only to `127.0.0.1:7681`; Nginx Proxy Manager remains
  the external entry point.
- Make every deployed image traceable to the exact Gitea/GitHub commit SHA.
- Leave existing runtime secrets, TradingAgents data, historical stacks, and
  unrelated containers untouched.

## Non-Goals

- No TradingAgents analysis form, HTTP API, authentication, or report viewer.
- No LLM or market-data credentials in the web container or workflow.
- No remote image registry, Kubernetes, blue-green platform, or automatic
  rollback service.
- No CI-managed Nginx Proxy Manager changes.
- No deletion of historical TradingAgents images, volumes, or Dockge stacks.
- No automatic repair of future Gitea divergence.

## Considered Approaches

### Repository-owned Gitea workflow on the gateway runner (selected)

The repository contains the service, Compose definition, deployment script,
tests, and Gitea workflow. A push to synchronized Gitea `main` dispatches only
to a runner carrying the `gateway` label. This keeps the deployed behavior and
its automation versioned together and produces direct commit-to-runtime
traceability.

### Manually managed Dockge stack

Dockge would fit existing gateway operations, but repository updates would not
naturally trigger a deployment and the checked-in deployment contract could
drift from the host. It remains useful for unrelated historical stacks but is
not the owner of this service.

### Registry-based build and pull deployment

Building elsewhere and pulling an immutable registry image would separate
build and runtime privileges. For a dependency-free empty page on a single
host, the registry, credentials, retention, and pull orchestration add cost
without a current operational benefit.

## Architecture

### Source synchronization

GitHub Actions remains the only component allowed to update Gitea `main`.
Normal synchronization uses a single non-force refspec,
`HEAD:refs/heads/main`, followed by an exact SHA comparison.

The current unrelated Gitea root prevents the first fast-forward. A one-time
operator action performs these guarded steps:

1. Re-read Gitea `main` and require it to equal
   `052251b1a133a3aef9506b864c30d96c628c45be`.
2. Verify that commit has no parent and its tree contains only `README.md`.
3. Create the annotated backup tag
   `pre-github-sync-20260920-052251b1` at that exact commit.
4. Verify the tag resolves to the expected commit.
5. Replace only `refs/heads/main` using an explicit force-with-lease for the
   known old SHA; do not use mirror push, wildcard refspecs, or ref deletion.
6. Verify Gitea `main` exactly equals the checked-out GitHub `main` SHA.

If any observed SHA or tree differs, the operation stops without changing
Gitea. The initialization operation cannot accept an arbitrary old SHA. Once
the fixed old root is no longer `main`, later divergence is reported rather
than overwritten.

### Web service

`web/server.py` uses only the Python standard library. It serves the exact
contents of `web/index.html` for `/` and `/index.html`, returns `ok\n` from
`/healthz`, and returns 404 for unknown paths. The HTML page intentionally has
no visible content.

`web/Dockerfile` uses Python 3.12 Alpine, runs as a non-root user, and embeds
only the server and page. The Compose service:

- binds `127.0.0.1:7681` to container port `8080`;
- uses `restart: unless-stopped`;
- has a Docker health check against `/healthz`;
- is read-only, drops all Linux capabilities, enables
  `no-new-privileges`, and uses a small `tmpfs` for `/tmp`;
- has no `env_file`, application secret, host data mount, or Docker socket.

The Compose project name is fixed as `trading-agents-web`. The running image is
`trading-agents-web-ui:<40-character commit SHA>`, and both image and container
carry `org.opencontainers.image.revision=<SHA>` metadata.

### Deployment workflow

`.gitea/workflows/deploy-gateway-web.yml` responds to `main` pushes and an
explicit manual dispatch. The job:

- validates the Gitea server URL, repository name, `refs/heads/main`, and a
  lowercase 40-character commit SHA;
- uses `runs-on: gateway`, never the generic `ubuntu-latest` label;
- has only `contents: read` repository permission;
- uses a pinned checkout action with credentials disabled after checkout;
- passes the immutable checked-out SHA to `scripts/deploy_gateway_web.sh`;
- uses a fixed concurrency group with `cancel-in-progress: false` so an older
  deployment cannot overtake a newer one within this workflow.

The workflow never receives the GitHub-to-Gitea token or application API keys.
It requires the runner's existing host Docker access; this remains
host-root-equivalent and is restricted operationally by the dedicated runner
label and workflow guards, not by Docker itself.

### Deployment script

The deployment script validates the SHA and fixed port, selects Docker Compose
v2 (or the existing compatible `docker-compose` command), and performs:

1. Build the SHA-tagged candidate image with revision metadata.
2. Start a temporary candidate container without host data or secrets and
   verify both `/healthz` and the exact blank page.
3. Remove the temporary candidate container.
4. Record the currently deployed image reference, if one exists.
5. Reconcile the fixed Compose project to the candidate image.
6. Verify Docker health plus `http://127.0.0.1:7681/healthz` and the exact page.
7. On post-cutover verification failure, restore the recorded prior image when
   available and report failure; on first deployment, leave the failed service
   stopped.

A build or candidate-smoke failure does not touch the running service. The
script does not prune images or change Nginx Proxy Manager. Old images remain
available for manual diagnosis and rollback; retention can be added when image
growth becomes material.

## Runner And Gateway Preparation

Before synchronizing the deployment workflow, the gateway operator adds the
`gateway` label to `gitea-runner-gatway` while retaining its existing labels,
restarts only that runner if required by its configuration mechanism, and
verifies it returns online with the new label. No repository workflow may use
the misleading `emailbill` label for this deployment.

The operator also confirms:

- `127.0.0.1:7681` remains unbound immediately before first deployment;
- the historical Dockge `tradingagents` stack remains stopped;
- Nginx Proxy Manager still maps `trading.suncheng.online` to
  `127.0.0.1:7681`;
- Docker and Compose are available to the gateway runner.

These are preflight checks, not permissions to remove or rewrite historical
stacks.

## Failure Handling

- Initialization precondition mismatch: make no ref changes and escalate the
  newly observed Gitea state.
- Normal synchronization non-fast-forward: fail without force.
- Wrong Gitea server, repository, branch, or runner: skip/fail before Docker
  mutation.
- Build or candidate smoke failure: keep the current service unchanged.
- Port conflict: fail before cutover and report the owning process/container.
- Cutover health failure: restore the prior image when one existed; otherwise
  stop the failed first deployment.
- Nginx Proxy Manager route failure: leave the healthy loopback service
  running and report the proxy as a separate operational failure.
- No failure path deletes application data, historical stacks, images, or Git
  refs other than the explicitly leased one-time `main` replacement.

## Testing

Tests are written before implementation and cover:

- exact root page bytes, `/healthz`, HEAD behavior, and 404 responses;
- invalid server port configuration;
- non-root image and Compose security settings;
- exact loopback port `127.0.0.1:7681:8080`;
- SHA-tagged image and revision metadata contract;
- workflow platform/repository/ref guards, `gateway` runner label, pinned
  actions, permissions, concurrency, and absence of secrets;
- deployment script validation, candidate-before-cutover ordering, page and
  health verification, and rollback behavior through a fake Docker/Curl
  command harness;
- one-time initialization success and rejection of changed SHA, changed tree,
  lease races, arbitrary old SHA, broad force, mirror, wildcard, and deletion;
- ordinary post-initialization fast-forward synchronization and rejection of
  later divergence.

Repository CI runs the web and infrastructure tests on pull requests and
GitHub `main`. The Gitea deployment workflow performs candidate and live
runtime checks on the gateway.

## Acceptance Criteria

1. The old Gitea root remains reachable through
   `pre-github-sync-20260920-052251b1`, and Gitea/GitHub `main` resolve to the
   same full SHA.
2. A subsequent GitHub `main` commit reaches Gitea through a normal non-force
   push.
3. The Gitea deployment run is assigned to the runner with label `gateway` and
   completes for that synchronized SHA.
4. Exactly one `trading-agents-web` Compose web container is healthy and uses
   `trading-agents-web-ui:<that SHA>` with matching revision metadata.
5. `127.0.0.1:7681/healthz` returns `200` and `ok\n`; `/` returns the checked-in
   empty page byte-for-byte.
6. `trading.suncheng.online` returns the same page through the existing Nginx
   Proxy Manager route.
7. No runtime/application secret, TradingAgents data directory, historical
   stack, or unrelated container is modified.
8. A deliberately invalid candidate is rejected before cutover in tests, and
   the previously healthy service remains selected.

## Delivery Sequence

1. Implement and test the guarded one-time Gitea initialization path.
2. Implement and test the blank web service, image, Compose contract, and
   deployment script.
3. Add and test the Gitea deployment workflow and GitHub CI coverage.
4. Add the gateway runner label and verify runner availability.
5. Execute the one-time guarded Gitea synchronization.
6. Observe the first Gitea build/deploy and verify loopback plus public entry.

Steps 4-6 are operational changes and occur only after the repository changes
pass review and reach GitHub `main`.
