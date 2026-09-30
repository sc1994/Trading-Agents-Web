import json
from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows import china_news
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.interface import route_to_vendor


def _supplement(configured, domestic, *, context=False):
    blocks = []
    for label, fetch in [("Configured news vendor", configured), ("Domestic Chinese sources", domestic)]:
        try:
            content = fetch()
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False)
        except Exception:
            content = f"DATA_UNAVAILABLE: {label} fetch failed; missing data is not neutral sentiment."
        blocks.append(f"## {label}\n{content}")
    prefix = "Macro context only, not company sentiment evidence.\n\n" if context else ""
    return prefix + "\n\n".join(blocks)


@tool
def get_news(
    ticker: Annotated[str, "Ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """
    Retrieve news data for a given ticker symbol.
    Domestic Chinese company news supplements the configured vendor across markets.
    Mainland equities use domestic news and official disclosure metadata.
    Args:
        ticker (str): Ticker symbol
        start_date (str): Start date in yyyy-mm-dd format
        end_date (str): End date in yyyy-mm-dd format
    Returns:
        str: A formatted string containing news data
    """
    if get_config().get("china_news_enabled", True):
        if china_news.china_stock_code(ticker):
            return china_news.get_china_stock_news(ticker, start_date, end_date)
        return _supplement(
            lambda: route_to_vendor("get_news", ticker, start_date, end_date),
            lambda: china_news.get_china_stock_news(ticker, start_date, end_date),
        )
    return route_to_vendor("get_news", ticker, start_date, end_date)


@tool
def get_china_market_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back"] = None,
    limit: Annotated[int | None, "Max articles to return"] = None,
) -> str:
    """Retrieve dated Chinese financial news from Sina, WallstreetCN and public CLS pages.

    Public feeds have limited history; absence of articles is not neutral sentiment.
    """
    return china_news.get_china_market_news(curr_date, look_back_days, limit)

@tool
def get_global_news(
    curr_date: Annotated[str, "Current date in yyyy-mm-dd format"],
    look_back_days: Annotated[int | None, "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[int | None, "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Retrieve global news data.
    Uses the configured news_data vendor. Defaults for look_back_days and
    limit come from DEFAULT_CONFIG (global_news_lookback_days,
    global_news_article_limit); pass explicit values to override.

    Args:
        curr_date (str): Current date in yyyy-mm-dd format
        look_back_days (int): Number of days to look back; omit to inherit config
        limit (int): Maximum number of articles to return; omit to inherit config

    Returns:
        str: A formatted string containing global news data
    """
    if get_config().get("china_news_enabled", True):
        return _supplement(
            lambda: route_to_vendor("get_global_news", curr_date, look_back_days, limit),
            lambda: china_news.get_china_market_news(curr_date, look_back_days, limit),
            context=True,
        )
    return route_to_vendor("get_global_news", curr_date, look_back_days, limit)

@tool
def get_insider_transactions(
    ticker: Annotated[str, "ticker symbol"],
) -> str:
    """
    Retrieve insider transaction information about a company.
    Uses the configured news_data vendor.
    Args:
        ticker (str): Ticker symbol of the company
    Returns:
        str: A report of insider transaction data
    """
    return route_to_vendor("get_insider_transactions", ticker)
