import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.gateway-web.yml"
SCRIPT = ROOT / "scripts/deploy_gateway_web.sh"
INDEX = ROOT / "web/index.html"
GITEA_WORKFLOW = ROOT / ".gitea/workflows/deploy-gateway-web.yml"
CI_WORKFLOW = ROOT / ".github/workflows/ci.yml"
PINNED_CHECKOUT = re.compile(r"actions/checkout@[0-9a-f]{40}")
SHA = "a" * 40
OLD_SHA = "b" * 40
OLD_IMAGE = f"trading-agents-web-ui:{OLD_SHA}"


def load_yaml(path: Path) -> dict[object, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_workflow(path: Path) -> dict[str, object]:
    document = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(document, dict)
    return document


def workflow_command_data(node: object) -> list[object]:
    selected: list[object] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"env", "with", "run"}:
                selected.append(value)
            selected.extend(workflow_command_data(value))
    elif isinstance(node, list):
        for value in node:
            selected.extend(workflow_command_data(value))
    return selected


def test_gitea_workflow_is_restricted_to_gateway_main() -> None:
    workflow = load_workflow(GITEA_WORKFLOW)

    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "trading-agents-web-gateway-deploy",
        "cancel-in-progress": "false",
    }
    job = workflow["jobs"]["deploy"]
    assert job["runs-on"] == "gateway"
    condition = " ".join(job["if"].split())
    assert condition == (
        "${{ (github.server_url == 'http://suncheng.online:14200' || "
        "github.server_url == 'http://192.168.31.2:14200') && "
        "github.repository == 'suncheng/Trading-Agents-Web' && "
        "github.ref == 'refs/heads/main' && github.event_name == 'workflow_dispatch' }}"
    )


def test_gitea_workflow_pins_checkout_and_exposes_no_secrets() -> None:
    workflow = load_workflow(GITEA_WORKFLOW)
    checkout = workflow["jobs"]["deploy"]["steps"][0]

    assert PINNED_CHECKOUT.fullmatch(checkout["uses"])
    assert checkout["uses"] == (
        "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
    )
    assert checkout["with"] == {
        "ref": "${{ github.sha }}",
        "fetch-depth": "1",
        "persist-credentials": "false",
    }
    command_data = json.dumps(workflow_command_data(workflow), sort_keys=True)
    for forbidden in (
        "TRADING_AGENTS_WEB_GITEA_SYNC_TOKEN",
        "OPENAI_API_KEY",
        "ALPHA_VANTAGE_API_KEY",
    ):
        assert forbidden not in command_data


def test_gitea_workflow_deploys_only_the_checked_out_full_sha() -> None:
    workflow = load_workflow(GITEA_WORKFLOW)
    deploy = workflow["jobs"]["deploy"]["steps"][1]

    assert deploy["env"] == {
        "DEPLOY_SHA": "${{ github.sha }}",
        "MANUAL_RELEASE_SHA": "${{ github.event.inputs.release_sha }}",
        "PRIVATE_INGRESS_VERIFIED_SHA": "${{ github.event.inputs.private_ingress_verified_sha }}",
    }
    run = deploy["run"]
    assert run.startswith("set -Eeuo pipefail\n")
    assert "*[!0-9a-f]*|'') exit 2" in run
    assert 'test "${#DEPLOY_SHA}" -eq 40' in run
    assert 'test "$(git rev-parse HEAD)" = "$DEPLOY_SHA"' in run
    assert 'bash scripts/deploy_gateway_web.sh "$DEPLOY_SHA"' in run


def gateway_ci_job() -> dict[str, object]:
    workflow = load_workflow(CI_WORKFLOW)
    return workflow["jobs"]["gateway-web-image"]


def test_github_ci_test_job_fetches_full_history_for_provenance_checks() -> None:
    workflow = load_workflow(CI_WORKFLOW)
    checkout = workflow["jobs"]["test"]["steps"][0]

    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"] == {"fetch-depth": "0"}


