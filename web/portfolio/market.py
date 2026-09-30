"""Verified A-share identities and conservative cached market observations."""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock, RLock, Thread

from web.portfolio.domain import DomainError, iso_date, positive_decimal
from web.search import search_symbols
from web.store import _now

EXCHANGES = {"SH": "SS", "SZ": "SZ", "BJ": "BJ"}
CATALOG_FRESH = timedelta(days=1)
CATALOG_USABLE = timedelta(days=7)
CATALOG_RETRY = timedelta(minutes=5)
logger = logging.getLogger(__name__)


class BoundedFetch:
    def __init__(self, command: list[str] | None = None):
        self.command = command
        self._lock = RLock()
        self._children = set()
        self._stopped = False

    def __call__(self, operation: str, payload: dict, timeout: float) -> dict:
        with self._lock:
            if self._stopped:
                raise DomainError("market_stopped")
            command = self.command or [sys.executable, "-m", "web.portfolio.fetch", operation]
            child = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            self._children.add(child)
        try:
            output, _ = child.communicate(json.dumps(payload), timeout=timeout)
            if child.returncode or len(output.encode("utf-8")) > 4 * 1024 * 1024:
                raise DomainError("market_unavailable")
            value = json.loads(output)
            if not isinstance(value, dict):
                raise DomainError("market_unavailable")
            if value.get("error_code"):
                raise DomainError(
                    value["error_code"]
                    if value["error_code"] in {"market_dependency_missing", "missing_quote"}
                    else "market_unavailable"
                )
            return value
        except subprocess.TimeoutExpired:
            self._reap(child)
            raise DomainError("market_timeout") from None
        except DomainError:
            raise
        except (ValueError, OSError):
            raise DomainError("market_unavailable") from None
        finally:
            if child.poll() is None:
                self._reap(child)
            for pipe in (child.stdin, child.stdout):
                if pipe and not pipe.closed:
                    pipe.close()
            with self._lock:
                self._children.discard(child)

    @staticmethod
    def _reap(child):
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=0.5)

    def stop(self):
        with self._lock:
            self._stopped = True
            children = list(self._children)
        for child in children:
            self._reap(child)


