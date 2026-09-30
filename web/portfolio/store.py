"""Durable portfolio state, independent of immutable research tasks."""

import json
from decimal import Decimal
from uuid import uuid4

from web.portfolio.domain import DomainError, positive_decimal, reason_text, validate_plan
from web.store import Store, _json, _now


class PortfolioStore:
    def __init__(self, store: Store):
        self.store = store
        with store.transaction(immediate=True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS portfolio_instruments (
                    symbol TEXT PRIMARY KEY, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portfolio_watchlist (
                    symbol TEXT PRIMARY KEY REFERENCES portfolio_instruments(symbol),
                    reason TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portfolio_plans (
                    id TEXT PRIMARY KEY, symbol TEXT NOT NULL REFERENCES portfolio_instruments(symbol),
                    data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL CHECK(status IN ('active', 'closed')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS portfolio_checks (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL CHECK(source IN ('manual', 'automatic')),
                    target_date TEXT, attempt INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                        ('queued', 'running', 'completed', 'partial', 'failed', 'interrupted')),
                    plans TEXT NOT NULL DEFAULT '[]', results TEXT NOT NULL DEFAULT '[]',
                    error_code TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS portfolio_single_pending
                    ON portfolio_checks((1)) WHERE status IN ('queued', 'running');
                CREATE UNIQUE INDEX IF NOT EXISTS portfolio_auto_attempt
                    ON portfolio_checks(target_date, attempt) WHERE source='automatic';
                CREATE TABLE IF NOT EXISTS portfolio_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL
                );
            """)
            db.execute("INSERT OR IGNORE INTO portfolio_settings VALUES (1, ?)",
                       (_json({"automatic": True, "concentration_limit": None}),))

    @staticmethod
    def _instrument(db, symbol):
        row = db.execute("SELECT data FROM portfolio_instruments WHERE symbol=?", (symbol,)).fetchone()
        if row is None:
            raise DomainError("instrument_unverified", "symbol")
        return json.loads(row["data"])

    def get_instrument(self, symbol: str) -> dict:
        with self.store.transaction() as db:
            return self._instrument(db, symbol)

    def upsert_instrument(self, instrument: dict) -> dict:
        suffix = {"SH": "SS", "SZ": "SZ", "BJ": "BJ"}.get(instrument.get("exchange"))
        symbol = instrument.get("symbol", "")
        if (not suffix or instrument.get("security_type") != "A_SHARE"
                or instrument.get("currency") != "CNY" or not instrument.get("verified_at")
                or not isinstance(symbol, str) or len(symbol) != 9
                or not symbol[:6].isdigit() or not symbol.endswith("." + suffix)):
            raise DomainError("unsupported_market", "symbol")
        with self.store.transaction(immediate=True) as db:
            db.execute("INSERT INTO portfolio_instruments VALUES (?, ?) "
                       "ON CONFLICT(symbol) DO UPDATE SET data=excluded.data",
                       (symbol, _json(instrument)))
        return instrument

    @staticmethod
    def _limit(db, symbol):
        rows = db.execute("SELECT symbol FROM portfolio_watchlist UNION "
                          "SELECT symbol FROM portfolio_plans WHERE status='active'").fetchall()
        symbols = {r["symbol"] for r in rows}
        if symbol not in symbols and len(symbols) >= 100:
            raise DomainError("stock_limit", "symbol")

    def add_watch(self, symbol: str, reason: str) -> dict:
        reason, now = reason_text(reason), _now()
        with self.store.transaction(immediate=True) as db:
            self._instrument(db, symbol)
            self._limit(db, symbol)
            if db.execute("SELECT 1 FROM portfolio_watchlist WHERE symbol=?", (symbol,)).fetchone():
                raise DomainError("watch_exists", "symbol")
            db.execute("INSERT INTO portfolio_watchlist VALUES (?, ?, ?, ?)",
                       (symbol, reason, now, now))
        return next(w for w in self.list_watchlist() if w["symbol"] == symbol)

    def update_watch(self, symbol: str, reason: str) -> dict:
        with self.store.transaction(immediate=True) as db:
            changed = db.execute("UPDATE portfolio_watchlist SET reason=?, updated_at=? WHERE symbol=?",
                                 (reason_text(reason), _now(), symbol))
            if not changed.rowcount:
                raise DomainError("not_found")
        return next(w for w in self.list_watchlist() if w["symbol"] == symbol)

    def remove_watch(self, symbol: str) -> None:
        with self.store.transaction(immediate=True) as db:
            if not db.execute("DELETE FROM portfolio_watchlist WHERE symbol=?", (symbol,)).rowcount:
                raise DomainError("not_found")

    def list_watchlist(self) -> list[dict]:
        with self.store.transaction() as db:
            return [{**self._instrument(db, row["symbol"]), **dict(row)} for row in db.execute(
                "SELECT * FROM portfolio_watchlist ORDER BY created_at DESC, symbol")]

    @classmethod
    def _plan(cls, db, row) -> dict:
        if row is None:
            raise DomainError("not_found")
        return {**json.loads(row["data"]), **{k: row[k] for k in (
            "id", "revision", "status", "created_at", "updated_at")},
            "instrument": cls._instrument(db, row["symbol"])}

    def list_plans(self, active_only: bool = True) -> list[dict]:
        with self.store.transaction() as db:
            return [self._plan(db, row) for row in db.execute(
                "SELECT * FROM portfolio_plans WHERE (?=0 OR status='active') "
                "ORDER BY created_at, id", (int(active_only),))]

    def create_plan(self, raw: dict) -> dict:
        value, plan_id, now = validate_plan(raw), str(uuid4()), _now()
        with self.store.transaction(immediate=True) as db:
            self._instrument(db, value["symbol"])
            self._limit(db, value["symbol"])
            db.execute("INSERT INTO portfolio_plans VALUES (?, ?, ?, 1, 'active', ?, ?)",
                       (plan_id, value["symbol"], _json(value), now, now))
            return self._plan(db, db.execute("SELECT * FROM portfolio_plans WHERE id=?", (plan_id,)).fetchone())

    def update_plan(self, id: str, revision: int, raw: dict) -> dict:
        with self.store.transaction(immediate=True) as db:
            row = db.execute("SELECT * FROM portfolio_plans WHERE id=?", (id,)).fetchone()
            self._guard(row, revision)
            value = validate_plan({**json.loads(row["data"]), **raw})
            if value["symbol"] != row["symbol"]:
                raise DomainError("symbol_immutable", "symbol")
            db.execute("UPDATE portfolio_plans SET data=?, revision=revision+1, updated_at=? WHERE id=?",
                       (_json(value), _now(), id))
            return self._plan(db, db.execute("SELECT * FROM portfolio_plans WHERE id=?", (id,)).fetchone())

    @staticmethod
    def _guard(row, revision):
        if row is None:
            raise DomainError("not_found")
        if type(revision) is not int or row["revision"] != revision:
            raise DomainError("revision_conflict", "revision")
        if row["status"] != "active":
            raise DomainError("plan_closed")

    def close_plan(self, id: str, revision: int) -> dict:
        with self.store.transaction(immediate=True) as db:
            row = db.execute("SELECT * FROM portfolio_plans WHERE id=?", (id,)).fetchone()
            self._guard(row, revision)
            db.execute("UPDATE portfolio_plans SET status='closed', revision=revision+1, updated_at=? WHERE id=?",
                       (_now(), id))
            return self._plan(db, db.execute("SELECT * FROM portfolio_plans WHERE id=?", (id,)).fetchone())

    def get_settings(self) -> dict:
        with self.store.transaction() as db:
            return json.loads(db.execute("SELECT data FROM portfolio_settings WHERE id=1").fetchone()["data"])

    def update_settings(self, raw: dict) -> dict:
        if set(raw) - {"automatic", "concentration_limit"}:
            raise DomainError("invalid_fields")
        with self.store.transaction(immediate=True) as db:
            value = {**json.loads(db.execute("SELECT data FROM portfolio_settings WHERE id=1").fetchone()["data"]), **raw}
            if type(value["automatic"]) is not bool:
                raise DomainError("invalid_boolean", "automatic")
            if value["concentration_limit"] is not None:
                value["concentration_limit"] = positive_decimal(value["concentration_limit"], "concentration_limit")
                if Decimal(value["concentration_limit"]) > 100:
                    raise DomainError("invalid_threshold", "concentration_limit")
            db.execute("UPDATE portfolio_settings SET data=? WHERE id=1", (_json(value),))
            return value

    @staticmethod
    def _check(row):
        if row is None:
            return None
        return {**dict(row), "plans": json.loads(row["plans"]), "results": json.loads(row["results"])}

    def enqueue(self, source: str, target_date: str | None, attempt: int = 0,
                requested_at: str | None = None) -> dict:
        with self.store.transaction(immediate=True) as db:
            pending = db.execute("SELECT * FROM portfolio_checks WHERE status IN ('queued', 'running')").fetchone()
            if pending:
                return self._check(pending)
            if source == "automatic":
                prior = db.execute("SELECT * FROM portfolio_checks WHERE source='automatic' "
                                   "AND target_date=? AND attempt=?", (target_date, attempt)).fetchone()
                if prior:
                    return self._check(prior)
            check_id = str(uuid4())
            db.execute("INSERT INTO portfolio_checks(id, source, target_date, attempt, status, created_at) "
                       "VALUES (?, ?, ?, ?, 'queued', ?)",
                       (check_id, source, target_date, attempt, requested_at or _now()))
            return self._check(db.execute("SELECT * FROM portfolio_checks WHERE id=?", (check_id,)).fetchone())

    def claim(self) -> dict | None:
        with self.store.transaction(immediate=True) as db:
            row = db.execute("SELECT * FROM portfolio_checks WHERE status='queued'").fetchone()
            if row is None:
                return None
            plans = [self._plan(db, p) for p in db.execute("SELECT * FROM portfolio_plans WHERE status='active' ORDER BY id")]
            db.execute("UPDATE portfolio_checks SET status='running', started_at=?, plans=? WHERE id=?",
                       (_now(), json.dumps(plans, ensure_ascii=False, allow_nan=False), row["id"]))
            return self._check(db.execute("SELECT * FROM portfolio_checks WHERE id=?", (row["id"],)).fetchone())

    def set_target(self, id: str, target_date: str) -> None:
        with self.store.transaction(immediate=True) as db:
            db.execute("UPDATE portfolio_checks SET target_date=? WHERE id=? AND status='running'", (target_date, id))

    def complete(self, id: str, results: list[dict], status: str) -> dict:
        if status not in {"completed", "partial", "failed"}:
            raise DomainError("invalid_check_status")
        with self.store.transaction(immediate=True) as db:
            encoded = json.dumps(results, ensure_ascii=False, allow_nan=False)
            if not db.execute("UPDATE portfolio_checks SET results=?, status=?, finished_at=? "
                              "WHERE id=? AND status='running'", (encoded, status, _now(), id)).rowcount:
                raise DomainError("check_not_running")
            return self._check(db.execute("SELECT * FROM portfolio_checks WHERE id=?", (id,)).fetchone())

    def fail(self, id: str, code: str) -> dict:
        with self.store.transaction(immediate=True) as db:
            db.execute("UPDATE portfolio_checks SET status='failed', error_code=?, finished_at=? "
                       "WHERE id=? AND status='running'", (code, _now(), id))
            return self._check(db.execute("SELECT * FROM portfolio_checks WHERE id=?", (id,)).fetchone())

    def get_check(self, id: str) -> dict | None:
        with self.store.transaction() as db:
            return self._check(db.execute("SELECT * FROM portfolio_checks WHERE id=?", (id,)).fetchone())

    def latest_check(self) -> dict | None:
        with self.store.transaction() as db:
            return self._check(db.execute("SELECT * FROM portfolio_checks ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone())

    def automatic_attempts(self, target_date: str) -> list[dict]:
        with self.store.transaction() as db:
            return [self._check(r) for r in db.execute("SELECT * FROM portfolio_checks "
                    "WHERE source='automatic' AND target_date=? ORDER BY attempt", (target_date,))]

    def has_success(self, target_date: str) -> bool:
        with self.store.transaction() as db:
            return db.execute("SELECT 1 FROM portfolio_checks WHERE target_date=? AND status='completed'",
                              (target_date,)).fetchone() is not None

    def recover(self) -> None:
        with self.store.transaction(immediate=True) as db:
            db.execute("UPDATE portfolio_checks SET status='interrupted', error_code='interrupted', "
                       "finished_at=? WHERE status='running'", (_now(),))
