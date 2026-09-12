#!/usr/bin/env python3
"""Serve the empty web placeholder and a dependency-free readiness endpoint."""

from __future__ import annotations

import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

INDEX_HTML = (Path(__file__).resolve().parent / "index.html").read_bytes()
HEALTH_BODY = b"ok\n"


class WebHandler(BaseHTTPRequestHandler):
    server_version = "TradingAgentsWeb/0.1"
    sys_version = ""

    def do_GET(self) -> None:
        self._handle_request(send_body=True)

    def do_HEAD(self) -> None:
        self._handle_request(send_body=False)

    def _handle_request(self, *, send_body: bool) -> None:
        path = urlsplit(self.path).path
        if path in {"/", "/index.html"}:
            self._send_response(
                HTTPStatus.OK,
                INDEX_HTML,
                "text/html; charset=utf-8",
                send_body=send_body,
            )
            return
        if path == "/healthz":
            self._send_response(
                HTTPStatus.OK,
                HEALTH_BODY,
                "text/plain; charset=utf-8",
                send_body=send_body,
            )
            return
        self._send_response(
            HTTPStatus.NOT_FOUND,
            b"not found\n",
            "text/plain; charset=utf-8",
            send_body=send_body,
        )

    def _send_response(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        send_body: bool,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if send_body:
            self.wfile.write(body)


def _port_from_environment() -> int:
    raw_port = os.environ.get("WEB_PORT", "8080")
    try:
        port = int(raw_port)
    except ValueError as error:
        raise ValueError("WEB_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("WEB_PORT must be between 1 and 65535")
    return port


def create_server(
    host: str | None = None, port: int | None = None
) -> ThreadingHTTPServer:
    bind_host = host if host is not None else os.environ.get("WEB_HOST", "0.0.0.0")
    bind_port = _port_from_environment() if port is None else port
    if not 0 <= bind_port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    return ThreadingHTTPServer((bind_host, bind_port), WebHandler)


def main() -> None:
    server = create_server()
    print(f"local web placeholder listening on http://{server.server_address[0]}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
