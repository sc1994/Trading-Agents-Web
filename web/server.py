import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

INDEX = Path(__file__).with_name("index.html").read_bytes()
HEALTH = b"ok\n"
NOT_FOUND = b"not found\n"


class GatewayRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._respond(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._respond(send_body=False)

    def _respond(self, *, send_body: bool) -> None:
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            status, body, content_type = 200, INDEX, "text/html; charset=utf-8"
        elif path == "/healthz":
            status, body, content_type = 200, HEALTH, "text/plain; charset=utf-8"
        else:
            status, body, content_type = 404, NOT_FOUND, "text/plain; charset=utf-8"

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if send_body:
            self.wfile.write(body)


def _port_from_environment() -> int:
    value = os.environ.get("WEB_PORT", "8080")
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError("WEB_PORT must be an integer from 1 through 65535") from error
    if not 1 <= port <= 65535:
        raise ValueError("WEB_PORT must be from 1 through 65535")
    return port


def create_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    selected_host = os.environ.get("WEB_HOST", "0.0.0.0") if host is None else host
    if port is None:
        selected_port = _port_from_environment()
    elif port == 0 or 1 <= port <= 65535:
        selected_port = port
    else:
        raise ValueError("port must be 0 or from 1 through 65535")
    return ThreadingHTTPServer((selected_host, selected_port), GatewayRequestHandler)


if __name__ == "__main__":
    server = create_server()
    try:
        server.serve_forever()
    finally:
        server.server_close()
