import pytest
from fastapi.testclient import TestClient

from web import server


@pytest.fixture
def client(tmp_path):
    with TestClient(server.create_app(data_dir=tmp_path)) as client:
        yield client


@pytest.mark.parametrize("path", ["/", "/index.html", "/tasks/example", "/reports/example", "/settings", "/history"])
def test_spa_routes_return_html_with_security_headers(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<html" in response.text.lower()
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_healthz_returns_exact_body_and_head(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.content == b"ok\n"
    assert response.headers["content-length"] == "3"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    head = client.head("/healthz")
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == "3"
    assert head.headers["cache-control"] == "no-store"
    assert head.headers["x-content-type-options"] == "nosniff"


def test_head_returns_same_spa_headers_without_body(client):
    response = client.head("/")
    assert response.status_code == 200
    assert response.headers["content-length"] == client.get("/").headers["content-length"]
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path",
    [
        "/api/missing",
        "/api",
        "/private/checkpoint-bindings/hmac.key",
        "/cache/checkpoints/NVDA.db",
        "/memory/trading_memory.md",
        "/web.db",
        "/assets/missing.js",
    ],
)
def test_private_and_unknown_api_paths_are_not_spa_fallback(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("value", ["zero", "0", "65536", "-1"])
def test_invalid_environment_ports_are_rejected(monkeypatch, value):
    monkeypatch.setenv("WEB_PORT", value)
    with pytest.raises(ValueError, match="WEB_PORT"):
        server._port_from_environment()


def test_hashed_bundle_assets_have_mime_and_immutable_cache(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<html><script src="/assets/index-aB123456.js"></script></html>'
    )
    (dist / "assets" / "index-aB123456.js").write_text("console.log('bundle')")
    (dist / "assets" / "index-cD123456.css").write_text("body { color: green; }")
    private = tmp_path / "private.key"
    private.write_text("must-not-serve")
    (dist / "assets" / "leak-aB123456.js").symlink_to(private)
    monkeypatch.setattr(server, "STATIC_DIR", dist)
    with TestClient(server.create_app(data_dir=tmp_path / "data")) as client:
        assert "/assets/index-aB123456.js" in client.get("/").text
        for name, mime in [("index-aB123456.js", "javascript"), ("index-cD123456.css", "text/css")]:
            response = client.get(f"/assets/{name}")
            assert response.status_code == 200
            assert mime in response.headers["content-type"]
            assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert client.get("/assets/leak-aB123456.js").status_code == 404
