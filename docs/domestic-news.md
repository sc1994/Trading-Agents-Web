# Domestic News Sources

Mainland equity news is routed to domestic sources by default. Other markets,
including US and Hong Kong equities, keep the configured vendor AND automatically
retrieve supplementary Chinese company news. Global news also combines the
configured vendor with Chinese macro feeds. This changes news retrieval only, not
prices, financial statements, trading or deployment.

## Sources

- Eastmoney: company-code news searches ordered by time. If announcements supply
  a verified company name, it is also searched. Results can mention a company
  incidentally; analysts must assess relevance. HK/US Chinese names come from the
  public suggestion directory only after an exact code and market match. HK
  queries use qualified symbols (e.g. `0780.HK`, `00780.HK`) and the verified
  name (`同程旅行`), never an ambiguous bare numeric code. Non-mainland results
  must mention an alias/name with alphanumeric boundaries. Directory names are
  current identities, not a point-in-time historical company-name archive.
- CNINFO: company announcements with original PDF links. Returned securities are
  checked against the requested code. PDF bodies are not automatically read;
  reports explicitly identify metadata-only evidence and date-only timestamps.
  Mainland equities only: HK/US instruments never query this disclosure endpoint.
- Sina Finance and WallstreetCN: recent public market-news feeds.
- CLS: public telegraph-page excerpts. Static parsing is attempted first; a
  headless browser loads the public page when client-side rendering is needed.

The A-share news analyst uses company news plus domestic market news. Its sentiment
analyst assesses news/events, not community opinions. It does not request Reddit
or StockTwits. It scores only dated company evidence: when the primary lookback
window returns none, the window widens through `sentiment_window_fallback_days`
(7 → 14 → 30 days by default) before the analyst abstains, so a multi-day market
holiday does not by itself produce an abstention; a widened report discloses the
actual window and instructs the analyst to weight the most recent items. HK/US
sentiment retains available overseas communities and uses the combined
company-news block; social sources stay on the primary window. All markets
abstain with `DATA_INSUFFICIENT` when no article/social records were retrieved in
any window. Chinese macro feeds are context, not company-sentiment evidence.
Chinese news is not forum discussion: Xueqiu and Eastmoney Guba are not
integrated. Independent source failures do not erase healthy company or
global-news sources. New evidence policy/config changes invalidate older graph
checkpoints, so they cannot silently resume old reports.

## Browser Setup

For a local Python installation:

```bash
pip install '.[browser]'
python -m playwright install --with-deps chromium
```

The web Docker image installs the browser extra and Chromium, with binaries
readable by its non-root runtime user. Existing containers need rebuilding; this
change does not deploy or rebuild a running service.

Each browser uses a fresh context, accepts no downloads, and only navigates to a
fixed list of public news sites. It never supplies account cookies, logs in,
solves CAPTCHAs, uses stealth plugins or bypasses paywalls. If a page is blocked
or changes structure, that source is reported unavailable. Only already-public
CLS excerpts may be expanded.

## Configuration

The existing Python config accepts these keys:

| Key | Default | Purpose |
| --- | --- | --- |
| `china_news_enabled` | `True` | Domestic routing for mainland equities, supplementary company/global news elsewhere; `False` restores configured vendors |
| `china_news_browser_fallback` | `True` | Enable public-browser fallback and CLS enrichment |
| `china_news_timeout` | `10` | HTTP timeout in seconds per request |
| `china_news_browser_timeout` | `20` | Browser-attempt budget in seconds, capped at 60 |
| `china_news_max_pages` | `2` | Pages per API query, hard cap of 3 |
| `china_news_cache_ttl` | `300` | Successful-report cache lifetime in seconds per process |
| `sentiment_window_days` | `7` | Primary sentiment lookback window in days |
| `sentiment_window_fallback_days` | `[14, 30]` | Progressive fallback windows used when the primary window has no dated company evidence; entries must exceed the primary window and are capped at 365 days |

`news_article_limit` and `global_news_article_limit` cap returned articles.
The `china` vendor is also registered for `get_news` and `get_global_news` for
explicit configuration. Keep the existing primary vendor to preserve overseas
coverage; automatic supplementation is preferable to selecting `china` globally.

All items require dates and original links. Filtering uses Asia/Shanghai calendar
days, with an exclusive midnight-after upper bound. Reports disclose source
failures, page caps and incomplete historical coverage. Public feeds are not
historical archives; current articles cannot be substituted into an older run.
Deduplication uses normalized title and publication date, within each report.

## Verification

```bash
python -m pytest tests/test_china_news.py
python -m pytest tests/test_cross_market_news.py
```

Live smoke check (requires network; no LLM credentials):

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from tradingagents.agents.utils.news_data_tools import get_news, get_china_market_news

today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
print(get_news.func("600519.SS", today, today))
print(get_china_market_news.func(today, 1, 10))
```

Public access is not a commercial redistribution license or an uptime guarantee.
Confirm site terms, automated-access rules and model-processing/display rights
before production use. Tushare, paid news and authenticated communities are not
integrated by this change.
