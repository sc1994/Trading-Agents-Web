#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

LINEAGE = b"""## Repository lineage

This repository retains the repository owner's Trading-Agents-Web bootstrap content above and the complete TauricResearch/TradingAgents v0.4.0 README below. See [UPSTREAM.md](UPSTREAM.md) for the imported release identity, Apache-2.0 license, and manual upstream review process.
"""


def git_bytes(repository: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=repository, check=True, capture_output=True
    ).stdout


def compose(repository: Path, base_ref: str, upstream_ref: str) -> bytes:
    unmerged = git_bytes(
        repository, "diff", "--name-only", "--diff-filter=U"
    ).decode("utf-8").splitlines()
    if unmerged != ["README.md"]:
        raise RuntimeError("README.md must be the only unmerged path")
    user_readme = git_bytes(repository, "show", f"{base_ref}:README.md")
    upstream_readme = git_bytes(repository, "show", f"{upstream_ref}:README.md")
    if not user_readme or not upstream_readme:
        raise RuntimeError("both README inputs must be non-empty")
    separator = b"" if user_readme.endswith(b"\n\n") else b"\n"
    return user_readme + separator + LINEAGE + b"\n---\n\n" + upstream_readme


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument("--base", required=True)
    parser.add_argument("--upstream", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repository = args.repository.resolve()
    combined = compose(repository, args.base, args.upstream)
    (repository / "README.md").write_bytes(combined)


if __name__ == "__main__":
    main()