class AShareMarket:
    def __init__(self, data_dir: Path, call=None, clock=None):
        self.directory = Path(data_dir) / "portfolio-market"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.call = call or BoundedFetch()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._calendar_lock = Lock()
        self._catalog_locks = {exchange: Lock() for exchange in EXCHANGES}
        self._attempts, self._errors = {}, {}
        self._refreshing = set()
        self._stopping = Event()
        self._threads = []
        self._migrate_catalog()

    def _read(self, name: str, max_age=CATALOG_FRESH) -> dict | None:
        try:
            value = json.loads((self.directory / f"{name}.json").read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(value["fetched_at"])
            if not timedelta(0) <= self.clock() - fetched < max_age:
                return None
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _publish(self, name: str, value: dict):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory, prefix=f".{name}-", delete=False
            ) as output:
                temporary = Path(output.name)
                json.dump(value, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.directory / f"{name}.json")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_catalog(raw: dict, exchange: str, fetched_at: str) -> dict:
        items = {}
        for item in raw["instruments"]:
            symbol = item["symbol"]
            if (
                item.get("exchange") != exchange
                or not re.fullmatch(r"\d{6}\." + EXCHANGES[exchange], symbol)
                or item.get("currency") != "CNY"
                or item.get("security_type") != "A_SHARE"
                or not isinstance(item.get("name"), str)
                or not item["name"].strip()
                or symbol in items
            ):
                raise ValueError("invalid identity")
            # Only publish trusted fields, never provider diagnostics or arbitrary URLs.
            items[symbol] = {
                "symbol": symbol,
                "name": item["name"].strip(),
                "exchange": exchange,
                "currency": "CNY",
                "security_type": "A_SHARE",
                "verified_at": fetched_at,
            }
        if not items:
            raise ValueError("empty catalog")
        return {
            "instruments": list(items.values()),
            "fetched_at": fetched_at,
            "source": "akshare_exchange_catalog",
        }

    def _cached_catalog(self, exchange, max_age=CATALOG_USABLE):
        value = self._read(f"catalog-{exchange.lower()}", max_age)
        if value:
            try:
                return self._validate_catalog(value, exchange, value["fetched_at"])
            except (KeyError, ValueError, TypeError):
                pass
        return None

    def _migrate_catalog(self):
        legacy = self._read("catalog", CATALOG_USABLE)
        if not legacy:
            return
        for exchange in EXCHANGES:
            name = f"catalog-{exchange.lower()}"
            if (self.directory / f"{name}.json").exists():
                continue
            try:
                raw = {
                    "instruments": [
                        i for i in legacy["instruments"] if i.get("exchange") == exchange
                    ]
                }
                value = self._validate_catalog(raw, exchange, legacy["fetched_at"])
                self._publish(name, value)
            except (OSError, KeyError, ValueError, TypeError, AttributeError):
                logger.warning("portfolio catalog migration failed exchange=%s", exchange)

    def refresh_catalog(self, exchange: str | None = None) -> dict:
        if exchange is None:
            for name in EXCHANGES:
                self.refresh_catalog(name)
            return self._catalog()
        if exchange not in EXCHANGES:
            raise DomainError("unsupported_market")
        # Independent single-flight locks never block cache-only readers or other markets.
        with self._catalog_locks[exchange]:
            now = self.clock()
            cached = self._cached_catalog(exchange)
            if cached and now - datetime.fromisoformat(cached["fetched_at"]) < CATALOG_FRESH:
                return cached
            with self._lock:
                previous = self._attempts.get(exchange)
                if self._stopping.is_set() or (previous and now - previous < CATALOG_RETRY):
                    return cached or {}
                self._attempts[exchange] = now
                self._refreshing.add(exchange)
            error = None
            try:
                raw = self.call("catalog", {"exchange": exchange}, 20)
                try:
                    value = self._validate_catalog(raw, exchange, self.clock().isoformat())
                except (KeyError, ValueError, TypeError):
                    raise DomainError("catalog_invalid") from None
                try:
                    self._publish(f"catalog-{exchange.lower()}", value)
                except OSError:
                    raise DomainError("cache_write_failed") from None
                return value
            except DomainError as failure:
                error = (
                    failure.code
                    if failure.code
                    in {
                        "market_timeout",
                        "market_dependency_missing",
                        "catalog_invalid",
                        "cache_write_failed",
                        "market_stopped",
                    }
                    else "market_unavailable"
                )
                return cached or {}
            except Exception:
                error = "market_unavailable"
                return cached or {}
            finally:
                with self._lock:
                    self._refreshing.discard(exchange)
                    self._errors[exchange] = error
                if error and not self._stopping.is_set():
                    logger.warning(
                        "portfolio catalog refresh failed exchange=%s code=%s", exchange, error
                    )

    def _catalog(self):
        items, statuses = [], []
        for exchange in EXCHANGES:
            cached = self._cached_catalog(exchange)
            with self._lock:
                refreshing = exchange in self._refreshing or bool(
                    self._threads
                    and not self._stopping.is_set()
                    and not cached
                    and exchange not in self._attempts
                )
                error = self._errors.get(exchange)
            archived = cached or self._cached_catalog(exchange, timedelta(days=36500))
            fetched = archived["fetched_at"] if archived else None
            state = (
                "fresh"
                if cached and self.clock() - datetime.fromisoformat(fetched) < CATALOG_FRESH
                else "stale"
                if cached
                else "expired"
                if archived
                else "loading"
                if refreshing
                else "unavailable"
            )
            statuses.append(
                {
                    "exchange": exchange,
                    "state": state,
                    "fetched_at": fetched,
                    "refreshing": refreshing,
                    "error_code": error,
                }
            )
            if cached:
                items.extend(
                    {**item, "catalog_state": state, "catalog_fetched_at": fetched}
                    for item in cached["instruments"]
                )
        return {"instruments": items, "catalog_status": statuses}

    def start(self):
        with self._lock:
            if self._threads or self._stopping.is_set():
                return
            self._threads = [
                Thread(
                    target=self._refresh_loop, args=(e,), name=f"portfolio-catalog-{e}", daemon=True
                )
                for e in EXCHANGES
            ]
            for thread in self._threads:
                thread.start()

    def _refresh_loop(self, exchange):
        while not self._stopping.is_set():
            self.refresh_catalog(exchange)
            self._stopping.wait(30)

    def resolve(self, symbol: str) -> dict:
        if not isinstance(symbol, str):
            raise DomainError("unsupported_market", "symbol")
        symbol = symbol.strip().upper()
        if not re.fullmatch(r"\d{6}(?:\.(?:SS|SZ|BJ))?", symbol):
            raise DomainError("unsupported_market", "symbol")
        catalog = self._catalog()
        items = catalog["instruments"]
        matches = [
            item
            for item in items
            if item["symbol"] == symbol or (len(symbol) == 6 and item["symbol"][:6] == symbol)
        ]
        if len(matches) != 1:
            relevant = [
                s
                for s in catalog["catalog_status"]
                if len(symbol) == 6 or EXCHANGES[s["exchange"]] == symbol[7:]
            ]
            if any(s["state"] in {"loading", "expired", "unavailable"} for s in relevant):
                raise DomainError(
                    "catalog_loading"
                    if any(s["refreshing"] for s in relevant)
                    else "catalog_unavailable",
                    "symbol",
                )
            raise DomainError("instrument_unverified", "symbol")
        return matches[0].copy()

    def search(self, query: str) -> dict:
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 64:
            raise DomainError("invalid_query", "q")
        snapshot = self._catalog()
        catalog, statuses = snapshot["instruments"], snapshot["catalog_status"]
        needle = query.strip().casefold()
        local = [
            item
            for item in catalog
            if needle in item["symbol"].casefold() or needle in item["name"].casefold()
        ]
        if local:
            rows = [{**item, "supported": True, "support_code": None} for item in local[:8]]
            return {"results": rows, "unavailable": False, "catalog_status": statuses}
        lookup = search_symbols(query)
        verified = {item["symbol"]: item for item in catalog}
        rows = []
        for item in lookup["results"]:
            symbol = item["symbol"].upper()
            supported = symbol in verified
            status = next((s for s in statuses if EXCHANGES[s["exchange"]] == symbol[7:]), None)
            code = (
                None
                if supported
                else "unsupported_market"
                if not re.fullmatch(r"\d{6}\.(?:SS|SZ|BJ)", symbol)
                else "instrument_unverified"
                if status and status["state"] in {"fresh", "stale"}
                else "catalog_loading"
                if status and status["refreshing"]
                else "catalog_unavailable"
            )
            rows.append(
                {**item, **verified.get(symbol, {}), "supported": supported, "support_code": code}
            )
        return {
            "results": rows,
            "unavailable": lookup["unavailable"] or not catalog,
            "catalog_status": statuses,
        }

    def calendar(self) -> dict:
        with self._calendar_lock:
            cached = self._read("calendar")
            if cached:
                return cached
            try:
                raw = self.call("calendar", {}, 20)
                dates = sorted({iso_date(value, "calendar") for value in raw["dates"]})
                if len(dates) < 2:
                    raise ValueError("incomplete calendar")
                value = {
                    "dates": dates,
                    "covered_from": dates[0],
                    "covered_until": dates[-1],
                    "source": raw.get("source", "akshare_sina"),
                    "fetched_at": _now(),
                }
                self._publish("calendar", value)
                return value
            except Exception:
                raise DomainError("calendar_unavailable") from None

    def quote(self, instrument: dict, target_date: str) -> dict:
        base = {
            "symbol": instrument["symbol"],
            "price_date": None,
            "close": None,
            "currency": "CNY",
            "source": "akshare_eastmoney_unadjusted",
            "fetched_at": _now(),
        }
        try:
            raw = self.call(
                "quote", {"symbol": instrument["symbol"], "target_date": target_date}, 20
            )
            if raw.get("error_code"):
                raise DomainError("missing_quote")
            if raw.get("symbol") != instrument["symbol"] or raw.get("currency") != "CNY":
                raise DomainError("invalid_quote")
            positive_decimal(raw.get("close"), "close")
            iso_date(raw.get("price_date"), "price_date")
            if raw["price_date"] != target_date:
                return {**base, **raw, "error_code": "stale_quote"}
            if "volume" in raw and (
                not str(raw["volume"]).replace(".", "", 1).isdigit() or float(raw["volume"]) <= 0
            ):
                raise DomainError("missing_quote")
            return {**base, **raw, "error_code": None}
        except DomainError as error:
            code = (
                "invalid_quote" if error.code in {"invalid_decimal", "invalid_date"} else error.code
            )
            return {**base, "error_code": code}
        except Exception:
            return {**base, "error_code": "market_unavailable"}

    def stop(self):
        self._stopping.set()
        if hasattr(self.call, "stop"):
            self.call.stop()
        for thread in self._threads:
            thread.join(timeout=1)
