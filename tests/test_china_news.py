"""Domestic news must be dated, attributable and market-specific."""

import copy
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from tradingagents.dataflows import config as config_module
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.fixture(autouse=True)
def config(monkeypatch):
    settings = copy.deepcopy(DEFAULT_CONFIG)
    settings.update(china_news_browser_fallback=False, china_news_cache_ttl=0)
    monkeypatch.setattr(config_module, "_config", settings)
    return settings


def china():
    from tradingagents.dataflows import china_news

    return china_news


@pytest.mark.parametrize(
    "ticker,code",
    [
        ("600519.SS", "600519"),
        ("600519.SH", "600519"),
        ("300750.SZ", "300750"),
        ("920001.BJ", "920001"),
        ("sh600519", "600519"),
        ("600519", "600519"),
        ("AAPL", None),
        ("0700.HK", None),
        ("^000001.SS", None),
        ("000001.SS", None),
        ("399001.SZ", None),
        ("510300.SS", None),
        ("sh000001", None),
    ],
)
def test_recognizes_only_mainland_stock_symbols(ticker, code):
    assert china().china_stock_code(ticker) == code


def item(title="Inside", date="2026-09-30T23:59:59+08:00", url="https://example.com/a"):
    return china().NewsItem(title, "Evidence", datetime.fromisoformat(date), "Fixture", url)


def test_render_filters_by_shanghai_day_deduplicates_and_retains_provenance():
    out = china().render_news(
        [
            item(),
            item(),
            item("Future", "2026-10-01T00:00:00+08:00"),
            item("UTC inside", "2026-09-29T17:00:00+00:00", "https://example.com/b"),
            item("Too old", "2026-09-29T15:59:59+00:00"),
        ],
        "2026-09-30",
        "2026-09-30",
        limit=10,
    )
    assert out.count("### Inside") == 1
    assert "UTC inside" in out
    assert "Future" not in out and "Too old" not in out
    assert "Fixture" in out and "https://example.com/a" in out
    assert "2026-09-30T23:59:59+08:00" in out


def test_invalid_window_rejected_before_fetch(monkeypatch):
    module = china()
    monkeypatch.setattr(module, "_fetch_eastmoney", lambda *a: pytest.fail("network"))
    with pytest.raises(ValueError):
        module.get_china_stock_news("600519.SS", "2026-10-01", "2026-09-30")


