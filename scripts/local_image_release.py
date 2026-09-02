#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
REVISION_LABEL = "org.opencontainers.image.revision"
MANAGED_LABEL = "io.trading-agents-web.managed"


@dataclass(frozen=True)
class ImageInfo:
    id: str
    created: str
    revision: str
    managed: bool


class DockerClient:
    def call(
        self,
        args: Sequence[str],
        *,
        check: bool = True,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", *args],
            check=check,
            text=True,
            capture_output=capture_output,
        )

    def inspect(self, ref: str) -> ImageInfo:
        result = self.call(
            ["image", "inspect", "--format", "{{json .}}", ref],
            capture_output=True,
        )
        payload = json.loads(result.stdout)
        labels = payload.get("Config", {}).get("Labels") or {}
        return ImageInfo(
            id=payload["Id"],
            created=payload["Created"],
            revision=labels.get(REVISION_LABEL, ""),
            managed=labels.get(MANAGED_LABEL) == "true",
        )

    def exists(self, ref: str) -> bool:
        result = self.call(["image", "inspect", ref], check=False, capture_output=True)
        return result.returncode == 0

    def list_managed_sha_images(self, image: str) -> list[ImageInfo]:
        result = self.call(
            ["image", "ls", "--format", "{{.Repository}}\t{{.Tag}}", image],
            capture_output=True,
        )
        images: list[ImageInfo] = []
        for line in result.stdout.splitlines():
            repository, tag = line.split("\t", maxsplit=1)
            if repository != image or not FULL_SHA.fullmatch(tag):
                continue
            info = self.inspect(f"{image}:{tag}")
            if info.managed and info.revision == tag:
                images.append(info)
        return images

    def used_image_ids(self) -> set[str]:
        ids = self.call(
            ["container", "ls", "--all", "--quiet"], capture_output=True
        ).stdout.split()
        if not ids:
            return set()
        output = self.call(
            ["container", "inspect", "--format", "{{.Image}}", *ids],
            capture_output=True,
        ).stdout
        return set(output.split())

    def remove_image(self, ref: str) -> None:
        self.call(["image", "rm", ref])


def validate_sha(value: str) -> str:
    if not FULL_SHA.fullmatch(value):
        raise ValueError("SHA must be 40 lowercase hexadecimal characters")
    return value


def require_immutable(info: ImageInfo, sha: str) -> ImageInfo:
    if not info.managed or info.revision != sha:
        raise RuntimeError("immutable SHA tag conflicts with managed release metadata")
    return info


def smoke(docker: DockerClient, ref: str) -> None:
    docker.call(
        [
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            ref,
            "--help",
        ]
    )


def cleanup(docker: DockerClient, image: str, keep: int) -> None:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    images = sorted(
        docker.list_managed_sha_images(image),
        key=lambda item: (item.created, item.revision),
        reverse=True,
    )
    stable_ref = f"{image}:local-stable"
    if not docker.exists(stable_ref):
        raise RuntimeError("local-stable is missing; refusing cleanup")
    stable = docker.inspect(stable_ref)
    if not stable.managed or not FULL_SHA.fullmatch(stable.revision):
        raise RuntimeError("local-stable is not a managed SHA image; refusing cleanup")
    if not any(
        item.id == stable.id and item.revision == stable.revision for item in images
    ):
        raise RuntimeError("local-stable has no matching immutable SHA tag")

    retained = {stable.revision}
    for info in images:
        if len(retained) >= keep:
            break
        retained.add(info.revision)

    used = docker.used_image_ids()
    for info in images:
        ref = f"{image}:{info.revision}"
        if info.revision in retained:
            continue
        if info.id in used:
            print(f"skip in-use image {ref}")
            continue
        docker.remove_image(ref)
        print(f"removed expired successful image {ref}")


def publish(
    docker: DockerClient,
    sha: str,
    image: str,
    keep: int,
    context: Path,
    *,
    pid: int | None = None,
) -> None:
    sha = validate_sha(sha)
    pid = os.getpid() if pid is None else pid
    candidate = f"{image}:candidate-{sha}-{pid}"
    immutable = f"{image}:{sha}"
    stable = f"{image}:local-stable"

    if docker.exists(immutable):
        require_immutable(docker.inspect(immutable), sha)
        smoke(docker, immutable)
        docker.call(["image", "tag", immutable, stable])
        print(f"reused {immutable} and promoted it to {stable}")
        cleanup(docker, image, keep)
        return

    candidate_created = False
    try:
        docker.call(
            [
                "build",
                "--label",
                f"{REVISION_LABEL}={sha}",
                "--label",
                f"{MANAGED_LABEL}=true",
                "--tag",
                candidate,
                str(context),
            ]
        )
        candidate_created = True
        candidate_info = require_immutable(docker.inspect(candidate), sha)
        smoke(docker, candidate)

        if docker.exists(immutable):
            existing = require_immutable(docker.inspect(immutable), sha)
            if existing.id != candidate_info.id:
                raise RuntimeError(
                    "immutable SHA tag appeared with a different image ID; refusing overwrite"
                )
        else:
            docker.call(["image", "tag", candidate, immutable])

        docker.call(["image", "tag", immutable, stable])
        print(f"promoted {immutable} to {stable}")
        cleanup(docker, image, keep)
    finally:
        if candidate_created and docker.exists(candidate):
            docker.call(["image", "rm", candidate], check=False)


def rollback(docker: DockerClient, sha: str, image: str) -> None:
    sha = validate_sha(sha)
    immutable = f"{image}:{sha}"
    info = docker.inspect(immutable)
    if not info.managed or info.revision != sha:
        raise RuntimeError("rollback image is not a managed successful SHA image")
    docker.call(["image", "tag", immutable, f"{image}:local-stable"])
    print(f"rolled local-stable back to {immutable}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--sha", required=True)
    publish_parser.add_argument("--image", default="trading-agents-web")
    publish_parser.add_argument("--keep", type=int, default=3)
    publish_parser.add_argument("--context", type=Path, default=Path("."))
    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--sha", required=True)
    rollback_parser.add_argument("--image", default="trading-agents-web")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    docker = DockerClient()
    if args.command == "publish":
        publish(docker, args.sha, args.image, args.keep, args.context)
    else:
        rollback(docker, args.sha, args.image)


if __name__ == "__main__":
    main()
