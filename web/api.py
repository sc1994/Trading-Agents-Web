"""Public HTTP projections; graph state and credentials never cross this boundary."""

import json
import re
import shutil
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from web.reports import decision_view
from web.search import search_symbols
from web.validation import validate_task

Status = Literal["queued", "running", "completed", "failed", "interrupted"]
Rating = Literal["Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"]
HEARTBEAT_SECONDS = 15
router = APIRouter(prefix="/api")


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TaskInput(InputModel):
    ticker: str
    date: str
    name: str = Field(default="", max_length=200)
    asset_type: str = "auto"
    analysts: list[str] | None = None
    depth: str = "standard"
    language: str | None = None
    provider: str | None = None
    quick_model: str | None = None
    deep_model: str | None = None
    max_debate_rounds: int | None = None
    max_risk_discuss_rounds: int | None = None
    checkpoint_enabled: bool | None = None


class SettingsInput(InputModel):
    provider: str | None = None
    quick_model: str | None = None
    deep_model: str | None = None
    language: str | None = None
    checkpoint_enabled: bool | None = None
    keys: dict[str, str] = Field(default_factory=dict)
    clear_keys: list[str] = Field(default_factory=list)


class ConnectionInput(InputModel):
    provider: str


class KeyStatus(BaseModel):
    configured: bool
    last4: str | None


class SettingsView(BaseModel):
    provider: str
    quick_model: str
    deep_model: str
    language: str
    checkpoint_enabled: bool
    keys: dict[str, KeyStatus]


class TaskView(BaseModel):
    id: str
    params: dict
    ticker: str
    name: str
    date: str
    status: Status
    current_stage: str | None
    current_node: str | None
    rating: Rating | None
    decision: str | None
    error: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    sections: dict[str, str]
    can_resume: bool = False


class TaskList(BaseModel):
    tasks: list[TaskView]


class ReportView(BaseModel):
    task_id: str
    sections: dict[str, str]
    decision: dict | None


def _get_task(request: Request, task_id: str) -> dict:
    task = request.app.state.store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


def _view(request: Request, task: dict) -> TaskView:
    # Resume availability is a nonblocking hint, rechecked by the runner on execution.
    can_resume = task["status"] == "interrupted" and request.app.state.runner.can_resume(task)
    return TaskView(**task, can_resume=can_resume)


def _invalid(error: ValueError) -> HTTPException:
    # Domain validators use fixed messages, never interpolating user input or keys.
    message = str(error)
    field = message.split(" ", 1)[0]
    if field not in TaskInput.model_fields and field not in SettingsInput.model_fields:
        field = "provider" if message.startswith("credential") else "body"
    return HTTPException(422, [{"loc": ["body", field], "msg": message}])


@router.get("/assets/search")
def search(request: Request, q: str = Query(min_length=2, max_length=64)):
    try:
        return search_symbols(q, catalog_path=request.app.state.data_dir / "assets.json")
    except ValueError as error:
        raise _invalid(error) from None


@router.get("/settings", response_model=SettingsView)
def settings(request: Request):
    return request.app.state.settings.public()


@router.patch("/settings", response_model=SettingsView)
def update_settings(body: SettingsInput, request: Request):
    try:
        return request.app.state.settings.update(body.model_dump(exclude_unset=True))
    except ValueError as error:
        raise _invalid(error) from None


@router.post("/settings/test-connection")
def test_connection(body: ConnectionInput, request: Request):
    try:
        return request.app.state.settings.test_connection(body.provider)
    except ValueError as error:
        raise _invalid(error) from None


@router.post("/tasks", response_model=TaskView, status_code=201)
def create_task(body: TaskInput, request: Request):
    service = request.app.state.settings
    defaults = {**service.public(), "analysts": ["market", "social", "news", "fundamentals"]}
    raw = body.model_dump(exclude_unset=True)
    try:
        params = validate_task(raw, defaults)
        params["checkpoint_enabled"] = raw.get("checkpoint_enabled", defaults["checkpoint_enabled"])
        service.resolve_run_config(params)  # Validate credentials without persisting the envelope.
    except ValueError as error:
        raise _invalid(error) from None
    params["name"] = body.name.strip()
    task_id = request.app.state.store.create_task(params)
    return _view(request, _get_task(request, task_id))