def test_github_ci_builds_gateway_web_image_from_the_checked_out_sha() -> None:
    job = gateway_ci_job()
    checkout = job["steps"][0]
    verify = job["steps"][1]
    run = verify["run"]

    assert job["runs-on"] == "ubuntu-latest"
    assert PINNED_CHECKOUT.fullmatch(checkout["uses"])
    assert checkout["uses"] == (
        "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683"
    )
    assert checkout["with"] == {
        "ref": "${{ github.sha }}",
        "fetch-depth": "1",
        "persist-credentials": "false",
    }
    assert verify["env"] == {
        "IMAGE_REF": "trading-agents-web-ui:${{ github.sha }}"
    }
    assert "docker build" in run
    assert '--label "org.opencontainers.image.revision=${GITHUB_SHA}"' in run
    assert '--tag "$IMAGE_REF"' in run
    assert "--file web/Dockerfile" in run
    assert "--privileged" not in run


def test_github_ci_inspects_revision_and_rejects_a_root_image_user() -> None:
    run = gateway_ci_job()["steps"][1]["run"]

    assert "docker image inspect" in run
    assert 'index .Config.Labels "org.opencontainers.image.revision"' in run
    assert 'test "$built_revision" = "$GITHUB_SHA"' in run
    assert ".Config.User" in run
    assert 'case "$image_user" in' in run
    assert "0:*" in run
    assert "root:*" in run


def test_github_ci_runs_the_candidate_with_production_security_constraints() -> None:
    run = gateway_ci_job()["steps"][1]["run"]

    for option in (
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--tmpfs /tmp:rw,noexec,nosuid,size=16m",
        "--publish 127.0.0.1::8080",
    ):
        assert option in run
    assert 'docker port "$candidate_name" 8080/tcp' in run
    assert '"${candidate_url}/healthz"' in run
    assert '"${candidate_url}/"' in run
    assert 'cmp -s "$health_response" "$health_expected"' in run
    assert 'cmp -s "$page_response" "$tmp_dir/index.expected"' in run


def test_github_ci_candidate_check_is_bounded_and_always_cleaned_up() -> None:
    verify = gateway_ci_job()["steps"][1]
    run = verify["run"]

    assert verify["timeout-minutes"] == "10"
    assert "trap cleanup EXIT INT TERM" in run
    assert 'docker rm --force --volumes "$candidate_name"' in run
    assert "for attempt in {1..30}" in run
    assert "--connect-timeout 2" in run
    assert "--max-time 5" in run
    assert "while true" not in run


def test_github_ci_validates_compose_with_the_built_image_and_revision() -> None:
    run = gateway_ci_job()["steps"][1]["run"]

    assert 'TRADINGAGENTS_WEB_IMAGE="$IMAGE_REF"' in run
    assert 'TRADINGAGENTS_WEB_REVISION="$GITHUB_SHA"' in run
    assert (
        "docker compose --file docker-compose.gateway-web.yml config --quiet"
        in run
    )


def test_compose_binds_only_fixed_loopback_port_and_has_no_secrets() -> None:
    service = load_yaml(COMPOSE)["services"]["web"]

    assert service["image"] == "${TRADINGAGENTS_WEB_IMAGE:?required}"
    assert service["ports"] == ["127.0.0.1:7681:8080"]
    assert service["restart"] == "unless-stopped"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=16m"]
    assert "env_file" not in service
    assert "environment" not in service
    assert "/healthz" in " ".join(service["healthcheck"]["test"])


def test_compose_keeps_all_workbench_state_in_a_writable_named_volume() -> None:
    compose = load_yaml(COMPOSE)
    assert compose["services"]["web"]["volumes"] == [
        "web-data:/var/lib/tradingagents-web:rw"
    ]
    assert "web-data" in compose["volumes"]


