import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts/local_image_release.py"
SPEC = importlib.util.spec_from_file_location("local_image_release", MODULE_PATH)
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)

SHA = "1" * 40
OLD_1 = "2" * 40
OLD_2 = "3" * 40
OLD_3 = "4" * 40


def completed(stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["docker"], 0, stdout=stdout, stderr="")


def test_smoke_failure_never_tags_full_sha_or_stable() -> None:
    docker = Mock()
    docker.inspect.return_value = release.ImageInfo(
        id="sha256:candidate",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    docker.exists.side_effect = [False, False]
    docker.call.side_effect = [
        completed(),
        subprocess.CalledProcessError(1, ["docker", "run"]),
    ]
    with pytest.raises(subprocess.CalledProcessError):
        release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)
    calls = [call.args[0] for call in docker.call.call_args_list]
    assert not any(args[:2] == ["image", "tag"] for args in calls)


def test_publish_smokes_offline_before_updating_stable() -> None:
    docker = Mock()
    candidate = release.ImageInfo(
        id="sha256:candidate",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    docker.inspect.return_value = candidate
    docker.exists.side_effect = [False, False, True, False]
    docker.call.return_value = completed()
    docker.list_managed_sha_images.return_value = [candidate]
    docker.used_image_ids.return_value = set()
    release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)
    calls = [call.args[0] for call in docker.call.call_args_list]
    smoke_index = next(i for i, args in enumerate(calls) if args[0] == "run")
    stable_index = calls.index(
        ["image", "tag", f"trading-agents-web:{SHA}", "trading-agents-web:local-stable"]
    )
    assert smoke_index < stable_index
    smoke = calls[smoke_index]
    assert smoke[smoke.index("--network") : smoke.index("--network") + 2] == ["--network", "none"]
    assert "--read-only" in smoke
    assert smoke[-1] == "--help"


def test_matching_immutable_sha_is_reused_without_build_or_overwrite() -> None:
    docker = Mock()
    existing = release.ImageInfo(
        id="sha256:existing",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    docker.exists.side_effect = [True, True]
    docker.inspect.return_value = existing
    docker.list_managed_sha_images.return_value = [existing]
    docker.used_image_ids.return_value = set()
    docker.call.return_value = completed()

    release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)

    calls = [call.args[0] for call in docker.call.call_args_list]
    assert not any(args[0] == "build" for args in calls)
    assert ["image", "tag", f"trading-agents-web:{SHA}", "trading-agents-web:local-stable"] in calls
    assert not any(
        args[:3] == ["image", "tag", f"trading-agents-web:candidate-{SHA}-7"]
        for args in calls
    )


def test_conflicting_immutable_sha_is_rejected_before_docker_mutation() -> None:
    docker = Mock()
    docker.exists.return_value = True
    docker.inspect.return_value = release.ImageInfo(
        id="sha256:foreign",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=False,
    )
    with pytest.raises(RuntimeError, match="immutable SHA tag conflicts"):
        release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)
    assert docker.call.call_count == 0


def test_racing_immutable_tag_with_different_id_is_never_overwritten() -> None:
    docker = Mock()
    candidate = release.ImageInfo(
        id="sha256:candidate",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    existing = release.ImageInfo(
        id="sha256:other",
        created="2026-09-01T00:00:01Z",
        revision=SHA,
        managed=True,
    )
    docker.exists.side_effect = [False, True, False]
    docker.inspect.side_effect = [candidate, existing]
    docker.call.return_value = completed()
    with pytest.raises(RuntimeError, match="different image ID"):
        release.publish(docker, SHA, "trading-agents-web", 3, Path("."), pid=7)
    calls = [call.args[0] for call in docker.call.call_args_list]
    assert not any(
        args == [
            "image",
            "tag",
            f"trading-agents-web:candidate-{SHA}-7",
            f"trading-agents-web:{SHA}",
        ]
        for args in calls
    )
    assert not any(args[-1:] == ["trading-agents-web:local-stable"] for args in calls)


def test_cleanup_counts_rolled_back_stable_among_three_and_skips_in_use() -> None:
    docker = Mock()
    stable = release.ImageInfo("id-stable", "2026-09-01T00:00:00Z", OLD_3, True)
    docker.exists.return_value = True
    docker.inspect.return_value = stable
    docker.list_managed_sha_images.return_value = [
        release.ImageInfo("id-new", "2026-09-05T00:00:00Z", SHA, True),
        release.ImageInfo("id-2", "2026-09-04T00:00:00Z", OLD_1, True),
        release.ImageInfo("id-used", "2026-09-03T00:00:00Z", OLD_2, True),
        stable,
        release.ImageInfo("id-old", "2026-08-31T00:00:00Z", "5" * 40, True),
    ]
    docker.used_image_ids.return_value = {"id-used"}
    release.cleanup(docker, "trading-agents-web", keep=3)
    docker.remove_image.assert_called_once_with(f"trading-agents-web:{'5' * 40}")
    assert all(OLD_3 not in str(call) for call in docker.remove_image.call_args_list)


def test_cleanup_refuses_stable_without_matching_full_sha_tag() -> None:
    docker = Mock()
    docker.exists.return_value = True
    docker.inspect.return_value = release.ImageInfo(
        "id-stable", "2026-09-01T00:00:00Z", OLD_3, True
    )
    docker.list_managed_sha_images.return_value = [
        release.ImageInfo("id-new", "2026-09-05T00:00:00Z", SHA, True)
    ]
    with pytest.raises(RuntimeError, match="matching immutable SHA tag"):
        release.cleanup(docker, "trading-agents-web", keep=3)
    docker.remove_image.assert_not_called()


def test_rollback_requires_matching_managed_revision() -> None:
    docker = Mock()
    docker.inspect.return_value = release.ImageInfo(
        id="sha256:kept",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=True,
    )
    release.rollback(docker, SHA, "trading-agents-web")
    docker.call.assert_called_once_with(
        ["image", "tag", f"trading-agents-web:{SHA}", "trading-agents-web:local-stable"]
    )


def test_short_sha_is_rejected_before_docker_is_called() -> None:
    docker = Mock()
    with pytest.raises(ValueError, match="40 lowercase"):
        release.publish(docker, "abc", "trading-agents-web", 3, Path("."))
    assert docker.method_calls == []


def test_rollback_rejects_unmanaged_image() -> None:
    docker = Mock()
    docker.inspect.return_value = release.ImageInfo(
        id="sha256:foreign",
        created="2026-09-01T00:00:00Z",
        revision=SHA,
        managed=False,
    )
    with pytest.raises(RuntimeError, match="not a managed successful"):
        release.rollback(docker, SHA, "trading-agents-web")
    docker.call.assert_not_called()
