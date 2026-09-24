"""Single-process FastAPI/Uvicorn entrypoint for the private research workbench."""

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from web.api import router
from web.runner import GraphRunner
from web.settings import SettingsService
from web.store import Store
from web.worker import TaskWorker

STATIC_DIR = Path(__file__).parent / "client" / "dist"
_FALLBACK_INDEX = Path(__file__).with_name("index.html")


def create_app(data_dir: Path | None = None, executor: GraphRunner | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        directory = Path(
            data_dir or os.environ.get("TRADINGAGENTS_WEB_DATA_DIR", "data/web")
        ).resolve()
        store = Store(directory / "web.db")
        settings = SettingsService(store)
        runner = executor if executor is not None else GraphRunner(settings, directory)
        worker = TaskWorker(store, runner)
        app.state.data_dir = directory
        app.state.store = store
        app.state.settings = settings
        app.state.runner = runner
        app.state.worker = worker
        await run_in_threadpool(worker.start)
        try:
            yield
        finally:
            await run_in_threadpool(worker.stop)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security(request: Request, call_next):
        response = None
        # Entry access control (Basic Auth, network allow-list) is owned by the
        # reverse proxy in front of the app, never by host matching here: the
        # workbench is reached through several proxy entries (domain, tunnel
        # host:port) whose Host/Origin/scheme the proxy legitimately rewrites, so
        # pinning any one of them breaks the others. Sec-Fetch-Site is set by the
        # browser and cannot be forged by page script, so a genuinely cross-site
        # write from another site is still refused.
        if request.method not in {"GET", "HEAD", "OPTIONS"} and (
            request.headers.get("sec-fetch-site") == "cross-site"
        ):
            response = JSONResponse({"detail": "Cross-site writes are forbidden"}, status_code=403)
        if response is None:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic's default errors include raw input, including invalid API keys.
        details = [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return JSONResponse({"detail": details}, status_code=422)

    @app.api_route("/healthz", methods=["GET", "HEAD"])
    def health():
        return PlainTextResponse("ok\n")

    app.include_router(router)

    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    def static_app(path: str):
        root = STATIC_DIR.resolve()
        if path.startswith("assets/"):
            candidate = (root / path).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                raise HTTPException(404, "Not found")
            headers = {}
            if re.search(r"-[A-Za-z0-9_-]{8,}\.[^.]+$", candidate.name):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return FileResponse(candidate, headers=headers)
        if path not in {"", "index.html", "history", "settings", "tasks"} and not (
            path.startswith(("tasks/", "reports/"))
            and all(part not in {"", ".", ".."} for part in path.split("/"))
        ):
            raise HTTPException(404, "Not found")
        index = root / "index.html"
        if not index.is_file():
            index = _FALLBACK_INDEX
        if not index.resolve().is_relative_to(root) and index != _FALLBACK_INDEX:
            raise HTTPException(404, "Not found")
        return FileResponse(index, media_type="text/html")

    return app


def _port_from_environment() -> int:
    value = os.environ.get("WEB_PORT", "8080")
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError("WEB_PORT must be an integer from 1 through 65535") from error
    if not 1 <= port <= 65535:
        raise ValueError("WEB_PORT must be from 1 through 65535")
    return port


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        app, host=os.environ.get("WEB_HOST", "0.0.0.0"), port=_port_from_environment(), workers=1
    )