def test_image_packages_the_built_client_and_single_worker_python_runtime() -> None:
    recipe = (ROOT / "web/Dockerfile").read_text()
    assert "FROM node:22-alpine AS ui" in recipe
    assert "npm ci" in recipe
    assert "npm run build && test -s dist/index.html" in recipe
    assert "FROM python:3.12-slim" in recipe
    assert "COPY tradingagents ./tradingagents" in recipe
    assert "pip install --no-cache-dir ." in recipe
    assert "COPY --from=ui /src/web/client/dist ./web/client/dist" in recipe
    assert "TRADINGAGENTS_WEB_DATA_DIR=/var/lib/tradingagents-web" in recipe
    command = next(line.removeprefix("CMD ") for line in recipe.splitlines() if line.startswith("CMD "))
    assert json.loads(command) == [
        "uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"
    ]


def test_compose_sets_revision_label_from_required_sha() -> None:
    service = load_yaml(COMPOSE)["services"]["web"]

    assert service["labels"] == {
        "org.opencontainers.image.revision": "${TRADINGAGENTS_WEB_REVISION:?required}"
    }


FAKE_COMMAND = r'''#!/usr/bin/python3
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

name = Path(sys.argv[0]).name
args = sys.argv[1:]
env = os.environ
log_path = Path(env["FAKE_COMMAND_LOG"])
previous_records = []
if log_path.exists():
    previous_records = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
record = {
    "command": [name, *args],
    "allowed": False,
    "image": env.get("TRADINGAGENTS_WEB_IMAGE", ""),
    "revision": env.get("TRADINGAGENTS_WEB_REVISION", ""),
    "resolved_image_id": "",
}
stdout = ""
exit_code = 0


def allow() -> None:
    record["allowed"] = True


if name == "docker":
    publish_format = '{{.ID}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.service"}}'
    project_filters = [
        "--filter", "label=com.docker.compose.project=trading-agents-web",
        "--filter", "label=com.docker.compose.service=web",
    ]
    if args == ["ps", "--filter", "publish=7681", "--format", publish_format]:
        allow()
        owner = env.get("FAKE_PORT_OWNER", "none")
        if owner == "project":
            stdout = "existing-container|trading-agents-web|web\n"
        elif owner == "foreign":
            stdout = "foreign-container|another-project|web\n"
        elif owner not in {"none", "process"}:
            exit_code = 96
    elif args == ["ps", "--all", *project_filters, "--format", "{{.ID}}"]:
        allow()
        if env.get("FAKE_EXISTING_IMAGE"):
            stdout = "existing-container\n"
    elif args == ["inspect", "--format", "{{.Config.Image}}", "existing-container"]:
        allow()
        stdout = env.get("FAKE_EXISTING_IMAGE", "") + "\n"
    elif args == ["inspect", "--format", "{{.Image}}", "existing-container"]:
        allow()
        stdout = env.get("FAKE_EXISTING_IMAGE_ID", "") + "\n"
    elif args == [
        "build", "--label", f'org.opencontainers.image.revision={env["FAKE_SHA"]}',
        "--tag", f'trading-agents-web-ui:{env["FAKE_SHA"]}',
        "--file", "web/Dockerfile", ".",
    ]:
        allow()
    elif len(args) == 5 and args[:3] == ["image", "inspect", "--format"]:
        revision_format = '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
        id_format = "{{.Id}}"
        image = args[4]
        new_image = f'trading-agents-web-ui:{env["FAKE_SHA"]}'
        built_new_image = any(
            previous["command"][:2] == ["docker", "build"]
            for previous in previous_records
        )
        if args[3] == revision_format and image == new_image:
            allow()
            stdout = env["FAKE_SHA"] + "\n"
        elif args[3] == revision_format and image in {
            env.get("FAKE_EXISTING_IMAGE"),
            env.get("FAKE_EXISTING_IMAGE_ID"),
        }:
            allow()
            stdout = env.get("FAKE_OLD_REVISION", "") + "\n"
        elif args[3] == id_format and image == new_image:
            allow()
            if built_new_image:
                stdout = "sha256:new-build-image\n"
            elif env.get("FAKE_EXISTING_IMAGE") == new_image:
                stdout = env.get("FAKE_EXISTING_IMAGE_ID", "") + "\n"
            elif env.get("FAKE_EXISTING_SHA_IMAGE_ID"):
                stdout = env["FAKE_EXISTING_SHA_IMAGE_ID"] + "\n"
            else:
                exit_code = 1
    elif len(args) == 17 and args[:4] == ["run", "--detach", "--rm", "--name"]:
        candidate = args[4]
        expected = [
            "run", "--detach", "--rm", "--name", candidate,
            "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--volume", "/var/lib/tradingagents-web",
            "--publish", "127.0.0.1::8080",
            f'trading-agents-web-ui:{env["FAKE_SHA"]}',
        ]
        if args == expected and candidate.startswith(
            f'trading-agents-web-candidate-{env["FAKE_SHA"]}-'
        ):
            allow()
            stdout = "candidate-container\n"
    elif len(args) == 3 and args[0] == "port" and args[2] == "8080/tcp":
        candidate = args[1]
        if candidate.startswith(f'trading-agents-web-candidate-{env["FAKE_SHA"]}-'):
            allow()
            stdout = "127.0.0.1:49152\n"
    elif len(args) == 3 and args[0] == "cp":
        container, source = args[1].split(":", 1)
        destination = Path(args[2])
        candidate = container.startswith(f'trading-agents-web-candidate-{env["FAKE_SHA"]}-')
        if (candidate or container == "existing-container") and source in {
            "/app/web/client/dist/index.html", "/app/index.html"
        } and destination.resolve().is_relative_to(Path(env["TMPDIR"]).resolve()):
            allow()
            if not candidate and env.get("FAKE_OLD_LEGACY") == "true" and source != "/app/index.html":
                exit_code = 1
            else:
                destination.write_bytes(Path(env["FAKE_INDEX"] if candidate else env["FAKE_OLD_INDEX"]).read_bytes())
    elif len(args) == 4 and args[:3] == ["rm", "--force", "--volumes"]:
        candidate = args[3]
        if candidate.startswith(f'trading-agents-web-candidate-{env["FAKE_SHA"]}-'):
            allow()
            stdout = candidate + "\n"
    elif args == [
        "inspect", "--format",
        "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}",
        "live-web",
    ]:
        allow()
        stdout = "healthy\n"
elif name == "docker-compose":
    prefix = [
        "--project-name", "trading-agents-web",
        "--file", "docker-compose.gateway-web.yml",
    ]
    action = args[len(prefix):] if args[:len(prefix)] == prefix else []
    image = env.get("TRADINGAGENTS_WEB_IMAGE", "")
    revision = env.get("TRADINGAGENTS_WEB_REVISION", "")
    new_image = f'trading-agents-web-ui:{env["FAKE_SHA"]}'
    valid_release = (image == new_image and revision == env["FAKE_SHA"])
    valid_rollback = (
        bool(env.get("FAKE_EXISTING_IMAGE"))
        and image == env.get("FAKE_EXISTING_IMAGE")
        and revision == env.get("FAKE_OLD_REVISION")
    )
    if action == ["up", "--detach", "--no-build", "web"] and (
        valid_release or valid_rollback
    ):
        allow()
        built_new_image = any(
            previous["command"][:2] == ["docker", "build"]
            for previous in previous_records
        )
        if image == new_image and built_new_image:
            record["resolved_image_id"] = "sha256:new-build-image"
        elif image == env.get("FAKE_EXISTING_IMAGE"):
            record["resolved_image_id"] = env.get("FAKE_EXISTING_IMAGE_ID", "")
        else:
            record["resolved_image_id"] = env.get("FAKE_EXISTING_SHA_IMAGE_ID", "")
    elif action == ["ps", "--quiet", "web"] and (valid_release or valid_rollback):
        allow()
        stdout = "live-web\n"
    elif action == ["stop", "web"] and valid_release:
        allow()
elif name == "curl":
    curl_prefix = [
        "--fail", "--silent", "--show-error",
        "--connect-timeout", "2", "--max-time", "5", "--output",
    ]
    if len(args) == 10 and args[:8] == curl_prefix:
        output = Path(args[8])
        url = args[9]
        allowed_urls = {
            "http://127.0.0.1:49152/healthz",
            "http://127.0.0.1:49152/",
            "http://127.0.0.1:7681/healthz",
            "http://127.0.0.1:7681/",
        }
        if url in allowed_urls and output.resolve().is_relative_to(
            Path(env["TMPDIR"]).resolve()
        ):
            allow()
            candidate = ":49152" in url
            health = url.endswith("/healthz")
            new_release = env.get("TRADINGAGENTS_WEB_IMAGE") == (
                f'trading-agents-web-ui:{env["FAKE_SHA"]}'
            )
            previous_candidate_health_calls = sum(
                previous["command"][0] == "curl"
                and previous["command"][-1] == "http://127.0.0.1:49152/healthz"
                for previous in previous_records
            )
            previous_live_health_calls = sum(
                previous["command"][0] == "curl"
                and previous["command"][-1] == "http://127.0.0.1:7681/healthz"
                for previous in previous_records
            )
            candidate_health = env.get("FAKE_CANDIDATE_HEALTH")
            if candidate and health and candidate_health == "fail":
                exit_code = 7
            elif (
                candidate
                and health
                and candidate_health == "fail-once"
                and previous_candidate_health_calls == 0
            ):
                exit_code = 7
            elif not candidate and health and new_release and env.get("FAKE_LIVE_HEALTH") == "timeout":
                exit_code = 28
            elif (
                not candidate
                and health
                and new_release
                and env.get("FAKE_LIVE_HEALTH") == "fail-once"
                and previous_live_health_calls == 0
            ):
                exit_code = 22
            elif not candidate and health and new_release and env.get("FAKE_LIVE_HEALTH") == "fail":
                exit_code = 22
            elif health:
                output.write_bytes(b"ok\n")
            elif candidate and env.get("FAKE_CANDIDATE_PAGE", "ok") != "ok":
                output.write_bytes(b"wrong candidate page\n")
            elif not candidate and new_release and env.get("FAKE_LIVE_PAGE", "ok") != "ok":
                output.write_bytes(b"wrong live page\n")
            else:
                output.write_bytes(Path(env["FAKE_INDEX"] if candidate or new_release else env["FAKE_OLD_INDEX"]).read_bytes())
elif name == "ss":
    if args == ["-H", "-ltn", "sport = :7681"]:
        allow()
        if env.get("FAKE_PORT_OWNER") in {"project", "foreign", "process"}:
            stdout = "LISTEN 0 4096 127.0.0.1:7681 0.0.0.0:*\n"
elif name == "mktemp":
    if args == ["-d"]:
        allow()
        stdout = tempfile.mkdtemp(prefix="deploy-test-", dir=env["TMPDIR"]) + "\n"
elif name == "cmp":
    if len(args) == 3 and args[0] == "-s":
        first = Path(args[1]).resolve()
        second = Path(args[2]).resolve()
        temp_root = Path(env["TMPDIR"]).resolve()
        if first.is_relative_to(temp_root) and (
            second.is_relative_to(temp_root) or second == Path(env["FAKE_INDEX"]).resolve()
        ):
            allow()
            exit_code = 0 if first.read_bytes() == second.read_bytes() else 1
elif name == "rm":
    if len(args) == 3 and args[:2] == ["-rf", "--"]:
        target = Path(args[2]).resolve()
        if target.is_relative_to(Path(env["TMPDIR"]).resolve()):
            allow()
            shutil.rmtree(target, ignore_errors=True)
elif name == "sleep":
    if args == ["1"]:
        allow()

with log_path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\n")

if not record["allowed"]:
    print("fake command rejected: " + " ".join(record["command"]), file=sys.stderr)
    raise SystemExit(97)
sys.stdout.write(stdout)
raise SystemExit(exit_code)
'''


