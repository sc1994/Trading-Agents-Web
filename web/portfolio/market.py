"""Verified A-share identities and conservative cached market observations."""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from web.portfolio.domain import DomainError, iso_date, positive_decimal
from web.search import search_symbols
from web.store import _now


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
    def __init__(self, data_dir: Path, call=None):
        self.directory = Path(data_dir) / "portfolio-market"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.call = call or BoundedFetch()
        self._lock = RLock()

    def _read(self, name: str) -> dict | None:
        try:
            value = json.loads((self.directory / f"{name}.json").read_text(encoding="utf-8"))
            fetched = datetime.fromisoformat(value["fetched_at"])
            if not 0 <= (datetime.now(timezone.utc) - fetched).total_seconds() < 86400:
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

    def refresh_catalog(self) -> dict:
        try:
            raw = self.call("catalog", {}, 20)
            items, now = {}, _now()
            for item in raw["instruments"]:
                symbol, exchange = item["symbol"], item["exchange"]
                suffix = {"SH": "SS", "SZ": "SZ", "BJ": "BJ"}.get(exchange)
                if (
                    not suffix
                    or not re.fullmatch(r"\d{6}\." + suffix, symbol)
                    or item.get("currency") != "CNY"
                    or item.get("security_type") != "A_SHARE"
                    or not isinstance(item.get("name"), str)
                    or not item["name"].strip()
                ):
                    raise ValueError("invalid identity")
                items[symbol] = {**item, "verified_at": now}
            if {item["exchange"] for item in items.values()} != {"SH", "SZ", "BJ"}:
                raise ValueError("partial catalog")
            value = {
                "instruments": list(items.values()),
                "fetched_at": now,
                "source": raw.get("source", "akshare_exchange_catalog"),
            }
            self._publish("catalog", value)
            return value
        except Exception:
            raise DomainError("catalog_unavailable", "symbol") from None

    def _catalog(self):
        with self._lock:
            return self._read("catalog") or self.refresh_catalog()

    def resolve(self, symbol: str) -> dict:
        if not isinstance(symbol, str):
            raise DomainError("unsupported_market", "symbol")
        symbol = symbol.strip().upper()
        if not re.fullmatch(r"\d{6}(?:\.(?:SS|SZ|BJ))?", symbol):
            raise DomainError("unsupported_market", "symbol")
        items = self._catalog()["instruments"]
        matches = [
            item
            for item in items
            if item["symbol"] == symbol or (len(symbol) == 6 and item["symbol"][:6] == symbol)
        ]
        if len(matches) != 1:
            raise DomainError("instrument_unverified", "symbol")
        return matches[0].copy()

    def search(self, query: str) -> dict:
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 64:
            raise DomainError("invalid_query", "q")
        available = True
        try:
            catalog = self._catalog()["instruments"]
        except DomainError:
            catalog, available = [], False
        needle = query.strip().casefold()
        local = [
            item
            for item in catalog
            if needle in item["symbol"].casefold() or needle in item["name"].casefold()
        ]
        if local:
            rows = [{**item, "supported": True, "support_code": None} for item in local[:8]]
            return {"results": rows, "unavailable": False}
        lookup = search_symbols(query)
        verified = {item["symbol"]: item for item in catalog}
        rows = []
        for item in lookup["results"]:
            symbol = item["symbol"].upper()
            supported = symbol in verified
            code = (
                None
                if supported
                else "unsupported_market"
                if not re.fullmatch(r"\d{6}\.(?:SS|SZ|BJ)", symbol)
                else "instrument_unverified"
                if available
                else "catalog_unavailable"
            )
            rows.append(
                {**item, **verified.get(symbol, {}), "supported": supported, "support_code": code}
            )
        return {"results": rows, "unavailable": lookup["unavailable"] or not available}

    def calendar(self) -> dict:
        with self._lock:
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
        if hasattr(self.call, "stop"):
            self.call.stop()
