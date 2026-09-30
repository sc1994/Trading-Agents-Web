"""Bounded public Chinese news retrieval; no credentials or anti-bot bypasses."""

import json
import logging
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests
from parsel import Selector

from .config import get_config

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
HEADERS = {
    "User-Agent": "TradingAgents domestic news reader",
    "Referer": "https://www.cninfo.com.cn/",
}
_cache = OrderedDict()
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class NewsItem:
    title: str
    content: str
    published_at: datetime
    source: str
    url: str
    company_name: str = ""


def china_stock_code(ticker: str) -> str | None:
    """Recognize mainland equity symbols, not HK equities or caret-prefixed indices."""
    match = re.fullmatch(r"(?:(SH|SZ|BJ))?(\d{6})(?:\.(SS|SH|SZ|BJ))?", ticker.strip().upper())
    if not match:
        return None
    prefix, code, suffix = match.groups()
    market = suffix or prefix
    if market in {"SS", "SH"} and not code.startswith("6"):
        return None
    if market == "SZ" and not code.startswith(("0", "30")):
        return None
    if market == "BJ" and not code.startswith(("4", "8", "9")):
        return None
    return code if code.startswith(("0", "30", "4", "6", "8", "9")) else None


def _clean(value) -> str:
    return " ".join(Selector(text=str(value or "")).xpath("string(.)").get("").split())


def _date(value) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, SHANGHAI)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def _window(start_date: str, end_date: str):
    start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=SHANGHAI)
    end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=SHANGHAI) + timedelta(days=1)
    if start >= end:
        raise ValueError("start_date must be on or before end_date")
    return start, end


def _url(value: str) -> str:
    value = str(value or "").replace("http://", "https://", 1)
    return value if urlparse(value).scheme == "https" else ""


def render_news(items, start_date: str, end_date: str, limit: int = 20) -> str:
    start, end = _window(start_date, end_date)
    seen = set()
    blocks = []
    for item in sorted(items, key=lambda item: item.published_at, reverse=True):
        stamp = item.published_at.astimezone(SHANGHAI)
        if not start <= stamp < end or not item.title or not item.url:
            continue
        key = (item.title, stamp.date())
        if key in seen:
            continue
        seen.add(key)
        blocks.append(
            f"### {item.title}\nPublished: {stamp.isoformat()}\n"
            f"Source: {item.source}\n{item.content[:3000]}\nLink: {item.url}\n"
        )
        if len(blocks) >= max(1, limit):
            break
    return "\n".join(blocks) or (
        "NO_DATA_AVAILABLE: No dated relevant items in the requested window; "
        "this is not evidence of neutral sentiment."
    )


def _get(url, **kwargs):
    response = requests.get(
        url, headers=HEADERS, timeout=get_config()["china_news_timeout"], **kwargs
    )
    response.raise_for_status()
    return response


def parse_eastmoney(text: str) -> list[NewsItem]:
    """Parse JSON/JSONP by its envelope, never by stripping a character set."""
    text = text.strip()
    if not text.startswith("{"):
        match = re.fullmatch(r"[\w.]+\((.*)\);?", text, re.S)
        if not match:
            raise ValueError("Unexpected Eastmoney JSONP envelope")
        text = match.group(1)
    data = json.loads(text)
    rows = data.get("result", {}).get("cmsArticleWebOld")
    if not isinstance(rows, list):
        raise ValueError("Eastmoney search did not return article records")
    items = []
    for row in rows:
        try:
            items.append(
                NewsItem(
                    _clean(row["title"]),
                    _clean(row.get("content")),
                    _date(row["date"]),
                    f"Eastmoney / {_clean(row.get('mediaName'))}",
                    _url(row.get("url") or f"https://finance.eastmoney.com/a/{row['code']}.html"),
                )
            )
        except (ValueError, KeyError, TypeError):
            logger.debug("Skipping malformed Eastmoney article")
    return items


