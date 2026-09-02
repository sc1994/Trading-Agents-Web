import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/sync-gitea.yml"
SCRIPT = ROOT / "scripts/sync_gitea_main.sh"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def run(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=check, text=True, capture_output=True)


def git(cwd: Path, *args: str) -> str:
    return run("git", *args, cwd=cwd).stdout.strip()


def commit(repo: Path, message: str, content: str) -> str:
    (repo / "payload.txt").write_text(content, encoding="utf-8")
    git(repo, "add", "payload.txt")
    git(repo, "commit", "-m", message)
    sha = git(repo, "rev-parse", "HEAD")
    assert SHA_RE.fullmatch(sha)
    return sha


def test_workflow_has_read_only_single_branch_contract() -> None:
    document = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert document["on"]["push"]["branches"] == ["main"]
    assert "workflow_dispatch" in document["on"]
    assert document["permissions"] == {"contents": "read"}
    job = document["jobs"]["sync-main"]
    assert "github.server_url == 'https://github.com'" in job["if"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    run_command = job["steps"][1]["run"]
    assert "scripts/sync_gitea_main.sh" in run_command
    assert "https://gitea.suncheng.online:81/suncheng/Trading-Agents-Web.git" in run_command
    assert job["steps"][1]["env"] == {
        "GITEA_MIRROR_SYNC_TOKEN": "${{ secrets.GITEA_MIRROR_SYNC_TOKEN }}"
    }
    script = SCRIPT.read_text(encoding="utf-8")
    assert "HEAD:refs/heads/main" in script
    assert all(flag not in script for flag in ("--force", "--mirror", "--delete"))


def test_script_pushes_main_and_rejects_non_fast_forward(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target.git"
    other = tmp_path / "other"
    source.mkdir()
    git(source, "init", "-b", "main")
    git(source, "config", "user.name", "Infra Test")
    git(source, "config", "user.email", "infra-test@example.invalid")
    first = commit(source, "first", "first")
    run("git", "init", "--bare", str(target), cwd=tmp_path)
    remote = target.resolve().as_uri()

    run("bash", str(SCRIPT), remote, first, cwd=source)
    assert git(source, "ls-remote", remote, "refs/heads/main").split()[0] == first

    run("git", "clone", "--branch", "main", remote, str(other), cwd=tmp_path)
    git(other, "config", "user.name", "Infra Test")
    git(other, "config", "user.email", "infra-test@example.invalid")
    divergent = commit(other, "target divergence", "target")
    git(other, "push", "origin", "HEAD:main")

    second = commit(source, "source divergence", "source")
    result = run("bash", str(SCRIPT), remote, second, cwd=source, check=False)
    assert result.returncode != 0
    assert git(source, "ls-remote", remote, "refs/heads/main").split()[0] == divergent


def test_https_mode_fails_before_git_when_token_is_missing(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("GITEA_MIRROR_SYNC_TOKEN", None)
    result = subprocess.run(
        ["bash", str(SCRIPT), "https://gitea.example.invalid/owner/repo.git", "a" * 40],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "GITEA_MIRROR_SYNC_TOKEN is required" in result.stderr