def test_eastmoney_jsonp_is_parsed_without_losing_boundary_characters(monkeypatch):
    module = china()
    response = MagicMock()
    response.text = 'domestic_news({"code":0,"result":{"cmsArticleWebOld":[{"title":"<em>Report</em>","content":"Fact","date":"2026-09-30 09:00:00","mediaName":"Publisher","code":"202609301234","url":"http://finance.eastmoney.com/a/202609301234.html"}]}});'
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: response)
    rows = module._fetch_eastmoney("600519", 1)
    assert rows[0].title == "Report"
    assert rows[0].published_at == datetime(2026, 9, 30, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert rows[0].url == "https://finance.eastmoney.com/a/202609301234.html"


def test_cninfo_discards_other_companies_and_returns_pdf_links(monkeypatch):
    module = china()
    response = MagicMock()
    response.json.return_value = {
        "announcements": [
            {
                "secCode": "600519",
                "secName": "<em>Company</em>",
                "announcementTitle": "Report",
                "announcementTime": 1790697600000,
                "adjunctUrl": "finalpage/2026-09-30/report.PDF",
            },
            {
                "secCode": "600117",
                "announcementTitle": "Wrong company",
                "announcementTime": 1790697600000,
                "adjunctUrl": "finalpage/other.PDF",
            },
        ],
        "hasMore": False,
    }
    monkeypatch.setattr(module.requests, "post", lambda *a, **k: response)
    rows = module._fetch_cninfo("600519", "2026-09-23", "2026-09-30", 1)
    assert len(rows) == 1
    assert rows[0].company_name == "Company"
    assert rows[0].url == "https://static.cninfo.com.cn/finalpage/2026-09-30/report.PDF"


def test_source_failure_does_not_erase_healthy_news(monkeypatch):
    module = china()

    def broken(*a):
        raise RuntimeError("network failed")

    monkeypatch.setattr(module, "_fetch_cninfo", broken)
    monkeypatch.setattr(module, "_fetch_eastmoney", lambda *a: [item()])
    out = module.get_china_stock_news("600519.SS", "2026-09-23", "2026-09-30")
    assert "Inside" in out and "DATA_UNAVAILABLE" in out and "CNINFO" in out


def test_empty_data_is_not_presented_as_neutral(monkeypatch):
    module = china()
    monkeypatch.setattr(module, "_fetch_cninfo", lambda *a: [])
    monkeypatch.setattr(module, "_fetch_eastmoney", lambda *a: [])
    out = module.get_china_stock_news("600519.SS", "2026-09-23", "2026-09-30")
    assert "NO_DATA_AVAILABLE" in out
    assert "not evidence of neutral sentiment" in out


def test_public_browser_fallback_only_on_failure(monkeypatch, config):
    module = china()
    config["china_news_browser_fallback"] = True

    def broken(*a):
        raise RuntimeError("endpoint unavailable")

    monkeypatch.setattr(module, "_fetch_cninfo", lambda *a: [])
    monkeypatch.setattr(module, "_fetch_eastmoney", broken)
    monkeypatch.setattr(module, "fetch_browser_news", lambda *a, **k: [item("Browser evidence")])
    out = module.get_china_stock_news("600519.SS", "2026-09-23", "2026-09-30")
    assert "Browser evidence" in out


def test_a_share_tool_uses_domestic_source_but_us_keeps_vendor(monkeypatch):
    from tradingagents.agents.utils import news_data_tools as tools

    monkeypatch.setattr(china(), "get_china_stock_news", lambda *a: "DOMESTIC")
    monkeypatch.setattr(tools, "route_to_vendor", lambda *a: "US_VENDOR")
    assert tools.get_news.func("600519.SS", "2026-09-23", "2026-09-30") == "DOMESTIC"
    assert tools.get_news.func("AAPL", "2026-09-23", "2026-09-30") == "US_VENDOR"


def test_a_share_sentiment_never_fetches_overseas_communities(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst as analyst

    monkeypatch.setattr(
        analyst.get_news,
        "func",
        lambda *a: "DOMESTIC EVIDENCE\nPublished: 2026-09-30T09:00:00+08:00",
    )
    monkeypatch.setattr(
        analyst, "fetch_stocktwits_messages", lambda *a, **k: pytest.fail("US social")
    )
    monkeypatch.setattr(analyst, "fetch_reddit_posts", lambda *a, **k: pytest.fail("US social"))
    captured = []

    def invoke(*args):
        captured.extend(args[2])
        return "Report"

    monkeypatch.setattr(analyst, "invoke_structured_or_freetext", invoke)
    analyst.create_sentiment_analyst(MagicMock())(
        {"company_of_interest": "600519.SS", "trade_date": "2026-09-30", "messages": []}
    )
    text = "\n".join(m.content for m in captured)
    assert "DOMESTIC EVIDENCE" in text
    assert "Yahoo Finance" not in text
    assert "not retail community sentiment" in text


def test_market_news_retains_good_source_when_other_fails(monkeypatch):
    module = china()
    monkeypatch.setattr(module, "_fetch_sina", lambda *a: [item("Sina evidence")])

    def broken(*a):
        raise RuntimeError("failure")

    monkeypatch.setattr(module, "_fetch_wallstreetcn", broken)
    out = module.get_china_market_news("2026-09-30", 7, 10)
    assert "Sina evidence" in out and "WallstreetCN" in out and "DATA_UNAVAILABLE" in out


def test_empty_a_share_sentiment_abstains_without_llm(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst as analyst

    monkeypatch.setattr(analyst.get_news, "func", lambda *a: "NO_DATA_AVAILABLE")
    monkeypatch.setattr(
        analyst, "invoke_structured_or_freetext", lambda *a: pytest.fail("unsupported score")
    )
    result = analyst.create_sentiment_analyst(MagicMock())(
        {"company_of_interest": "600519.SS", "trade_date": "2026-09-30", "messages": []}
    )
    assert "DATA_INSUFFICIENT" in result["sentiment_report"]
    assert "5.0" not in result["sentiment_report"]


def test_domestic_routing_can_be_disabled(monkeypatch, config):
    from tradingagents.agents.utils import news_data_tools as tools

    config["china_news_enabled"] = False
    monkeypatch.setattr(tools, "route_to_vendor", lambda *a: "CONFIGURED_VENDOR")
    assert tools.get_news.func("600519.SS", "2026-09-23", "2026-09-30") == "CONFIGURED_VENDOR"


def test_domestic_market_tool_is_registered_in_graph():
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    assert "get_china_market_news" in graph._create_tool_nodes()["news"].tools_by_name


def test_a_share_news_analyst_binds_only_domestic_tools():
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from tradingagents.agents.analysts.news_analyst import create_news_analyst

    names = []

    class LLM:
        def bind_tools(self, tools):
            names.extend(tool.name for tool in tools)
            return RunnableLambda(lambda prompt: AIMessage(content="Report"))

    result = create_news_analyst(LLM())(
        {"company_of_interest": "600519.SS", "trade_date": "2026-09-30", "messages": []}
    )
    assert result["news_report"] == "Report"
    assert names == ["get_news", "get_china_market_news"]


def test_browser_cls_extracts_dated_public_entries_and_links():
    from tradingagents.dataflows.china_news_browser import parse_browser_html

    html = """<div>2026.09.30 星期三 14:30:00</div>
      <div class="fixture-entry"><div>14:27:38</div><div>【Policy】财联社9月30日电，政策发布。</div>
      <div><div><a href="/detail/123">评论<span>(0)</span></a></div></div></div>"""
    rows = parse_browser_html("cls", html)
    assert len(rows) == 1
    assert rows[0].published_at.isoformat() == "2026-09-30T14:27:38+08:00"
    assert rows[0].url == "https://www.cls.cn/detail/123"
    assert "政策发布" in rows[0].content


def test_browser_rejects_login_or_captcha_page():
    from tradingagents.dataflows.china_news_browser import parse_browser_html

    with pytest.raises(ValueError):
        parse_browser_html("cls", "<html><body>请完成验证码</body></html>")


def test_browser_does_not_assign_analysis_date_to_undated_text():
    from tradingagents.dataflows.china_news_browser import parse_browser_html

    with pytest.raises(ValueError):
        parse_browser_html("cls", '<div>14:27:38 Policy <a href="/detail/123">评论</a></div>')


@pytest.mark.parametrize(
    "header,want",
    [
        ("2026.09.30 星期三 00:05:00", "2026-09-29T23:50:00+08:00"),
        ("2026.01.01 星期四 00:05:00", "2025-12-31T23:50:00+08:00"),
    ],
)
def test_cls_first_entry_before_midnight_keeps_previous_calendar_day(header, want):
    from tradingagents.dataflows.china_news_browser import parse_browser_html

    rows = parse_browser_html(
        "cls", f'<div>{header}</div><div>23:50:00 Policy <a href="/detail/123">评论</a></div>'
    )
    assert rows[0].published_at.isoformat() == want


def test_cls_rejects_inconsistent_wire_date_instead_of_inventing_year():
    from tradingagents.dataflows.china_news_browser import parse_browser_html

    with pytest.raises(ValueError):
        parse_browser_html(
            "cls",
            '<div>2026.09.30 星期三 14:30:00</div><div>14:27:38 财联社10月1日电，Policy <a href="/detail/123">评论</a></div>',
        )


@pytest.mark.parametrize(
    "source,html,want",
    [
        (
            "eastmoney",
            '<div class="news_item"><div class="news_item_t"><a href="http://finance.eastmoney.com/a/123.html">Title</a></div><div class="news_item_c"><span class="news_item_time">2026-09-30 09:00:00 - </span>Fact</div></div>',
            "2026-09-30T09:00:00+08:00",
        ),
        (
            "sina",
            '<div class="bd_i" data-time="20260930"><p class="bd_i_time_c">09:00:00</p><p class="bd_i_txt_c"><a href="https://wap.cj.sina.cn/pc/7x24/123">Fact</a></p></div>',
            "2026-09-30T09:00:00+08:00",
        ),
        (
            "wallstreetcn",
            '<div class="live-item"><time datetime="2026-09-30T09:00:00+08:00"></time><div class="live-item_html">Fact</div><a href="https://juicy.wscn.net/livenews/edit/123">Edit</a></div>',
            "2026-09-30T09:00:00+08:00",
        ),
    ],
)
def test_other_browser_sources_preserve_verified_dates(source, html, want):
    from tradingagents.dataflows.china_news_browser import parse_browser_html

    rows = parse_browser_html(source, html)
    assert len(rows) == 1 and rows[0].published_at.isoformat() == want
    assert rows[0].url.startswith("https://") and "Fact" in rows[0].content


def test_successful_stock_news_is_cached_even_if_no_announcements(monkeypatch, config):
    from collections import OrderedDict

    module = china()
    config["china_news_cache_ttl"] = 300
    monkeypatch.setattr(module, "_cache", OrderedDict())
    monkeypatch.setattr(module, "_fetch_cninfo", lambda *a: [])
    responses = iter([[item("Cached evidence")]])
    monkeypatch.setattr(module, "_fetch_eastmoney", lambda *a: next(responses))
    first = module.get_china_stock_news("600519.SS", "2026-09-23", "2026-09-30")
    second = module.get_china_stock_news("600519.SS", "2026-09-23", "2026-09-30")
    assert "Cached evidence" in first and second == first


def test_cache_expiry_reloads_source_and_failures_are_not_cached(monkeypatch, config):
    from collections import OrderedDict

    module = china()
    config["china_news_cache_ttl"] = 300
    monkeypatch.setattr(module, "_cache", OrderedDict())
    clock = [0]
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    assert module._cached("key", lambda: "Published: original") == "Published: original"
    clock[0] = 299
    assert module._cached("key", lambda: "Published: changed") == "Published: original"
    clock[0] = 300
    assert module._cached("key", lambda: "Published: changed") == "Published: changed"
    assert (
        module._cached("failure", lambda: "DATA_UNAVAILABLE: failed") == "DATA_UNAVAILABLE: failed"
    )
    assert module._cached("failure", lambda: "Published: recovered") == "Published: recovered"


def test_cache_evicts_oldest_reports_at_capacity(monkeypatch, config):
    from collections import OrderedDict

    module = china()
    config["china_news_cache_ttl"] = 300
    monkeypatch.setattr(module, "_cache", OrderedDict())
    for index in range(65):
        module._cached(str(index), lambda: "Published: original")
    assert module._cached("0", lambda: "Published: reloaded") == "Published: reloaded"
    assert module._cached("64", lambda: "Published: reloaded") == "Published: original"


def test_cache_never_reuses_a_different_analysis_window(monkeypatch, config):
    from collections import OrderedDict

    module = china()
    config["china_news_cache_ttl"] = 300
    monkeypatch.setattr(module, "_cache", OrderedDict())
    monkeypatch.setattr(module, "_fetch_cninfo", lambda *a: [])
    monkeypatch.setattr(
        module,
        "_fetch_eastmoney",
        lambda *a: [item("Today"), item("Yesterday", "2026-09-29T09:00:00+08:00")],
    )
    today = module.get_china_stock_news("600519.SS", "2026-09-30", "2026-09-30")
    yesterday = module.get_china_stock_news("600519.SS", "2026-09-29", "2026-09-29")
    assert "### Today" in today and "### Yesterday" not in today
    assert "### Yesterday" in yesterday and "### Today" not in yesterday


def test_graph_executes_domestic_tool_and_filters_future_feed_items(monkeypatch):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from tradingagents.graph.trading_graph import TradingAgentsGraph

    module = china()

    def response(url, **kwargs):
        result = MagicMock()
        if "sina" in url:
            result.json.return_value = {
                "result": {
                    "data": {
                        "feed": {
                            "list": [
                                {
                                    "rich_text": "SINA_FACT",
                                    "create_time": "2026-09-30 09:00:00",
                                    "docurl": "https://finance.sina.cn/item",
                                },
                                {
                                    "rich_text": "FUTURE_FACT",
                                    "create_time": "2026-10-01 09:00:00",
                                    "docurl": "https://finance.sina.cn/future",
                                },
                            ]
                        }
                    }
                }
            }
        else:
            result.json.return_value = {
                "data": {
                    "items": [
                        {
                            "content_text": "WSCN_FACT",
                            "display_time": 1790726400,
                            "uri": "https://wallstreetcn.com/livenews/123",
                        }
                    ]
                }
            }
        return result

    monkeypatch.setattr(module.requests, "get", response)
    node = TradingAgentsGraph.__new__(TradingAgentsGraph)._create_tool_nodes()["news"]
    graph = StateGraph(MessagesState)
    graph.add_node("news_tools", node)
    graph.add_edge(START, "news_tools")
    graph.add_edge("news_tools", END)
    output = graph.compile().invoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "get_china_market_news",
                            "args": {"curr_date": "2026-09-30", "limit": 10},
                            "id": "domestic-tool-1",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }
    )
    text = output["messages"][-1].content
    assert "SINA_FACT" in text and "WSCN_FACT" in text and "FUTURE_FACT" not in text