@dataclass
class FakeCommands:
    bin_dir: Path
    log_path: Path
    temp_dir: Path

    def calls(self) -> list[dict[str, object]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def run(self, sha: str = SHA, **overrides: str) -> subprocess.CompletedProcess[str]:
        built_index = self.temp_dir / "built-index.html"
        built_index.write_text('<html><script src="/assets/index-built123.js"></script></html>')
        environment = {
            "PATH": str(self.bin_dir),
            "TMPDIR": str(self.temp_dir),
            "FAKE_COMMAND_LOG": str(self.log_path),
            "FAKE_INDEX": str(built_index),
            "FAKE_OLD_INDEX": str(INDEX),
            "FAKE_SHA": SHA,
            "FAKE_EXISTING_IMAGE": "",
            "FAKE_EXISTING_IMAGE_ID": "sha256:old-image",
            "FAKE_EXISTING_SHA_IMAGE_ID": "",
            "FAKE_OLD_REVISION": OLD_SHA,
            "FAKE_PORT_OWNER": "none",
            "FAKE_CANDIDATE_HEALTH": "ok",
            "FAKE_CANDIDATE_PAGE": "ok",
            "FAKE_LIVE_HEALTH": "ok",
            "FAKE_LIVE_PAGE": "ok",
        }
        environment.update(overrides)
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT), sha],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        rejected = [call["command"] for call in self.calls() if not call["allowed"]]
        assert not rejected, f"deployment used commands outside its contract: {rejected}"
        return result


