import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/initialize_gitea_main.sh"
BACKUP_TAG = "pre-github-sync-20260920-052251b1"
SOURCE_ONLY_BRANCH = "source-only"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def run(
    *args: str,
    cwd: Path,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        env=env,
        text=True,
        capture_output=True,
    )


def git(cwd: Path, *args: str) -> str:
    return run("git", *args, cwd=cwd).stdout.strip()


def initialize_repository(path: Path) -> None:
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Infra Test")
    git(path, "config", "user.email", "infra-test@example.invalid")


def commit_file(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    git(repo, "add", filename)
    git(repo, "commit", "-m", message)
    sha = git(repo, "rev-parse", "HEAD")
    assert SHA_RE.fullmatch(sha)
    return sha


def remote_refs(target: Path) -> dict[str, str]:
    output = git(
        target.parent,
        "--git-dir",
        str(target),
        "for-each-ref",
        "--format=%(refname) %(objectname)",
    )
    return dict(line.split() for line in output.splitlines())


def remote_sha(source: Path, target: Path, ref: str) -> str:
    return git(source, "--git-dir", str(target), "rev-parse", ref)


@dataclass(frozen=True)
class InitializationFixture:
    source: Path
    target: Path
    old_worktree: Path
    new_sha: str
    old_sha: str


def make_initialization_fixture(tmp_path: Path) -> InitializationFixture:
    source = tmp_path / "source"
    initialize_repository(source)
    new_sha = commit_file(source, "payload.txt", "github\n", "GitHub main")
    git(source, "branch", SOURCE_ONLY_BRANCH, new_sha)

    old_worktree = tmp_path / "old-worktree"
    initialize_repository(old_worktree)
    old_sha = commit_file(old_worktree, "README.md", "", "Gitea placeholder")
    git(old_worktree, "branch", "preserved-branch", old_sha)
    git(old_worktree, "tag", "-a", "preserved-tag", old_sha, "-m", "Preserved tag")

    target = tmp_path / "target.git"
    run("git", "init", "--bare", "--initial-branch=main", str(target), cwd=tmp_path)
    remote = target.resolve().as_uri()
    git(old_worktree, "push", remote, "main", "preserved-branch", "preserved-tag")
    return InitializationFixture(source, target, old_worktree, new_sha, old_sha)


def make_root_commit(tmp_path: Path, name: str, files: dict[str, str]) -> tuple[Path, str]:
    repo = tmp_path / name
    initialize_repository(repo)
    for filename, content in files.items():
        (repo / filename).write_text(content, encoding="utf-8")
    git(repo, "add", *files)
    git(repo, "commit", "-m", name)
    sha = git(repo, "rev-parse", "HEAD")
    assert SHA_RE.fullmatch(sha)
    return repo, sha


def run_initializer(
    fixture: InitializationFixture,
    *,
    expected_old_sha: str | None = None,
    check: bool = False,
    extra_args: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    old_sha = fixture.old_sha if expected_old_sha is None else expected_old_sha
    return run(
        "bash",
        str(SCRIPT),
        fixture.target.resolve().as_uri(),
        fixture.new_sha,
        *extra_args,
        cwd=fixture.source,
        check=check,
        env={**os.environ, "GITEA_INITIALIZE_TEST_OLD_SHA": old_sha},
    )


def install_git_call_detector(tmp_path: Path) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "git-called"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\ntouch \"$GIT_CALLED_MARKER\"\nexit 99\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GIT_CALLED_MARKER": str(marker),
    }
    return env, marker


def assert_only_initialization_refs_changed(
    before: dict[str, str],
    after: dict[str, str],
) -> None:
    allowed = {"refs/heads/main", f"refs/tags/{BACKUP_TAG}"}
    assert {ref: sha for ref, sha in after.items() if ref not in allowed} == {
        ref: sha for ref, sha in before.items() if ref not in allowed
    }
    assert set(after) - set(before) <= {f"refs/tags/{BACKUP_TAG}"}


def test_initialization_backs_up_old_root_and_replaces_main(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    before = remote_refs(fixture.target)

    result = run(
        "bash",
        str(SCRIPT),
        fixture.target.resolve().as_uri(),
        fixture.new_sha,
        cwd=fixture.source,
        env={**os.environ, "GITEA_INITIALIZE_TEST_OLD_SHA": fixture.old_sha},
    )

    assert "initialized" in result.stdout
    after = remote_refs(fixture.target)
    assert after["refs/heads/main"] == fixture.new_sha
    assert remote_sha(
        fixture.source, fixture.target, f"refs/tags/{BACKUP_TAG}^{{}}"
    ) == fixture.old_sha
    assert f"refs/heads/{SOURCE_ONLY_BRANCH}" not in after
    assert_only_initialization_refs_changed(before, after)
    assert set(after) == {*before, f"refs/tags/{BACKUP_TAG}"}


def test_rejects_changed_old_main_without_creating_tag(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    changed_repo, changed_sha = make_root_commit(
        tmp_path, "changed-main", {"README.md": ""}
    )
    git(
        changed_repo,
        "push",
        "--force",
        fixture.target.resolve().as_uri(),
        f"{changed_sha}:refs/heads/main",
    )
    before = remote_refs(fixture.target)

    result = run_initializer(fixture)

    assert result.returncode != 0
    assert remote_refs(fixture.target) == before
    assert f"refs/tags/{BACKUP_TAG}" not in before


def test_rejects_old_commit_with_parent(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    git(fixture.old_worktree, "commit", "--allow-empty", "-m", "Placeholder with a parent")
    child_sha = git(fixture.old_worktree, "rev-parse", "HEAD")
    git(
        fixture.old_worktree,
        "push",
        fixture.target.resolve().as_uri(),
        f"{child_sha}:refs/heads/main",
    )
    before = remote_refs(fixture.target)

    result = run_initializer(fixture, expected_old_sha=child_sha)

    assert result.returncode != 0
    assert remote_refs(fixture.target) == before


def test_rejects_old_tree_with_extra_file(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    old_repo, malformed_sha = make_root_commit(
        tmp_path,
        "extra-file",
        {"README.md": "", "extra.txt": "unexpected\n"},
    )
    git(
        old_repo,
        "push",
        "--force",
        fixture.target.resolve().as_uri(),
        f"{malformed_sha}:refs/heads/main",
    )
    before = remote_refs(fixture.target)

    result = run_initializer(fixture, expected_old_sha=malformed_sha)

    assert result.returncode != 0
    assert remote_refs(fixture.target) == before


def test_rejects_nonempty_readme(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    old_repo, malformed_sha = make_root_commit(
        tmp_path, "nonempty-readme", {"README.md": "not empty\n"}
    )
    git(
        old_repo,
        "push",
        "--force",
        fixture.target.resolve().as_uri(),
        f"{malformed_sha}:refs/heads/main",
    )
    before = remote_refs(fixture.target)

    result = run_initializer(fixture, expected_old_sha=malformed_sha)

    assert result.returncode != 0
    assert remote_refs(fixture.target) == before


def test_rejects_readme_containing_only_newline(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    old_repo, malformed_sha = make_root_commit(
        tmp_path, "newline-readme", {"README.md": "\n"}
    )
    git(
        old_repo,
        "push",
        "--force",
        fixture.target.resolve().as_uri(),
        f"{malformed_sha}:refs/heads/main",
    )
    before = remote_refs(fixture.target)

    result = run_initializer(fixture, expected_old_sha=malformed_sha)

    assert result.returncode != 0
    assert remote_refs(fixture.target) == before


def test_rejects_arbitrary_expected_old_sha_argument(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    before = remote_refs(fixture.target)

    result = run_initializer(fixture, extra_args=(fixture.old_sha,))

    assert result.returncode != 0
    assert "usage:" in result.stderr
    assert remote_refs(fixture.target) == before


def test_rejects_test_old_sha_override_for_https(tmp_path: Path) -> None:
    env, marker = install_git_call_detector(tmp_path)
    env.update(
        {
            "GITEA_INITIALIZE_TEST_OLD_SHA": "b" * 40,
            "GITEA_MIRROR_SYNC_TOKEN": "test-token",
        }
    )

    result = run(
        "bash",
        str(SCRIPT),
        "https://gitea.example.invalid/owner/repo.git",
        "a" * 40,
        cwd=tmp_path,
        check=False,
        env=env,
    )

    assert result.returncode == 7
    assert "test old SHA override is forbidden for HTTPS" in result.stderr
    assert not marker.exists()


def test_reuses_existing_backup_tag_only_when_it_peels_to_old_sha(
    tmp_path: Path,
) -> None:
    fixture = make_initialization_fixture(tmp_path)
    git(
        fixture.old_worktree,
        "tag",
        "-a",
        BACKUP_TAG,
        fixture.old_sha,
        "-m",
        "Existing backup",
    )
    git(
        fixture.old_worktree,
        "push",
        fixture.target.resolve().as_uri(),
        f"refs/tags/{BACKUP_TAG}",
    )
    before = remote_refs(fixture.target)
    backup_object = before[f"refs/tags/{BACKUP_TAG}"]

    result = run_initializer(fixture, check=True)

    assert "initialized" in result.stdout
    after = remote_refs(fixture.target)
    assert after["refs/heads/main"] == fixture.new_sha
    assert after[f"refs/tags/{BACKUP_TAG}"] == backup_object
    assert f"refs/heads/{SOURCE_ONLY_BRANCH}" not in after
    assert_only_initialization_refs_changed(before, after)
    assert set(after) == set(before)


def test_rejects_conflicting_existing_backup_tag(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    conflicting_sha = commit_file(
        fixture.old_worktree,
        "conflict.txt",
        "conflict\n",
        "Conflicting backup target",
    )
    git(
        fixture.old_worktree,
        "tag",
        "-a",
        BACKUP_TAG,
        conflicting_sha,
        "-m",
        "Conflicting backup",
    )
    git(
        fixture.old_worktree,
        "push",
        fixture.target.resolve().as_uri(),
        f"refs/tags/{BACKUP_TAG}",
    )
    before = remote_refs(fixture.target)

    result = run_initializer(fixture)

    assert result.returncode != 0
    assert remote_refs(fixture.target) == before


def test_exact_lease_rejects_main_race_after_backup_tag(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    race_sha = commit_file(
        fixture.old_worktree,
        "race.txt",
        "race\n",
        "Concurrent Gitea update",
    )
    git(
        fixture.old_worktree,
        "push",
        fixture.target.resolve().as_uri(),
        f"{race_sha}:refs/heads/race-seed",
    )
    hook = fixture.target / "hooks" / "update"
    hook.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = \"refs/tags/{BACKUP_TAG}\" ]; then\n"
        f"  git --git-dir=\"{fixture.target}\" update-ref refs/heads/main "
        f"{race_sha} {fixture.old_sha}\n"
        "fi\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    before = remote_refs(fixture.target)

    result = run_initializer(fixture)

    assert result.returncode != 0
    after = remote_refs(fixture.target)
    assert after["refs/heads/main"] == race_sha
    assert remote_sha(
        fixture.source, fixture.target, f"refs/tags/{BACKUP_TAG}^{{}}"
    ) == fixture.old_sha
    assert f"refs/heads/{SOURCE_ONLY_BRANCH}" not in after
    assert_only_initialization_refs_changed(before, after)
    assert set(after) == {*before, f"refs/tags/{BACKUP_TAG}"}


def test_https_requires_sync_token_before_git(tmp_path: Path) -> None:
    env, marker = install_git_call_detector(tmp_path)
    env.pop("GITEA_MIRROR_SYNC_TOKEN", None)
    env.pop("GITEA_INITIALIZE_TEST_OLD_SHA", None)

    result = run(
        "bash",
        str(SCRIPT),
        "https://gitea.example.invalid/owner/repo.git",
        "a" * 40,
        cwd=tmp_path,
        check=False,
        env=env,
    )

    assert result.returncode == 4
    assert "GITEA_MIRROR_SYNC_TOKEN is required" in result.stderr
    assert not marker.exists()


def test_rejects_short_expected_new_sha_without_remote_changes(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    before = remote_refs(fixture.target)

    result = run(
        "bash",
        str(SCRIPT),
        fixture.target.resolve().as_uri(),
        fixture.new_sha[:12],
        cwd=fixture.source,
        check=False,
    )

    assert result.returncode != 0
    assert "full lowercase commit SHA" in result.stderr
    assert remote_refs(fixture.target) == before


def test_rejects_expected_new_sha_other_than_head(tmp_path: Path) -> None:
    fixture = make_initialization_fixture(tmp_path)
    other_sha = commit_file(fixture.source, "second.txt", "second\n", "Second source commit")
    before = remote_refs(fixture.target)

    result = run_initializer(fixture)

    assert other_sha != fixture.new_sha
    assert result.returncode != 0
    assert "checked out SHA does not match" in result.stderr
    assert remote_refs(fixture.target) == before


def test_rejects_other_remote_scheme_before_git(tmp_path: Path) -> None:
    env, marker = install_git_call_detector(tmp_path)

    result = run(
        "bash",
        str(SCRIPT),
        "ssh://gitea.example.invalid/owner/repo.git",
        "a" * 40,
        cwd=tmp_path,
        check=False,
        env=env,
    )

    assert result.returncode == 5
    assert "REMOTE_URL must use https://" in result.stderr
    assert not marker.exists()
