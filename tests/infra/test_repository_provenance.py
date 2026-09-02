import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSER = ROOT / "scripts/compose_import_readme.py"
BASE_COMMIT = "76fc9e407842970e8e6fdfdf32a2f9b7ef86be13"
BASE_README_BLOB = "f28ff51c7392b770bbd7ac16024c7fb4d8b67dc2"
UPSTREAM_COMMIT = "2448d0a12576f9b2ddcd5980a0630833423d1e1b"
UPSTREAM_README_BLOB = "505b69df46ce78e6bb0b22088a5b9c380cbc7a39"
TAG_OBJECT = "c5e62b8bb88bc308e84ea351044356f99da1213e"
LICENSE_SHA256 = "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        text=True,
        capture_output=True,
    )


def git_bytes(*args: str, cwd: Path = ROOT) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True
    ).stdout


def fixture_git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=check, text=True, capture_output=True
    )


def fixture_commit(repo: Path, message: str) -> str:
    fixture_git(repo, "add", "README.md")
    fixture_git(repo, "commit", "-m", message)
    return fixture_git(repo, "rev-parse", "HEAD").stdout.strip()


def test_upstream_commit_is_the_imported_parent_or_an_ancestor() -> None:
    merge_head = git("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False)
    if merge_head.returncode == 0:
        assert merge_head.stdout.strip() == UPSTREAM_COMMIT
    else:
        result = git("merge-base", "--is-ancestor", UPSTREAM_COMMIT, "HEAD", check=False)
        assert result.returncode == 0


def test_upstream_license_is_preserved_byte_for_byte() -> None:
    current = (ROOT / "LICENSE").read_bytes()
    original = git_bytes("show", f"{UPSTREAM_COMMIT}:LICENSE")
    assert current == original
    assert hashlib.sha256(current).hexdigest() == LICENSE_SHA256


def test_source_record_contains_reproducible_identity() -> None:
    source = (ROOT / "UPSTREAM.md").read_text(encoding="utf-8")
    assert "https://github.com/TauricResearch/TradingAgents.git" in source
    assert "v0.4.0" in source
    assert TAG_OBJECT in source
    assert UPSTREAM_COMMIT in source
    assert "manual review" in source.lower()


def test_both_readmes_are_preserved_around_lineage() -> None:
    assert git("rev-parse", f"{BASE_COMMIT}:README.md").stdout.strip() == BASE_README_BLOB
    assert (
        git("rev-parse", f"{UPSTREAM_COMMIT}:README.md").stdout.strip()
        == UPSTREAM_README_BLOB
    )
    user_readme = git_bytes("show", f"{BASE_COMMIT}:README.md")
    upstream_readme = git_bytes("show", f"{UPSTREAM_COMMIT}:README.md")
    current = (ROOT / "README.md").read_bytes()
    assert current.startswith(user_readme + b"\n## Repository lineage\n")
    assert current.endswith(upstream_readme)
    assert b"<<<<<<<" not in current
    assert b"=======" not in current
    assert b">>>>>>>" not in current
    assert git("ls-files", "-u", "--", "README.md").stdout == ""


def test_composer_resolves_independent_root_readmes_without_data_loss(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "fixture"
    repo.mkdir()
    fixture_git(repo, "init", "-b", "main")
    fixture_git(repo, "config", "user.name", "README Merge Test")
    fixture_git(repo, "config", "user.email", "readme-merge@example.invalid")
    user_readme = b"# User repository\n\nOwner bootstrap text.\n"
    upstream_readme = b"# Upstream project\n\nInstall and usage text.\n"
    (repo / "README.md").write_bytes(user_readme)
    base = fixture_commit(repo, "user root")

    fixture_git(repo, "switch", "--orphan", "upstream-root")
    fixture_git(repo, "rm", "-rf", ".", check=False)
    (repo / "README.md").write_bytes(upstream_readme)
    upstream = fixture_commit(repo, "upstream root")
    fixture_git(repo, "switch", "main")
    merge = fixture_git(
        repo,
        "merge",
        "--allow-unrelated-histories",
        "--no-ff",
        "--no-commit",
        upstream,
        check=False,
    )
    assert merge.returncode != 0
    assert fixture_git(
        repo, "diff", "--name-only", "--diff-filter=U"
    ).stdout.strip() == "README.md"

    subprocess.run(
        [
            sys.executable,
            str(COMPOSER),
            "--repository",
            str(repo),
            "--base",
            base,
            "--upstream",
            upstream,
        ],
        check=True,
    )
    fixture_git(repo, "add", "README.md")
    assert fixture_git(repo, "ls-files", "-u").stdout == ""
    combined = (repo / "README.md").read_bytes()
    assert combined.startswith(user_readme + b"\n## Repository lineage\n")
    assert combined.endswith(upstream_readme)

    fixture_git(repo, "commit", "-m", "merge roots")
    parents = fixture_git(repo, "rev-list", "--parents", "-n", "1", "HEAD").stdout.split()
    assert parents[1:] == [base, upstream]
