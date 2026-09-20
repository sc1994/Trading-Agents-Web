import importlib.util
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "web/index.html"
MODULE_PATH = ROOT / "web/server.py"
SPEC = importlib.util.spec_from_file_location("gateway_web_server", MODULE_PATH)
assert SPEC and SPEC.loader
server_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server_module
SPEC.loader.exec_module(server_module)


@pytest.fixture()
def running_server() -> str:
    server = server_module.create_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_root_and_index_return_exact_checked_in_bytes(running_server: str) -> None:
    for path in ("/", "/index.html"):
        with urlopen(f"{running_server}{path}", timeout=2) as response:
            assert response.status == 200
            assert response.headers["Content-Length"] == str(len(INDEX.read_bytes()))
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.read() == INDEX.read_bytes()


def test_healthz_returns_exact_body(running_server: str) -> None:
    with urlopen(f"{running_server}/healthz", timeout=2) as response:
        assert response.status == 200
        assert response.headers["Content-Length"] == str(len(b"ok\n"))
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.read() == b"ok\n"


def test_head_returns_headers_without_body(running_server: str) -> None:
    request = Request(f"{running_server}/", method="HEAD")
    with urlopen(request, timeout=2) as response:
        assert response.status == 200
        assert response.headers["Content-Length"] == str(len(INDEX.read_bytes()))
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.read() == b""


def test_unknown_path_returns_404(running_server: str) -> None:
    with pytest.raises(HTTPError) as error:
        urlopen(f"{running_server}/missing", timeout=2)
    assert error.value.code == 404
    assert error.value.headers["Content-Length"] == str(len(b"not found\n"))
    assert error.value.headers["Cache-Control"] == "no-store"
    assert error.value.headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("value", ["zero", "0", "65536", "-1"])
def test_invalid_environment_ports_are_rejected(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("WEB_PORT", value)
    with pytest.raises(ValueError, match="WEB_PORT"):
        server_module.create_server()
