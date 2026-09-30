"""Independent close-check queue with verified dates and bounded daily retries."""

from datetime import datetime, time, timedelta, timezone
from threading import Event, Lock, Thread
from zoneinfo import ZoneInfo

from web.portfolio.domain import DomainError, evaluate

SHANGHAI = ZoneInfo("Asia/Shanghai")
CUTOFF = time(16, 30)


def completed_date(now: datetime, calendar: dict) -> str:
    local = now.astimezone(SHANGHAI)
    day = local.date().isoformat()
    if day < calendar["covered_from"] or (local.weekday() < 5 and day > calendar["covered_until"]):
        raise DomainError("calendar_unavailable")
    candidates = [d for d in calendar["dates"] if d < day or (d == day and local.time() >= CUTOFF)]
    if not candidates:
        raise DomainError("calendar_unavailable")
    return max(candidates)


class CloseCheckWorker:
    def __init__(self, store, market, clock=None):
        self.store, self.market = store, market
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._stopping, self._wake = Event(), Event()
        self._tick_lock, self._lifecycle = Lock(), Lock()
        self._thread = None

    def start(self):
        with self._lifecycle:
            if self._thread and self._thread.is_alive():
                return
            self.store.recover()
            self._stopping.clear()
            self._thread = Thread(target=self._run, name="portfolio-close-worker", daemon=True)
            self._thread.start()

    def stop(self):
        self._stopping.set()
        self._wake.set()
        self.market.stop()
        if self._thread:
            self._thread.join(timeout=2)

    def request_check(self) -> dict:
        if self._stopping.is_set():
            raise DomainError("worker_stopped")
        result = self.store.enqueue("manual", None, requested_at=self.clock().isoformat())
        self._wake.set()
        return result

    def _schedule(self, now):
        local = now.astimezone(SHANGHAI)
        latest = self.store.latest_check()
        if latest and latest["status"] in {"queued", "running"}:
            return
        if (
            local.weekday() >= 5
            or local.time() < CUTOFF
            or not self.store.get_settings()["automatic"]
            or not self.store.list_plans()
        ):
            return
        day = local.date().isoformat()
        if self.store.has_success(day):
            return
        attempts = self.store.automatic_attempts(day)
        if len(attempts) >= 3:
            return
        if attempts and now - datetime.fromisoformat(attempts[-1]["created_at"]) < timedelta(
            minutes=30
        ):
            return
        try:
            calendar = self.market.calendar()
            # Require calendar coverage before treating an absent weekday as a holiday.
            completed_date(now, calendar)
            if day not in calendar["dates"]:
                return
        except DomainError:
            # Record the unavailable calendar as a failed observation, not a healthy holiday.
            pass
        self.store.enqueue("automatic", day, len(attempts) + 1, requested_at=now.isoformat())

    def tick(self):
        with self._tick_lock:
            if self._stopping.is_set():
                return
            now = self.clock()
            self._schedule(now)
            check = self.store.claim()
            if check is None:
                return
            try:
                target = completed_date(now, self.market.calendar())
                if check["source"] == "automatic" and check["target_date"] != target:
                    raise DomainError("check_date_expired")
                self.store.set_target(check["id"], target)
                quotes = {}
                for plan in check["plans"]:
                    if self._stopping.is_set():
                        raise DomainError("interrupted")
                    if plan["symbol"] not in quotes:
                        quotes[plan["symbol"]] = self.market.quote(plan["instrument"], target)
                results = [evaluate(p, quotes[p["symbol"]], target) for p in check["plans"]]
                valid = sum(r["quality"] == "valid" for r in results)
                status = "completed" if valid == len(results) else "partial" if valid else "failed"
                if self._stopping.is_set():
                    raise DomainError("interrupted")
                self.store.complete(check["id"], results, status)
            except DomainError as error:
                self.store.fail(check["id"], error.code)
            except Exception:
                self.store.fail(check["id"], "check_failed")

    def _run(self):
        while not self._stopping.is_set():
            try:
                self.tick()
            except Exception:
                # Keep the scheduler alive without leaking portfolio/provider details.
                latest = self.store.latest_check()
                if latest and latest["status"] == "running":
                    self.store.fail(latest["id"], "check_failed")
            self._wake.wait(30)
            self._wake.clear()
