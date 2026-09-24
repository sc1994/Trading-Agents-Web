"""Bounded instrument search with a short-lived, process-local query cache."""

import time
from collections.abc import Callable
from pathlib import Path

import yfinance as yf

from web.catalog import search_catalog

_CACHE_SECONDS = 600
_MAX_RESULTS = 8
_CACHE_MAX_ENTRIES = 256
_cache: dict[tuple[Callable, str], tuple[float, dict]] = {}


def _yahoo_lookup(query: str, **kwargs) -> list[dict]:
    return yf.Search(query, max_results=8, news_count=0, lists_count=0,
                     recommended=0, timeout=5).quotes


def search_symbols(query: str, lookup: Callable | None = None, catalog_path: Path | None = None) -> dict:
    """Return public quote fields, preserving Yahoo relevance except exact ticker matches."""
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 64:
        raise ValueError("query must contain between 2 and 64 characters")

    query = query.strip()
    local = search_catalog(catalog_path, query) if catalog_path is not None else []
    # Cached Yahoo responses must not hide a newly published local snapshot.
    if local:
        return {"results": local, "unavailable": False}
    lookup = lookup or _yahoo_lookup
    now = time.monotonic()
    key = (lookup, query.casefold())
    try:
        cached = _cache.get(key)
    except TypeError:
        cached = None  # An injected unhashable callable can still be used without caching.
    if cached is not None and now - cached[0] < _CACHE_SECONDS:
        return {"results": [item.copy() for item in cached[1]["results"]],
                "unavailable": cached[1]["unavailable"]}

    try:
        quotes = lookup(query)
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
