"""Chinese news supplements every market without confusing symbol identities."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tradingagents.dataflows import china_news as news
from tradingagents.dataflows.config import set_config


@pytest.fixture(autouse=True)
def bounded_config():
    set_config({"china_news_cache_ttl": 0, "china_news_browser_fallback": False})


@pytest.mark.parametrize("ticker,rows,expected", [
    ("0780.HK", [
        {"Code": "000780", "Classify": "AStock", "Name": "Wrong company"},
        {"Code": "00780", "Classify": "HK", "TypeUS": "3", "Name": "同程旅行"},
    ], ["0780.HK", "00780.HK", "同程旅行"]),
    ("AAPL", [
        {"Code": "AAPL22", "Classify": "UsStock", "TypeUS": "6", "Name": "Wrong bond"},
        {"Code": "AAPL", "Classify": "UsStock", "TypeUS": "1", "Name": "苹果"},
    ], ["AAPL", "苹果"]),
    ("0780.HK", [{"Code": "000780", "Classify": "AStock", "Name": "Wrong"}], ["0780.HK", "00780.HK"]),
])
def test_verified_keywords(monkeypatch, ticker, rows, expected):
    response = MagicMock()
    response.json.return_value = {"QuotationCodeTable": {"Data": rows}}
    monkeypatch.setattr(news, "_get", lambda *a, **k: response)
    assert news._news_keywords(ticker) == expected


def test_hk_news_is_relevant_historical_and_never_queries_cninfo(monkeypatch):
    monkeypatch.setattr(news, "_news_keywords", lambda t: ["0780.HK", "00780.HK", "同程旅行"])
    monkeypatch.setattr(news, "_fetch_cninfo", lambda *a: pytest.fail("HK mainland disclosure"))
    def item(title, day):
        return news.NewsItem(title, "Fact", datetime.fromisoformat(day + "T09:00:00+08:00"), "Fixture", "https://example.com/news")
    monkeypatch.setattr(news, "_fetch_eastmoney", lambda *a: [
        item("同程旅行 historical", "2026-09-24"),
        item("同程旅行 future", "2026-09-30"),
        item("Other company", "2026-09-24"),
    ])
    result = news.get_china_stock_news("0780.HK", "2026-09-17", "2026-09-24")
    assert "historical" in result and "future" not in result and "Other company" not in result
    assert "not applicable" in result


@pytest.mark.parametrize("ticker", ["0780.HK", "AAPL"])
def test_company_tool_retains_both_sources(monkeypatch, ticker):
    from tradingagents.agents.utils import news_data_tools as tools
    monkeypatch.setattr(news, "get_china_stock_news", lambda *a: "CHINESE COMPANY NEWS")
    monkeypatch.setattr(tools, "route_to_vendor", lambda *a: "OVERSEAS NEWS")
    result = tools.get_news.func(ticker, "2026-09-17", "2026-09-24")
    assert "CHINESE COMPANY NEWS" in result and "OVERSEAS NEWS" in result


@pytest.mark.parametrize("failed", ["domestic", "configured"])
def test_company_tool_isolates_source_exceptions(monkeypatch, failed):
    from tradingagents.agents.utils import news_data_tools as tools
    def broken(*a):
        raise RuntimeError("endpoint failed")
    monkeypatch.setattr(news, "get_china_stock_news", broken if failed == "domestic" else lambda *a: "HEALTHY")
    monkeypatch.setattr(tools, "route_to_vendor", broken if failed == "configured" else lambda *a: "HEALTHY")
    result = tools.get_news.func("0780.HK", "2026-09-17", "2026-09-24")
    assert "HEALTHY" in result and "DATA_UNAVAILABLE" in result


def test_global_tool_supplements_macro_context(monkeypatch):
    from tradingagents.agents.utils import news_data_tools as tools
    monkeypatch.setattr(news, "get_china_market_news", lambda *a: "CHINESE MACRO")
    monkeypatch.setattr(tools, "route_to_vendor", lambda *a: "GLOBAL MACRO")
    result = tools.get_global_news.func("2026-09-24", 7, 10)
    assert "CHINESE MACRO" in result and "GLOBAL MACRO" in result
    assert "not company sentiment" in result


@pytest.mark.parametrize("ticker", ["0780.HK", "AAPL", "600519.SS"])
def test_empty_sentiment_abstains_in_every_market(monkeypatch, ticker):
    from tradingagents.agents.analysts import sentiment_analyst as analyst
    monkeypatch.setattr(analyst.get_news, "func", lambda *a: "No news found")
    monkeypatch.setattr(analyst, "fetch_stocktwits_messages", lambda *a, **k: "<stocktwits unavailable: HTTPError>")
    monkeypatch.setattr(analyst, "fetch_reddit_posts", lambda *a, **k: "<no Reddit posts found>")
    monkeypatch.setattr(analyst, "invoke_structured_or_freetext", lambda *a: pytest.fail("no unsupported scoring"))
    result = analyst.create_sentiment_analyst(MagicMock())({"company_of_interest": ticker, "trade_date": "2026-09-24", "messages": []})
    assert "DATA_INSUFFICIENT" in result["sentiment_report"]


def test_social_only_evidence_can_still_be_scored(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst as analyst
    monkeypatch.setattr(analyst.get_news, "func", lambda *a: "NO_DATA_AVAILABLE")
    monkeypatch.setattr(analyst, "fetch_stocktwits_messages", lambda *a, **k: "Total: 1 most-recent messages\n[2026-09-24 · @user · Bullish] AAPL strong")
    monkeypatch.setattr(analyst, "fetch_reddit_posts", lambda *a, **k: "<no Reddit posts found>")
    monkeypatch.setattr(analyst, "invoke_structured_or_freetext", lambda *a: "Evidence-based report")
    result = analyst.create_sentiment_analyst(MagicMock())({"company_of_interest": "AAPL", "trade_date": "2026-09-24", "messages": []})
    assert result["sentiment_report"] == "Evidence-based report"


@pytest.mark.parametrize("block", [
    '## Configured news vendor\n{"feed":[{"title":"Event","url":"https://example.com/a","time_published":"20260924T090000"}]}\n\n## Domestic Chinese sources\nNO_DATA_AVAILABLE',
    '### Event (source: Reuters)\nSummary\nLink: https://example.com/news\n',
])
def test_overseas_article_formats_are_evidence(block):
    from tradingagents.agents.analysts.sentiment_analyst import _has_company_evidence
    assert _has_company_evidence(block)


def test_no_articles_or_status_only_is_not_evidence():
    from tradingagents.agents.analysts.sentiment_analyst import _has_company_evidence
    assert not _has_company_evidence('## Configured news vendor\n{"feed":[]}\n\n## Domestic Chinese sources\nDATA_UNAVAILABLE')


def test_hk_news_analyst_requires_fused_company_and_macro_sources():
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    from tradingagents.agents.analysts.news_analyst import create_news_analyst
    captured = []
    def respond(prompt):
        captured.extend(prompt.to_messages())
        return AIMessage(content="Report")
    llm = MagicMock()
    llm.bind_tools.return_value = RunnableLambda(respond)
    create_news_analyst(llm)({"company_of_interest": "0780.HK", "trade_date": "2026-09-24", "messages": []})
    text = "\n".join(m.content for m in captured)
    assert "must retrieve get_news" in text and "get_global_news" in text
    assert "regardless of listing market" in text


def test_disabling_supplement_does_not_fetch_domestic(monkeypatch):
    from tradingagents.agents.utils import news_data_tools as tools
    set_config({"china_news_enabled": False})
    monkeypatch.setattr(news, "get_china_stock_news", lambda *a: pytest.fail("disabled"))
    monkeypatch.setattr(news, "get_china_market_news", lambda *a: pytest.fail("disabled"))
    monkeypatch.setattr(tools, "route_to_vendor", lambda *a: "VENDOR ONLY")
    assert tools.get_news.func("0780.HK", "2026-09-17", "2026-09-24") == "VENDOR ONLY"
    assert tools.get_global_news.func("2026-09-24") == "VENDOR ONLY"


def test_news_policy_invalidates_old_checkpoint():
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.selected_analysts = ["news", "social"]
    graph.config = {"max_debate_rounds": 1, "max_risk_discuss_rounds": 1, "china_news_enabled": True}
    enabled = graph._run_signature("stock")
    assert "news_evidence=v3" in enabled
    assert "sentiment_window=7/14,30" in enabled
    graph.config["china_news_enabled"] = False
    assert enabled != graph._run_signature("stock")
    graph.config = {
        "max_debate_rounds": 1, "max_risk_discuss_rounds": 1, "china_news_enabled": True,
        "sentiment_window_days": 7, "sentiment_window_fallback_days": [30],
    }
    assert enabled != graph._run_signature("stock")


def test_disabled_domestic_empty_vendor_dict_abstains(monkeypatch):
    from tradingagents.agents.analysts import sentiment_analyst as analyst
    set_config({"china_news_enabled": False})
    monkeypatch.setattr(analyst.get_news, "func", lambda *a: {"feed": []})
    monkeypatch.setattr(analyst, "fetch_stocktwits_messages", lambda *a, **k: "<unavailable>")
    monkeypatch.setattr(analyst, "fetch_reddit_posts", lambda *a, **k: "<unavailable>")
    monkeypatch.setattr(analyst, "invoke_structured_or_freetext", lambda *a: pytest.fail("unsupported score"))
    result = analyst.create_sentiment_analyst(MagicMock())({"company_of_interest": "AAPL", "trade_date": "2026-09-24", "messages": []})
    assert "DATA_INSUFFICIENT" in result["sentiment_report"]
