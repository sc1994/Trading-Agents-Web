"""Read only public rendered pages with an ephemeral, bounded headless browser."""

import re
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import quote

from parsel import Selector

from .china_news import SHANGHAI, NewsItem, _clean, _date, _url
from .config import get_config

_browser_lock = threading.Lock()
PAGES = {
    "cls": ("https://www.cls.cn/telegraph", 'a[href^="/detail/"]'),
    "eastmoney": ("https://so.eastmoney.com/news/s?keyword={keyword}", ".news_item"),
    "sina": ("https://finance.sina.com.cn/7x24/", ".bd_i[data-time]"),
    "wallstreetcn": ("https://wallstreetcn.com/live/global", ".live-item"),
}


def _parse_cls(document):
    text = " ".join(
        document.xpath("//body//text()[not(ancestor::script or ancestor::style)]").getall()
    )
    if not text:
        text = document.xpath("string(.)").get("")
    header = re.search(r"(\d{4})\.(\d{2})\.(\d{2})\D{0,30}(\d{2}:\d{2}:\d{2})", text)
    if not header:
        raise ValueError("CLS page has no verifiable calendar timestamp")
    day = datetime(*map(int, header.groups()[:3]), tzinfo=SHANGHAI)
    previous = datetime.strptime(header.group(4), "%H:%M:%S").time()
    items = []
    seen = set()
    for link in document.xpath(
        '//a[starts-with(@href, "/detail/") and contains(string(.), "评论")]'
    ):
        href = link.attrib["href"]
        if href in seen:
            continue
        # Ancestors are in document order; choose the smallest timed entry.
        ancestors = list(link.xpath("ancestor::*"))
        entry = next(
            (
                node
                for node in reversed(ancestors)
                if re.match(r"^\s*\d{2}:\d{2}:\d{2}", node.xpath("string(.)").get(""))
            ),
            None,
        )
        if entry is None:
            continue
        content = _clean(entry.css('div[style*="white-space: pre-wrap"]').get() or entry.get())
        stamp = re.match(r"(\d{2}:\d{2}:\d{2})", content)
        if not stamp:
            continue
        clock = datetime.strptime(stamp.group(1), "%H:%M:%S").time()
        if previous is not None and clock > previous:
            day -= timedelta(days=1)
        previous = clock
        published = day.replace(hour=clock.hour, minute=clock.minute, second=clock.second)
        # Reject conflicting wire dates; never invent an earlier year to make them fit.
        wire_date = re.search(r"财联社(\d{1,2})月(\d{1,2})日[电讯]", content)
        if wire_date:
            month, date = map(int, wire_date.groups())
            if (month, date) != (published.month, published.day):
                continue
        content = content[len(stamp.group(1)) :].strip()
        items.append(
            NewsItem(
                content[:140],
                content + " [Public page excerpt; may be truncated.]",
                published,
                "CLS (public browser page)",
                "https://www.cls.cn" + href,
            )
        )
        seen.add(href)
    return items


def parse_browser_html(source: str, html: str) -> list[NewsItem]:
    document = Selector(text=html)
    items = []
    if source == "cls":
        items = _parse_cls(document)
    elif source == "eastmoney":
        for node in document.css(".news_item"):
            stamp = _clean(node.css(".news_item_time").get())[:19]
            try:
                items.append(
                    NewsItem(
                        _clean(node.css(".news_item_t").get()),
                        _clean(node.css(".news_item_c").get()),
                        _date(stamp),
                        "Eastmoney (public browser page)",
                        _url(node.css(".news_item_t a::attr(href)").get()),
                    )
                )
            except (ValueError, TypeError):
                continue
    elif source == "sina":
        for node in document.css(".bd_i[data-time]"):
            try:
                day = datetime.strptime(node.attrib["data-time"], "%Y%m%d").strftime("%Y-%m-%d")
                clock = _clean(node.css(".bd_i_time_c").get())
                text = _clean(node.css(".bd_i_txt_c").get())
                items.append(
                    NewsItem(
                        text[:140],
                        text,
                        _date(f"{day} {clock}"),
                        "Sina Finance (public browser page)",
                        _url(node.css(".bd_i_txt_c a::attr(href)").get()),
                    )
                )
            except (ValueError, TypeError):
                continue
    elif source == "wallstreetcn":
        for node in document.css(".live-item"):
            try:
                stamp = node.css("time::attr(datetime)").get()
                hrefs = " ".join(node.css("a::attr(href)").getall())
                identifier = re.search(r"/livenews/(?:edit/)?(\d+)", hrefs)
                if identifier is None:
                    continue
                content = _clean(node.css(".live-item_html").get())
                title = _clean(node.css(".live-item_title").get()) or content[:140]
                items.append(
                    NewsItem(
                        title,
                        content,
                        _date(stamp),
                        "WallstreetCN (public browser page)",
                        "https://wallstreetcn.com/livenews/" + identifier.group(1),
                    )
                )
            except (ValueError, TypeError):
                continue
    else:
        raise ValueError("Unsupported domestic browser source")
    items = [item for item in items if item.title and item.url]
    if not items:
        raise ValueError(
            "No dated public articles; page may require login, verification or have changed"
        )
    return items


def fetch_browser_news(
    source: str, keyword: str = "", screenshot_path: str | None = None
) -> list[NewsItem]:
    """No persistent profiles, credentials, stealth plugins or CAPTCHA interaction."""
    if source not in PAGES:
        raise ValueError("Unsupported domestic browser source")
    from playwright.sync_api import sync_playwright

    timeout = max(1, min(60, get_config()["china_news_browser_timeout"]))
    deadline = time.monotonic() + timeout
    if not _browser_lock.acquire(timeout=timeout):
        raise TimeoutError("Domestic browser busy")
    browser = None
    try:

        def remaining():
            return max(1, int((deadline - time.monotonic()) * 1000))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, timeout=remaining())
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000},
                    accept_downloads=False,
                    service_workers="block",
                )
                page = context.new_page()
                url, selector = PAGES[source]
                response = page.goto(
                    url.format(keyword=quote(keyword, safe="")),
                    wait_until="domcontentloaded",
                    timeout=remaining(),
                )
                if response is None or response.status >= 400:
                    raise ValueError("Public page unavailable")
                page.locator(selector).first.wait_for(state="attached", timeout=remaining())
                # Only expand already-public excerpts. Never click login or verification controls.
                if source == "cls":
                    controls = page.locator(".telegraph-content-br-close")
                    for _ in range(min(5, controls.count())):
                        if time.monotonic() >= deadline:
                            break
                        controls.nth(0).click(timeout=remaining())
                rows = parse_browser_html(source, page.content())
                if screenshot_path:
                    page.evaluate("() => window.scrollTo(0, 0)")
                    page.screenshot(path=screenshot_path, full_page=False, timeout=remaining())
                return rows
            finally:
                browser.close()
    finally:
        _browser_lock.release()