@pytest.fixture()
def fake_commands(tmp_path: Path) -> FakeCommands:
    bin_dir = tmp_path / "bin"
    temp_dir = tmp_path / "tmp"
    bin_dir.mkdir()
    temp_dir.mkdir()
    for command in ("docker", "docker-compose", "curl", "ss", "mktemp", "cmp", "rm", "sleep"):
        path = bin_dir / command
        path.write_text(FAKE_COMMAND, encoding="utf-8")
        path.chmod(0o755)
    return FakeCommands(bin_dir, tmp_path / "calls.jsonl", temp_dir)


def commands(calls: list[dict[str, object]]) -> list[list[str]]:
    return [call["command"] for call in calls]  # type: ignore[misc]


def test_deploy_from_push_needs_no_manual_attestations(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(MANUAL_RELEASE_SHA="", PRIVATE_INGRESS_VERIFIED_SHA="")
    assert result.returncode == 0, result.stderr
    invoked = commands(fake_commands.calls())
    assert any(call[:2] == ["docker", "build"] for call in invoked)
    assert any(call[0] == "docker-compose" and "up" in call for call in invoked)


def test_candidate_is_verified_before_cutover(fake_commands: FakeCommands) -> None:
    result = fake_commands.run()

    assert result.returncode == 0, result.stderr
    calls = fake_commands.calls()
    invoked = commands(calls)
    build = [
        "docker", "build", "--label", f"org.opencontainers.image.revision={SHA}",
        "--tag", f"trading-agents-web-ui:{SHA}", "--file", "web/Dockerfile", ".",
    ]
    candidate_run = next(call for call in invoked if call[:2] == ["docker", "run"])
    candidate_health = next(
        call for call in invoked if call[0] == "curl" and call[-1].endswith(":49152/healthz")
    )
    candidate_page = next(
        call for call in invoked if call[0] == "curl" and call[-1] == "http://127.0.0.1:49152/"
    )
    candidate_remove = next(call for call in invoked if call[:3] == ["docker", "rm", "--force"])
    compose_up = next(
        call for call in invoked if call[0] == "docker-compose" and "up" in call
    )
    assert invoked.index(build) < invoked.index(candidate_run)
    assert invoked.index(candidate_run) < invoked.index(candidate_health)
    assert invoked.index(candidate_health) < invoked.index(candidate_page)
    assert invoked.index(candidate_page) < invoked.index(candidate_remove)
    assert invoked.index(candidate_remove) < invoked.index(compose_up)
    assert [call[-1] for call in invoked if call[0] == "curl"] == [
        "http://127.0.0.1:49152/healthz",
        "http://127.0.0.1:49152/",
        "http://127.0.0.1:7681/healthz",
        "http://127.0.0.1:7681/",
    ]
    first_up = next(call for call in calls if call["command"] == compose_up)
    assert first_up["image"] == f"trading-agents-web-ui:{SHA}"
    assert first_up["revision"] == SHA
    assert sum(call == compose_up for call in invoked) == 1
    assert not any(call[-2:] == ["stop", "web"] for call in invoked)


def test_candidate_failure_never_calls_cutover(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(FAKE_CANDIDATE_HEALTH="fail")

    assert result.returncode == 7
    invoked = commands(fake_commands.calls())
    assert sum(
        call[0] == "curl" and call[-1] == "http://127.0.0.1:49152/healthz"
        for call in invoked
    ) == 30
    assert sum(call == ["sleep", "1"] for call in invoked) == 29
    assert any(call[:3] == ["docker", "rm", "--force"] for call in invoked)
    assert not any(call[0] == "docker-compose" for call in invoked)


def test_candidate_readiness_retries_transient_connection_failure(
    fake_commands: FakeCommands,
) -> None:
    result = fake_commands.run(FAKE_CANDIDATE_HEALTH="fail-once")

    assert result.returncode == 0, result.stderr
    invoked = commands(fake_commands.calls())
    assert sum(
        call[0] == "curl" and call[-1] == "http://127.0.0.1:49152/healthz"
        for call in invoked
    ) == 2
    assert sum(call == ["sleep", "1"] for call in invoked) == 1
    assert sum(call[0] == "docker-compose" and "up" in call for call in invoked) == 1


def test_candidate_page_must_match_built_image_bytes(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(FAKE_CANDIDATE_PAGE="wrong")

    assert result.returncode == 1
    invoked = commands(fake_commands.calls())
    assert any(call[:3] == ["docker", "rm", "--force"] for call in invoked)
    assert not any(call[0] == "docker-compose" for call in invoked)


def test_port_conflict_fails_before_build(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(FAKE_PORT_OWNER="foreign")

    assert result.returncode == 1
    assert "foreign-container" in result.stderr
    invoked = commands(fake_commands.calls())
    assert invoked == [
        [
            "docker",
            "ps",
            "--filter",
            "publish=7681",
            "--format",
            '{{.ID}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.service"}}',
        ]
    ]


def test_non_container_port_conflict_fails_before_build(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(FAKE_PORT_OWNER="process")

    assert result.returncode == 1
    assert "non-project process" in result.stderr
    invoked = commands(fake_commands.calls())
    assert invoked[-1] == ["ss", "-H", "-ltn", "sport = :7681"]
    assert not any(call[:2] == ["docker", "build"] for call in invoked)
    assert not any(call[0] == "docker-compose" for call in invoked)


@pytest.mark.parametrize("legacy", ["true", "false"])
def test_post_cutover_failure_restores_previous_image(
    fake_commands: FakeCommands, legacy: str
) -> None:
    result = fake_commands.run(
        FAKE_EXISTING_IMAGE=OLD_IMAGE,
        FAKE_PORT_OWNER="project",
        FAKE_LIVE_HEALTH="fail",
        FAKE_OLD_LEGACY=legacy,
    )

    assert result.returncode == 22
    calls = fake_commands.calls()
    ups = [call for call in calls if call["command"][0] == "docker-compose" and "up" in call["command"]]
    assert [(call["image"], call["revision"]) for call in ups] == [
        (f"trading-agents-web-ui:{SHA}", SHA),
        (OLD_IMAGE, OLD_SHA),
    ]
    assert any(
        call["command"][-1] == "http://127.0.0.1:7681/healthz"
        and call["image"] == OLD_IMAGE
        for call in calls
    )
    assert not any(call["command"][-2:] == ["stop", "web"] for call in calls)
    assert "previous Compose web image did not recover" not in result.stderr


def test_failed_first_deployment_stops_service(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(FAKE_LIVE_HEALTH="fail")

    assert result.returncode == 22
    calls = fake_commands.calls()
    ups = [call for call in calls if call["command"][0] == "docker-compose" and "up" in call["command"]]
    assert [(call["image"], call["revision"]) for call in ups] == [
        (f"trading-agents-web-ui:{SHA}", SHA)
    ]
    assert any(call["command"][-2:] == ["stop", "web"] for call in calls)
    assert all(call["image"] != OLD_IMAGE for call in calls)


def test_live_timeout_restores_previous_image(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(
        FAKE_EXISTING_IMAGE=OLD_IMAGE,
        FAKE_PORT_OWNER="project",
        FAKE_LIVE_HEALTH="timeout",
    )

    assert result.returncode == 28
    calls = fake_commands.calls()
    ups = [
        call
        for call in calls
        if call["command"][0] == "docker-compose" and "up" in call["command"]
    ]
    assert [(call["image"], call["revision"]) for call in ups] == [
        (f"trading-agents-web-ui:{SHA}", SHA),
        (OLD_IMAGE, OLD_SHA),
    ]
    assert not any(call["command"][-2:] == ["stop", "web"] for call in calls)


def test_live_timeout_on_first_deployment_stops_service(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(FAKE_LIVE_HEALTH="timeout")

    assert result.returncode == 28
    calls = fake_commands.calls()
    assert sum(
        call["command"][0] == "docker-compose" and "up" in call["command"]
        for call in calls
    ) == 1
    assert sum(call["command"][-2:] == ["stop", "web"] for call in calls) == 1


def test_live_page_mismatch_restores_previous_image(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(
        FAKE_EXISTING_IMAGE=OLD_IMAGE,
        FAKE_PORT_OWNER="project",
        FAKE_LIVE_PAGE="wrong",
    )

    assert result.returncode == 1
    calls = fake_commands.calls()
    ups = [
        call
        for call in calls
        if call["command"][0] == "docker-compose" and "up" in call["command"]
    ]
    assert [(call["image"], call["revision"]) for call in ups] == [
        (f"trading-agents-web-ui:{SHA}", SHA),
        (OLD_IMAGE, OLD_SHA),
    ]
    assert not any(call["command"][-2:] == ["stop", "web"] for call in calls)


def test_same_sha_reuses_running_image_without_overwriting_rollback_target(
    fake_commands: FakeCommands,
) -> None:
    image = f"trading-agents-web-ui:{SHA}"
    result = fake_commands.run(
        FAKE_EXISTING_IMAGE=image,
        FAKE_EXISTING_IMAGE_ID="sha256:running-old-image",
        FAKE_OLD_REVISION=SHA,
        FAKE_PORT_OWNER="project",
        FAKE_LIVE_HEALTH="fail-once",
    )

    assert result.returncode == 22
    calls = fake_commands.calls()
    assert not any(call["command"][:2] == ["docker", "build"] for call in calls)
    ups = [
        call
        for call in calls
        if call["command"][0] == "docker-compose" and "up" in call["command"]
    ]
    assert [(call["image"], call["revision"]) for call in ups] == [
        (image, SHA),
        (image, SHA),
    ]
    assert [call["resolved_image_id"] for call in ups] == [
        "sha256:running-old-image",
        "sha256:running-old-image",
    ]
    assert sum(
        call["command"][-1] == "http://127.0.0.1:7681/healthz" for call in calls
    ) == 2
    assert any(call["command"][-1] == "http://127.0.0.1:7681/" for call in calls)


@pytest.mark.parametrize("invalid_sha", ["abc", "A" * 40])
def test_rejects_short_or_uppercase_sha_before_docker(
    fake_commands: FakeCommands, invalid_sha: str
) -> None:
    result = fake_commands.run(invalid_sha)

    assert result.returncode != 0
    assert "40 lowercase hexadecimal" in result.stderr
    assert fake_commands.calls() == []