@router.get("/tasks", response_model=TaskList)
def list_tasks(
    request: Request,
    q: str = Query(default="", max_length=200),
    status: Status | None = None,
    rating: Rating | None = None,
):
    tasks = request.app.state.store.list_tasks(query=q, status=status or "", rating=rating or "")
    return TaskList(tasks=[_view(request, task) for task in tasks])


@router.get("/tasks/{task_id}", response_model=TaskView)
def get_task(task_id: str, request: Request):
    return _view(request, _get_task(request, task_id))


@router.get("/tasks/{task_id}/report", response_model=ReportView)
def report(task_id: str, request: Request):
    task = _get_task(request, task_id)
    decision = None
    if task["decision"]:
        decision = {**decision_view(task["decision"]), "rating": task["rating"]}
    return ReportView(task_id=task_id, sections=task["sections"], decision=decision)


@router.get("/tasks/{task_id}/report.md")
def markdown_report(task_id: str, request: Request):
    task = _get_task(request, task_id)
    text = f"# {task['ticker']} — {task['date']}\n\n"
    text += "\n\n".join(
        f"## {section}\n\n{content}" for section, content in task["sections"].items()
    )
    filename = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{task['ticker']}-{task['date']}-{task_id}.md")
    return Response(
        text + "\n",
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/tasks/{task_id}/resume", response_model=TaskView)
def resume(task_id: str, request: Request):
    _get_task(request, task_id)
    try:
        return _view(request, request.app.state.worker.resume(task_id))
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/tasks/{task_id}/rerun", response_model=TaskView, status_code=201)
def rerun(task_id: str, request: Request):
    task = _get_task(request, task_id)
    try:
        request.app.state.settings.resolve_run_config(task["params"])
    except ValueError as error:
        raise _invalid(error) from None
    return _view(request, request.app.state.worker.rerun(task_id))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, request: Request):
    _get_task(request, task_id)
    if not request.app.state.store.delete_task(task_id):
        raise HTTPException(409, "Running tasks cannot be deleted")
    # UUID filenames only, and never follow a report-directory symlink into shared state.
    root: Path = request.app.state.data_dir / "reports"
    target = root / str(UUID(task_id))
    if target.is_symlink():
        target.unlink()
    elif target.is_dir() and root.resolve() == root and target.resolve().parent == root:
        shutil.rmtree(target)
    return Response(status_code=204)


@router.get("/tasks/{task_id}/events")
async def events(task_id: str, request: Request, after: int = Query(default=0, ge=0, le=2**63 - 1)):
    await run_in_threadpool(_get_task, request, task_id)
    try:
        cursor = int(request.headers.get("last-event-id", str(after)))
        if not 0 <= cursor <= 2**63 - 1:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "Event cursor must be a nonnegative integer") from None
    worker = request.app.state.worker

    async def stream():
        nonlocal cursor
        while not await request.is_disconnected():
            batch = await run_in_threadpool(
                worker.wait_for_events, task_id, cursor, HEARTBEAT_SECONDS
            )
            for event in batch:
                cursor = event["id"]
                yield f"id: {cursor}\nevent: {event['kind']}\ndata: {json.dumps(event['payload'], ensure_ascii=False)}\n\n"
            if not batch:
                task = await run_in_threadpool(request.app.state.store.get_task, task_id)
                if task is None or task["status"] in {"completed", "failed", "interrupted"}:
                    # Re-read after snapshot to include a terminal commit racing this read.
                    trailing = await run_in_threadpool(
                        request.app.state.store.events_after, task_id, cursor
                    )
                    for event in trailing:
                        yield f"id: {event['id']}\nevent: {event['kind']}\ndata: {json.dumps(event['payload'], ensure_ascii=False)}\n\n"
                    return
                yield ": ping\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
