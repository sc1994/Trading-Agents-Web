"""The sentiment analyst widens its lookback window before abstaining.

A short window can be legitimately empty while every source is reachable —
e.g. the 2026-10-09 analysis of 300511.SZ, whose 7-day window covered the
National Day golden week (market closed 10-01..10-07) plus two trading days
with no coverage. The analyst must widen (7 -> 14 -> 30 days) and score real
evidence instead of abstaining on a calendar artifact.
"""

from unittest.mock import MagicMock

import pytest

from tradingagents.dataflows.config import set_config

CHINA_TICKER = "300511.SZ"
TRADE_DATE = "2026-10-09"  # first analysis after the golden week
PRIMARY_START = "2026-10-02"  # 7 days back
WIDE_START = "2026-09-25"  # 14 days back
WIDEST_START = "2026-09-09"  # 30 days back


@pytest.fixture(autouse=True)
def windows_config():
    set_config(
        {
            "china_news_cache_ttl": 0,
            "china_news_browser_fallback": False,
            "sentiment_window_days": 7,
            "sentiment_window_fallback_days": [14, 30],
        }
    )


def _rendered(day: str) -> str:
    return (
        "## 300511.SZ: domestic news and official announcements\n\n"
        f"### 雪榕生物公告 {day}\nPublished: {day}T09:00:00+08:00\n"
        "Source: Eastmoney\nBody\nLink: https://example.com/news\n"
    )


def _run(monkeypatch, ticker, news_by_window, stocktwits="<stocktwits unavailable>",
         reddit="<no Reddit posts found>"):
    from tradingagents.agents.analysts import sentiment_analyst as analyst

    news_calls, social_calls, prompts = [], [], []

    def fake_get_news(t, start, end):
        news_calls.append((start, end))
        return news_by_window(start)

    def fake_stocktwits(t, **kwargs):
        social_calls.append(("stocktwits", kwargs.get("start_date"), kwargs.get("end_date")))
        return stocktwits

    def fake_reddit(t, **kwargs):
        social_calls.append(("reddit", kwargs.get("start_date"), kwargs.get("end_date")))
        return reddit

    def fake_invoke(*args):
        prompts.append("\n".join(m.content for m in args[2]))
        return "SCORED REPORT"

    monkeypatch.setattr(analyst.get_news, "func", fake_get_news)
    monkeypatch.setattr(analyst, "fetch_stocktwits_messages", fake_stocktwits)
    monkeypatch.setattr(analyst, "fetch_reddit_posts", fake_reddit)
    monkeypatch.setattr(analyst, "invoke_structured_or_freetext", fake_invoke)
    result = analyst.create_sentiment_analyst(MagicMock())(
        {"company_of_interest": ticker, "trade_date": TRADE_DATE, "messages": []}
    )
    return result, news_calls, social_calls, prompts


def test_china_widens_to_first_window_with_evidence(monkeypatch):
    def news_by_window(start):
        return "NO_DATA_AVAILABLE" if start == PRIMARY_START else _rendered("2026-09-30")

    result, news_calls, _, prompts = _run(monkeypatch, CHINA_TICKER, news_by_window)
    assert result["sentiment_report"] == "SCORED REPORT"
    assert news_calls == [(PRIMARY_START, TRADE_DATE), (WIDE_START, TRADE_DATE)]
    assert "widened to 14 days" in prompts[0]
    assert "covering 2026-09-25 to 2026-10-09" in prompts[0]


def test_china_abstains_only_after_every_window_is_empty(monkeypatch):
    result, news_calls, _, _ = _run(monkeypatch, CHINA_TICKER, lambda start: "NO_DATA_AVAILABLE")
    assert "DATA_INSUFFICIENT" in result["sentiment_report"]
    assert "逐级放宽窗口" in result["sentiment_report"]
    assert news_calls == [
        (PRIMARY_START, TRADE_DATE),
        (WIDE_START, TRADE_DATE),
        (WIDEST_START, TRADE_DATE),
    ]


def test_china_does_not_widen_when_primary_window_has_evidence(monkeypatch):
    result, news_calls, _, prompts = _run(
        monkeypatch, CHINA_TICKER, lambda start: _rendered("2026-10-08")
    )
    assert result["sentiment_report"] == "SCORED REPORT"
    assert news_calls == [(PRIMARY_START, TRADE_DATE)]
    assert "widened" not in prompts[0]


def test_china_evidence_in_widest_window_still_scores(monkeypatch):
    def news_by_window(start):
        return _rendered("2026-09-10") if start == WIDEST_START else "NO_DATA_AVAILABLE"

    result, news_calls, _, prompts = _run(monkeypatch, CHINA_TICKER, news_by_window)
    assert result["sentiment_report"] == "SCORED REPORT"
    assert news_calls[-1] == (WIDEST_START, TRADE_DATE)
    assert "widened to 30 days" in prompts[0]


def test_overseas_widens_news_while_social_stays_on_primary_window(monkeypatch):
    def news_by_window(start):
        return "NO_DATA_AVAILABLE" if start == PRIMARY_START else _rendered("2026-09-30")

    result, news_calls, social_calls, prompts = _run(monkeypatch, "AAPL", news_by_window)
    assert result["sentiment_report"] == "SCORED REPORT"
    assert news_calls == [(PRIMARY_START, TRADE_DATE), (WIDE_START, TRADE_DATE)]
    assert social_calls == [
        ("stocktwits", PRIMARY_START, TRADE_DATE),
        ("reddit", PRIMARY_START, TRADE_DATE),
    ]
    assert "past 14 days (2026-09-25 to 2026-10-09)" in prompts[0]
    assert "past 7 days" in prompts[0]


def test_overseas_abstains_after_all_windows_and_social_are_empty(monkeypatch):
    result, news_calls, _, _ = _run(monkeypatch, "AAPL", lambda start: "NO_DATA_AVAILABLE")
    assert "DATA_INSUFFICIENT" in result["sentiment_report"]
    assert len(news_calls) == 3


def test_lookback_windows_sanitizes_config():
    from tradingagents.agents.analysts.sentiment_analyst import _lookback_windows

    set_config(
        {
            "sentiment_window_days": 7,
            "sentiment_window_fallback_days": [3, 14, 14, "30", 400, 30, True],
        }
    )
    windows = _lookback_windows(TRADE_DATE)
    assert [days for days, _ in windows] == [7, 14, 30]
    assert windows[1] == (14, WIDE_START)


def test_lookback_windows_invalid_primary_falls_back_to_seven_days():
    from tradingagents.agents.analysts.sentiment_analyst import _lookback_windows

    set_config({"sentiment_window_days": 0, "sentiment_window_fallback_days": [14]})
    assert [days for days, _ in _lookback_windows(TRADE_DATE)] == [7, 14]


def test_lookback_windows_without_fallbacks_stays_single():
    from tradingagents.agents.analysts.sentiment_analyst import _lookback_windows

    set_config({"sentiment_window_fallback_days": []})
    assert _lookback_windows(TRADE_DATE) == [(7, PRIMARY_START)]


def test_window_notice_only_when_widened():
    from tradingagents.agents.analysts.sentiment_analyst import _window_notice

    assert _window_notice(7, 7) == ""
    notice = _window_notice(7, 14)
    assert "widened to 14 days" in notice and "historical context" in notice