def _fetch_eastmoney(keyword: str, pages: int) -> list[NewsItem]:
    items = []
    for page in range(1, pages + 1):
        query = {
            "uid": "",
            "keyword": keyword,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "default",
                    "sort": "time",
                    "pageIndex": page,
                    "pageSize": 100,
                    "preTag": "",
                    "postTag": "",
                }
            },
        }
        response = _get(
            "https://search-api-web.eastmoney.com/search/jsonp",
            params={
                "cb": "domestic_news",
                "param": json.dumps(query, ensure_ascii=False),
            },
        )
        rows = parse_eastmoney(response.text)
        items.extend(rows)
        if len(rows) < 100:
            break
    return items


def _fetch_cninfo(code: str, start_date: str, end_date: str, pages: int) -> list[NewsItem]:
    items = []
    column = "sse" if code.startswith("6") else "szse"
    if code.startswith(("4", "8", "9")):
        column = "bj"
    for page in range(1, pages + 1):
        response = requests.post(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data={
                "pageNum": page,
                "pageSize": 30,
                "column": column,
                "tabName": "fulltext",
                "stock": "",
                "searchkey": code,
                "seDate": f"{start_date}~{end_date}",
                "sortName": "time",
                "sortType": "desc",
                "isHLtitle": "true",
            },
            headers=HEADERS,
            timeout=get_config()["china_news_timeout"],
        )
        response.raise_for_status()
        data = response.json()
        if "announcements" not in data:
            raise ValueError("CNINFO did not return announcement records")
        for row in data.get("announcements") or []:
            if row.get("secCode") != code:
                continue
            try:
                path = row["adjunctUrl"]
                if not path.startswith("finalpage/") or ".." in path:
                    continue
                items.append(
                    NewsItem(
                        _clean(row["announcementTitle"]),
                        "Official announcement metadata only; linked PDF has not been read. "
                        "The supplied timestamp represents an announcement date, not verified publication time.",
                        _date(row["announcementTime"] / 1000),
                        "CNINFO",
                        f"https://static.cninfo.com.cn/{path}",
                        _clean(row.get("secName")),
                    )
                )
            except (ValueError, KeyError, TypeError):
                logger.debug("Skipping malformed CNINFO announcement")
        if not data.get("hasMore"):
            break
    return items


def _fetch_sina(pages: int) -> list[NewsItem]:
    items = []
    for page in range(1, pages + 1):
        data = _get(
            "https://zhibo.sina.com.cn/api/zhibo/feed",
            params={
                "zhibo_id": 152,
                "page": page,
                "page_size": 30,
            },
        ).json()
        rows = data["result"]["data"]["feed"]["list"]
        for row in rows:
            try:
                text = _clean(row["rich_text"])
                items.append(
                    NewsItem(
                        text[:140],
                        text,
                        _date(row["create_time"]),
                        "Sina Finance",
                        _url(row.get("docurl")),
                    )
                )
            except (ValueError, KeyError, TypeError):
                logger.debug("Skipping malformed Sina item")
        if len(rows) < 30:
            break
    return items


def _fetch_wallstreetcn(pages: int) -> list[NewsItem]:
    items = []
    cursor = None
    for _ in range(pages):
        params = {"channel": "global-channel", "limit": 30}
        if cursor:
            params["cursor"] = cursor
        data = _get("https://api-one.wallstcn.com/apiv1/content/lives", params=params).json()
        rows = data["data"]["items"]
        for row in rows:
            try:
                text = _clean(row.get("content_text") or row.get("content"))
                items.append(
                    NewsItem(
                        _clean(row.get("title")) or text[:140],
                        text,
                        _date(row["display_time"]),
                        "WallstreetCN",
                        _url(row.get("uri")),
                    )
                )
            except (ValueError, KeyError, TypeError):
                logger.debug("Skipping malformed WallstreetCN item")
        cursor = data["data"].get("next_cursor")
        if not cursor or not rows:
            break
    return items


def fetch_browser_news(source: str, keyword: str = "") -> list[NewsItem]:
    from .china_news_browser import fetch_browser_news as fetch

    return fetch(source, keyword)


