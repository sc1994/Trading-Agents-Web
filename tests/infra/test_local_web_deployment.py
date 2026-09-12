from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.web.yml"
DEPLOY_SCRIPT = ROOT / "scripts/deploy_local_web.sh"
WORKFLOW = ROOT / ".gitea/workflows/deploy-local-web.yml"
PINNED_ACTION = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def load_yaml(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_web_compose_isolated_from_runtime_secrets() -> None:
    document = load_yaml(COMPOSE)
    service = document["services"]["web"]
    assert service["build"]["context"] == "."
    assert service["build"]["dockerfile"] == "web/Dockerfile"
    assert service["image"] == "trading-agents-web-ui:local"
    assert service["ports"] == ["${TRADINGAGENTS_WEB_PORT:-8080}:8080"]
    assert "env_file" not in service
    assert "/healthz" in " ".join(service["healthcheck"]["test"])


def test_gitea_workflow_only_deploys_protected_main() -> None:
    document = load_yaml(WORKFLOW)
    assert document["on"]["push"]["branches"] == ["main"]
    assert "pull_request" not in document["on"]
    assert "workflow_dispatch" in document["on"]
    assert document["permissions"] == {"contents": "read"}
    assert document["concurrency"] == {
        "group": "trading-agents-web-local-web",
        "cancel-in-progress": "false",
    }

    job = document["jobs"]["deploy"]
    assert "github.server_url == 'https://gitea.suncheng.online:81'" in job["if"]
    assert "github.repository == 'suncheng/Trading-Agents-Web'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert job["runs-on"] == "ubuntu-latest"
    for step in job["steps"]:
        if "uses" in step:
            assert PINNED_ACTION.fullmatch(step["uses"])
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "scripts/deploy_local_web.sh" in runs

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "GITEA_MIRROR_SYNC_TOKEN" not in text
    assert "OPENAI_API_KEY" not in text
    assert "ALPHA_VANTAGE_API_KEY" not in text


def test_deploy_script_rebuilds_and_verifies_the_local_service() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "docker compose" in text
    assert "docker-compose" in text
    assert "docker-compose.web.yml" in text
    assert "--build" in text
    assert "--detach" in text
    assert "/healthz" in text
    assert "curl" in text
