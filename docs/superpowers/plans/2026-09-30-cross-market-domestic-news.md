# Cross-market Domestic News Implementation Plan

> **For agentic workers:** Execute inline using superpowers:executing-plans; review the completed change using superpowers:requesting-code-review.

**Goal:** Supplement configured news with Chinese company and macro sources across markets, and abstain when sentiment has no evidence.

**Architecture:** Resolve Chinese names with exact market/code matches from the existing public Eastmoney suggestion API. Keep CNINFO mainland-only. Combine independently failing sources at the tool boundary; company evidence and macro context stay separate.

**Tech Stack:** Python, requests, LangChain tools, pytest, optional Playwright.

**Spec:** User-approved scope: HK/US domestic supplementation, original sources retained, strict historical dates, no-data abstention, no new forums or production deployment.

## Global Constraints

- No guessed company mappings, credentials, CAPTCHA or paywall bypasses.
- Domestic macro context is not company sentiment evidence.
- Existing isolated worktree; deliver a new PR, not a deployment.

## Task 1: Verified names and cross-market company retrieval

Files: `tradingagents/dataflows/china_news.py`, `tests/test_cross_market_news.py`.

- [x] Add tests for exact HK/US matches, wrong-market rejection, CNINFO exclusion and historical relevance filtering. Example: `assert module._news_keywords("0780.HK") == ["0780.HK", "00780.HK", "同程旅行"]` with mocked suggestion rows.
- [x] Run `python3 -m pytest tests/test_cross_market_news.py -q` and confirm intended failures.
- [x] Implement bounded suggestion lookup, explicit symbol aliases, company-name search and relevance filtering: `news = [row for row in news if _relevant(row, keywords)]`. Preserve mainland disclosure behavior.
- [x] Re-run focused tests and existing domestic tests.

## Task 2: Supplementary tools and sentiment abstention

Files: `tradingagents/agents/utils/news_data_tools.py`, `tradingagents/agents/analysts/{news_analyst,sentiment_analyst}.py`, corresponding tests.

- [x] Add failing tests for HK/US fused news, source failure isolation, global macro fusion, disabled flag, and no-data abstention. Example: `assert "DATA_INSUFFICIENT" in result["sentiment_report"]` when all three sources are empty.
- [x] Combine source blocks with explicit labels and independent exception handling. Extend analyst access/prompts while retaining mainland-only community exclusions.
- [x] Detect actual article or social-record formats before invoking sentiment generation; replace Neutral-on-silence prompt wording.
- [x] Supply deterministic evidence fixtures to structured-output tests and re-run related suites.

## Task 3: Verification and delivery

Files: `docs/domestic-news.md` and this checklist.

- [x] Update source coverage/limitations documentation.
- [x] Probe `0780.HK` for Sept17-24 and capture a public-source screenshot if browsing is used.
- [x] Run full pytest, diff checks, and a read-only independent code review; address findings.
- [x] Commit, push and create a PR; report actual verification and limitations, without claiming deployment.

Delivery: https://github.com/sc1994/Trading-Agents-Web/pull/26 (not deployed).

Verification: final suite 1114 passed, 2 skipped, 71 subtests; changed-file Ruff
and git diff checks passed. Read-only review approved after a red/green test fixed
empty structured vendor output under disabled domestic supplementation. Live
Sept17-24 retrieval: HK0780 20 dated domestic articles; AAPL 8. Browser search
extracted 10 public items; its current page is not evidence for an older window.