def _source(label, fetch, browser_source=None, keyword=""):
    try:
        return fetch(), ""
    except Exception as exc:
        logger.warning("Domestic news source %s failed: %s", label, type(exc).__name__)
        if browser_source and get_config()["china_news_browser_fallback"]:
            try:
                return fetch_browser_news(
                    browser_source, keyword
                ), f"{label}: browser fallback used."
            except Exception as browser_exc:
                logger.warning("Browser fallback %s failed: %s", label, type(browser_exc).__name__)
        return (
            [],
            f"DATA_UNAVAILABLE: {label} fetch failed; do not infer sentiment from missing data.",
        )


def _cached(key, build):
    ttl = max(0, get_config()["china_news_cache_ttl"])
    with _cache_lock:
        cached = _cache.get(key)
        if ttl and cached and time.monotonic() - cached[0] < ttl:
            return cached[1]
    result = build()
    if ttl and "DATA_UNAVAILABLE" not in result and "Published:" in result:
        with _cache_lock:
            _cache[key] = (time.monotonic(), result)
            _cache.move_to_end(key)
            while len(_cache) > 64:
                _cache.popitem(last=False)
    return result


def get_china_stock_news(ticker: str, start_date: str, end_date: str) -> str:
    _window(start_date, end_date)
    code = china_stock_code(ticker)
    if not code:
        raise ValueError("Domestic stock news requires a mainland equity ticker")
    settings = get_config()
    pages = min(3, max(1, settings["china_news_max_pages"]))

    def build():
        announcements, ann_status = _source(
            "CNINFO", lambda: _fetch_cninfo(code, start_date, end_date, pages)
        )
        keywords = [code]
        if announcements and announcements[0].company_name:
            keywords.append(announcements[0].company_name)
        news, statuses = [], [ann_status]
        for keyword in keywords:
            rows, status = _source(
                "Eastmoney", lambda k=keyword: _fetch_eastmoney(k, pages), "eastmoney", keyword
            )
            news.extend(rows)
            statuses.append(status)
        return (
            f"## {ticker}: domestic news and official announcements ({start_date} to {end_date})\n"
            "News search matches may only mention the company; assess relevance. "
            "These are event/news inputs, not retail community sentiment. "
            f"Public retrieval is capped at {pages} pages per query; historical coverage is not guaranteed.\n\n"
            "### Company news\n"
            + render_news(news, start_date, end_date, settings["news_article_limit"])
            + "\n\n### Official announcements\n"
            + render_news(announcements, start_date, end_date, settings["news_article_limit"])
            + "\n\n"
            + "\n".join(status for status in statuses if status)
        )

    return _cached(
        (
            "stock",
            ticker,
            start_date,
            end_date,
            pages,
            settings["news_article_limit"],
            settings["china_news_browser_fallback"],
        ),
        build,
    )


def get_china_market_news(
    curr_date: str, look_back_days: int | None = None, limit: int | None = None
) -> str:
    settings = get_config()
    days = settings["global_news_lookback_days"] if look_back_days is None else look_back_days
    limit = settings["global_news_article_limit"] if limit is None else limit
    if days < 0 or limit < 1:
        raise ValueError("look_back_days must be nonnegative and limit positive")
    start_date = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=days)).strftime(
        "%Y-%m-%d"
    )
    _window(start_date, curr_date)
    pages = min(3, max(1, settings["china_news_max_pages"]))

    def build():
        items, statuses = [], []
        for label, fetch, browser in [
            ("Sina Finance", lambda: _fetch_sina(pages), "sina"),
            ("WallstreetCN", lambda: _fetch_wallstreetcn(pages), "wallstreetcn"),
        ]:
            rows, status = _source(label, fetch, browser)
            items.extend(rows)
            statuses.append(status)
        if settings["china_news_browser_fallback"]:
            from .china_news_browser import parse_browser_html

            rows, status = _source(
                "CLS",
                lambda: parse_browser_html("cls", _get("https://www.cls.cn/telegraph").text),
                "cls",
            )
            items.extend(rows)
            statuses.append(status)
        return (
            f"## China market news ({start_date} to {curr_date})\n"
            "Latest public feeds only; this is not a complete historical news archive.\n\n"
            + render_news(items, start_date, curr_date, limit)
            + "\n\n"
            + "\n".join(status for status in statuses if status)
        )

    return _cached(
        ("market", curr_date, days, limit, pages, settings["china_news_browser_fallback"]), build
    )
