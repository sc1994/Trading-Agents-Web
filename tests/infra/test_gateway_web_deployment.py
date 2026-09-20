import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.gateway-web.yml"
SCRIPT = ROOT / "scripts/deploy_gateway_web.sh"
INDEX = ROOT / "web/index.html"
SHA = "a" * 40
OLD_SHA = "b" * 40
OLD_IMAGE = f"trading-agents-web-ui:{OLD_SHA}"


def load_yaml(path: Path) -> dict[object, object]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_compose_binds_only_fixed_loopback_port_and_has_no_secrets() -> None:
    service = load_yaml(COMPOSE)["services"]["web"]

    assert service["image"] == "${TRADINGAGENTS_WEB_IMAGE:?required}"
    assert service["ports"] == ["127.0.0.1:7681:8080"]
    assert service["restart"] == "unless-stopped"
    assert service["read_only"] == "true"
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["tmpfs"] == ["/tmp:rw,noexec,nosuid,size=16m"]
    assert "env_file" not in service
    assert "environment" not in service
    assert "volumes" not in service
    assert "/healthz" in " ".join(service["healthcheck"]["test"])


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
record = {
    "command": [name, *args],
    "allowed": False,
    "image": env.get("TRADINGAGENTS_WEB_IMAGE", ""),
    "revision": env.get("TRADINGAGENTS_WEB_REVISION", ""),
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
    elif args == [
        "build", "--label", f'org.opencontainers.image.revision={env["FAKE_SHA"]}',
        "--tag", f'trading-agents-web-ui:{env["FAKE_SHA"]}',
        "--file", "web/Dockerfile", ".",
    ]:
        allow()
    elif len(args) == 5 and args[:3] == ["image", "inspect", "--format"]:
        expected_format = '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
        image = args[4]
        if args[3] == expected_format and image == f'trading-agents-web-ui:{env["FAKE_SHA"]}':
            allow()
            stdout = env["FAKE_SHA"] + "\n"
        elif args[3] == expected_format and image == env.get("FAKE_EXISTING_IMAGE"):
            allow()
            stdout = env.get("FAKE_OLD_REVISION", "") + "\n"
    elif len(args) == 15 and args[:4] == ["run", "--detach", "--rm", "--name"]:
        candidate = args[4]
        expected = [
            "run", "--detach", "--rm", "--name", candidate,
            "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
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
    elif len(args) == 3 and args[:2] == ["rm", "--force"]:
        candidate = args[2]
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
    elif action == ["ps", "--quiet", "web"] and (valid_release or valid_rollback):
        allow()
        stdout = "live-web\n"
    elif action == ["stop", "web"] and valid_release:
        allow()
elif name == "curl":
    if len(args) == 6 and args[:4] == ["--fail", "--silent", "--show-error", "--output"]:
        output = Path(args[4])
        url = args[5]
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
            if candidate and health and env.get("FAKE_CANDIDATE_HEALTH") != "ok":
                exit_code = 22
            elif not candidate and health and new_release and env.get("FAKE_LIVE_HEALTH") != "ok":
                exit_code = 22
            elif health:
                output.write_bytes(b"ok\n")
            elif candidate and env.get("FAKE_CANDIDATE_PAGE", "ok") != "ok":
                output.write_bytes(b"wrong candidate page\n")
            elif not candidate and new_release and env.get("FAKE_LIVE_PAGE", "ok") != "ok":
                output.write_bytes(b"wrong live page\n")
            else:
                output.write_bytes(Path(env["FAKE_INDEX"]).read_bytes())
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
        environment = {
            "PATH": str(self.bin_dir),
            "TMPDIR": str(self.temp_dir),
            "FAKE_COMMAND_LOG": str(self.log_path),
            "FAKE_INDEX": str(INDEX),
            "FAKE_SHA": SHA,
            "FAKE_EXISTING_IMAGE": "",
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

    assert result.returncode == 22
    invoked = commands(fake_commands.calls())
    assert any(call[:3] == ["docker", "rm", "--force"] for call in invoked)
    assert not any(call[0] == "docker-compose" for call in invoked)


def test_candidate_page_must_match_checked_in_bytes(fake_commands: FakeCommands) -> None:
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


def test_post_cutover_failure_restores_previous_image(fake_commands: FakeCommands) -> None:
    result = fake_commands.run(
        FAKE_EXISTING_IMAGE=OLD_IMAGE,
        FAKE_PORT_OWNER="project",
        FAKE_LIVE_HEALTH="fail",
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


@pytest.mark.parametrize("invalid_sha", ["abc", "A" * 40])
def test_rejects_short_or_uppercase_sha_before_docker(
    fake_commands: FakeCommands, invalid_sha: str
) -> None:
    result = fake_commands.run(invalid_sha)

    assert result.returncode != 0
    assert "40 lowercase hexadecimal" in result.stderr
    assert fake_commands.calls() == []
