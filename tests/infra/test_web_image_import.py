"""Exercise Web imports from the runtime Dockerfile COPY inputs."""

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_image_web_sources_import_without_checkout_fallback(tmp_path):
    runtime = False
    for line in (ROOT / "web/Dockerfile").read_text().splitlines():
        if not line.startswith(("FROM ", "COPY ")):
            continue
        fields = shlex.split(line)
        if not fields:
            continue
        if fields[0] == "FROM":
            runtime = fields[1].startswith("python:")
        if not runtime or fields[0] != "COPY" or fields[1].startswith("--"):
            continue
        destination = tmp_path / fields[-1]
        for source in fields[1:-1]:
            if not source.startswith("web/") and source not in {"tradingagents", "cli"}:
                continue
            destination.mkdir(parents=True, exist_ok=True)
            for entry in ROOT.glob(source):
                if entry.is_dir():
                    shutil.copytree(entry, destination, dirs_exist_ok=True)
                else:
                    shutil.copy2(entry, destination / entry.name)

    result = subprocess.run(
        [sys.executable, "-c", "import web.server; print(web.server.__file__)"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert str(tmp_path / "web/server.py") in result.stdout
