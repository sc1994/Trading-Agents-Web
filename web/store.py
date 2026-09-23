"""Durable task, event, and report storage for the single-process web worker."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: dict) -> str:
    def check(item):
        if isinstance(item, dict):
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                normalized = key.lower().replace("-", "").replace("_", "")
                if normalized.endswith("apikey"):
                    raise ValueError("secret api_key fields cannot be persisted")
                check(nested)
        elif isinstance(item, list):
            for nested in item:
                check(nested)
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError("value must be JSON-safe")

    if not isinstance(value, dict):
        raise ValueError("value must be a JSON object")
    check(value)
    try:
        return json.dumps(value, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON-safe") from exc


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.stat().st_mode & 0o7777 != 0o700:
            raise ValueError("database directory must be private (0700)")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    params TEXT NOT NULL,
                    ticker TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT '',
                    date TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK (status IN
                        ('queued', 'running', 'completed', 'failed', 'interrupted')),
                    current_stage TEXT,
                    current_node TEXT,
                    rating TEXT,
                    decision TEXT,
                    error TEXT,
                    resume_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_task_cursor ON events(task_id, id);
                CREATE TABLE IF NOT EXISTS sections (
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    section TEXT NOT NULL,
                    text TEXT NOT NULL,
                    PRIMARY KEY (task_id, section)
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            if "resume_requested" not in {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}:
                db.execute("ALTER TABLE tasks ADD COLUMN resume_requested INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def transaction(self, *, immediate: bool = False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _task(db, row):
        if row is None:
            return None
        task = dict(row)
        task["params"] = json.loads(task["params"])
        task["sections"] = {
            section["section"]: section["text"]
            for section in db.execute(
                "SELECT section, text FROM sections WHERE task_id=? ORDER BY section", (task["id"],)
            )
        }
        return task

    def create_task(self, params: dict) -> str:
        encoded = _json(params)
        task_id, now = str(uuid4()), _now()
        with self.transaction(immediate=True) as db:
            db.execute(
                """INSERT INTO tasks (id, params, ticker, name, date, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)""",
                (
                    task_id,
                    encoded,
                    str(params.get("ticker", "")),
                    str(params.get("name", "")),
                    str(params.get("date", "")),
                    now,
                    now,
                ),
            )
        return task_id

    def get_task(self, task_id: str) -> dict | None:
        with self.transaction() as db:
            return self._task(db, db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def list_tasks(self, *, query: str = "", status: str = "", rating: str = "") -> list[dict]:
        with self.transaction() as db:
            rows = db.execute(
                """SELECT * FROM tasks
                   WHERE (? = '' OR instr(lower(ticker), lower(?)) > 0
                      OR instr(lower(name), lower(?)) > 0)
                     AND (? = '' OR status = ?)
                     AND (? = '' OR rating = ?)
                   ORDER BY created_at DESC, rowid DESC""",
                (query, query, query, status, status, rating, rating),
            ).fetchall()
            return [self._task(db, row) for row in rows]

    def claim_next(self) -> dict | None:
        with self.transaction(immediate=True) as db:
            if db.execute("SELECT 1 FROM tasks WHERE status='running' LIMIT 1").fetchone():
                return None
            row = db.execute(
                "SELECT id FROM tasks WHERE status='queued' ORDER BY created_at, rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            now = _now()
            db.execute(
                """UPDATE tasks SET status='running', started_at=?, updated_at=? WHERE id=?""",
                (now, now, row["id"]),
            )
            return self._task(db, db.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone())

    def append_event(self, task_id: str, kind: str, payload: dict) -> int:
        encoded = _json(payload)
        with self.transaction(immediate=True) as db:
            cursor = db.execute(
                "INSERT INTO events (task_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (task_id, kind, encoded, _now()),
            )
            return cursor.lastrowid

    def events_after(self, task_id: str, last_id: int) -> list[dict]:
        with self.transaction() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id", (task_id, last_id)
            ).fetchall()
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def save_section(self, task_id: str, section: str, text: str) -> None:
        with self.transaction(immediate=True) as db:
            db.execute(
                """INSERT INTO sections (task_id, section, text) VALUES (?, ?, ?)
                   ON CONFLICT(task_id, section) DO UPDATE SET text=excluded.text""",
                (task_id, section, text),
            )
            db.execute("UPDATE tasks SET updated_at=? WHERE id=?", (_now(), task_id))

    def finish(self, task_id: str, rating: str, decision: str) -> None:
        if rating not in {"Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW"}:
            raise ValueError("invalid rating")
        with self.transaction(immediate=True) as db:
            row = db.execute(
                "SELECT text FROM sections WHERE task_id=? AND section='decision'", (task_id,)
            ).fetchone()
            if row is None or not row["text"] or row["text"] != decision:
                raise ValueError("saved decision must match final decision")
            now = _now()
            cursor = db.execute(
                """UPDATE tasks SET status='completed', rating=?, decision=?, error=NULL,
                   finished_at=?, updated_at=? WHERE id=? AND status='running'""",
                (rating, decision, now, now, task_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("only running tasks can finish")
            db.execute(
                "INSERT INTO events (task_id, kind, payload, created_at) VALUES (?, 'completed', ?, ?)",
                (task_id, _json({"rating": rating}), now),
            )

    def fail(self, task_id: str, error: str) -> None:
        with self.transaction(immediate=True) as db:
            now = _now()
            cursor = db.execute(
                """UPDATE tasks SET status='failed', error=?, rating=NULL, finished_at=?,
                   updated_at=? WHERE id=? AND status='running'""",
                (error, now, now, task_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("only running tasks can fail")
            db.execute(
                "INSERT INTO events (task_id, kind, payload, created_at) VALUES (?, 'failed', ?, ?)",
                (task_id, _json({"error": error}), now),
            )

    def requeue_interrupted(self, task_id: str) -> dict:
        """Keep the original immutable graph parameters and persist resume intent."""
        with self.transaction(immediate=True) as db:
            now = _now()
            cursor = db.execute(
                """UPDATE tasks SET status='queued', resume_requested=1, error=NULL,
                   finished_at=NULL, updated_at=? WHERE id=? AND status='interrupted'""",
                (now, task_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("only interrupted tasks can resume")
            db.execute(
                "INSERT INTO events (task_id, kind, payload, created_at) VALUES (?, 'queued', ?, ?)",
                (task_id, _json({"resume_requested": True}), now),
            )
            return self._task(db, db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def interrupt_running(self) -> list[str]:
        with self.transaction(immediate=True) as db:
            now = _now()
            task_ids = [row["id"] for row in db.execute("SELECT id FROM tasks WHERE status='running'")]
            db.execute(
                """UPDATE tasks SET status='interrupted', finished_at=?, updated_at=?
                   WHERE status='running'""",
                (now, now),
            )
            db.executemany(
                "INSERT INTO events (task_id, kind, payload, created_at) VALUES (?, 'interrupted', '{}', ?)",
                [(task_id, now) for task_id in task_ids],
            )
            return task_ids

    def delete_task(self, task_id: str) -> bool:
        with self.transaction(immediate=True) as db:
            cursor = db.execute(
                "DELETE FROM tasks WHERE id=? AND status!='running'", (task_id,)
            )
            return cursor.rowcount == 1

    def get_settings(self) -> dict[str, str]:
        with self.transaction() as db:
            return {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM settings")}

    def update_settings(self, changes: dict[str, str | None]) -> None:
        with self.transaction(immediate=True) as db:
            for key, value in changes.items():
                if value is None:
                    db.execute("DELETE FROM settings WHERE key=?", (key,))
                else:
                    db.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value),
                    )
