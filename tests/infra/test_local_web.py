from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "web/server.py"
INDEX = ROOT / "web/index.html"


@pytest.fixture
def running_server():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    environment = os.environ.copy()
    environment.update({"WEB_HOST": "127.0.0.1", "WEB_PORT": str(port)})
    process = subprocess.Popen(
        [sys.executable, str(SERVER)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(
                    f"web server exited early ({process.returncode}): {stdout}{stderr}"
                )
            try:
                with urlopen(f"{base_url}/healthz", timeout=0.2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("web server did not become ready")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def test_root_serves_the_blank_html_page(running_server: str) -> None:
    with urlopen(f"{running_server}/", timeout=2) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "text/html; charset=utf-8"
        assert response.read() == INDEX.read_bytes()


def test_health_endpoint_is_available_without_application_dependencies(
    running_server: str,
) -> None:
    with urlopen(f"{running_server}/healthz", timeout=2) as response:
        assert response.status == 200
        assert response.read() == b"ok\n"


def test_unknown_paths_are_not_served(running_server: str) -> None:
    with pytest.raises(HTTPError) as error:
        urlopen(f"{running_server}/not-found", timeout=2)
    assert error.value.code == 404
