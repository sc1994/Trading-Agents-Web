"""Bounded instrument search with a short-lived, process-local query cache."""

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import yfinance as yf

from web.catalog import search_catalog

_CACHE_SECONDS = 600
_MAX_RESULTS = 8
_CACHE_MAX_ENTRIES = 256
_cache: dict[tuple[Callable, str], tuple[float, dict]] = {}
_CJK = re.compile(r"[\u3400-\u9fff]")
_EASTMONEY_SEARCH_URL = "https://searchapi.eastmoney.com/api/suggest/get"
_EASTMONEY_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"


def _yahoo_lookup(query: str, **kwargs) -> list[dict]:
    return yf.Search(query, max_results=8, news_count=0, lists_count=0,
                     recommended=0, timeout=5).quotes


def _eastmoney_lookup(query: str, request: Callable) -> list[dict]:
    params = {
        "input": query,
        "type": "14",
        "count": str(_MAX_RESULTS),
        "token": _EASTMONEY_TOKEN,
    }
    url = f"{_EASTMONEY_SEARCH_URL}?{urlencode(params)}"
    with request(url, timeout=5) as response:
        rows = json.load(response).get("QuotationCodeTable", {}).get("Data", [])

    quotes = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        code, classify = row.get("Code"), row.get("Classify")
        if not isinstance(code, str):
            continue
        security_type = str(row.get("TypeUS"))
        if (
            classify == "UsStock"
            and security_type in {"1", "3", "10"}
            and re.fullmatch(r"[A-Za-z0-9._^=-]{1,32}", code)
        ):
            symbol = code.upper().replace("_", "-")
            exchange = str(row.get("JYS") or "US")
        elif classify == "HK" and security_type == "3" and re.fullmatch(r"0\d{4}", code):
            symbol, exchange = f"{code[1:]}.HK", "HKEX"
        elif classify == "AStock" and re.fullmatch(r"\d{6}", code):
            market = {"0": ("SZ", "SZ"), "1": ("SS", "SH")}.get(str(row.get("MktNum")))
            if market is None:
                continue
            suffix, exchange = market
            symbol = f"{code}.{suffix}"
        else:
            continue
        quotes.append({
            "symbol": symbol,
            "shortname": str(row.get("Name") or ""),
            "exchDisp": exchange,
            "quoteType": "EQUITY",
        })
    return quotes


def search_symbols(
    query: str,
    lookup: Callable | None = None,
    catalog_path: Path | None = None,
    request: Callable | None = None,
) -> dict:
    """Return public quote fields, preserving Yahoo relevance except exact ticker matches."""
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 64:
        raise ValueError("query must contain between 2 and 64 characters")

    query = query.strip()
    local = search_catalog(catalog_path, query) if catalog_path is not None else []
    # Cached Yahoo responses must not hide a newly published local snapshot.
    if local:
        return {"results": local, "unavailable": False}
    chinese_lookup = lookup is None and _CJK.search(query) is not None
    request = request or urlopen
    lookup = lookup or (_eastmoney_lookup if chinese_lookup else _yahoo_lookup)
    now = time.monotonic()
    key = (request if chinese_lookup else lookup, query.casefold())
    try:
        cached = _cache.get(key)
    except TypeError:
        cached = None  # An injected unhashable callable can still be used without caching.
    if cached is not None and now - cached[0] < _CACHE_SECONDS:
        return {"results": [item.copy() for item in cached[1]["results"]],
                "unavailable": cached[1]["unavailable"]}

    try:
        quotes = lookup(query, request) if chinese_lookup else lookup(query)
        results = []
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            symbol = quote.get("symbol")
            if not isinstance(symbol, str) or not symbol.strip():
                continue
            results.append({
                "symbol": symbol.strip(),
                "name": str(quote.get("shortname") or quote.get("longname") or ""),
                "exchange": str(quote.get("exchDisp") or ""),
                "type": str(quote.get("quoteType") or ""),
            })
        results.sort(key=lambda item: item["symbol"].casefold() != query.casefold())
        response = {"results": results[:_MAX_RESULTS], "unavailable": False}
    except Exception:
        # Search is advisory; outages must not prevent manually entering a valid symbol.
        response = {"results": [], "unavailable": True}

    try:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            _cache.clear()
        _cache[key] = (now, response)
    except TypeError:
        pass
    return {"results": [item.copy() for item in response["results"]],
            "unavailable": response["unavailable"]}
