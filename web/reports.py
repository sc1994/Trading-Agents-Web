"""Project existing graph reports into public, source-backed display fields."""

import re

from tradingagents.agents.utils.rating import RATING_REVIEW, extract_rating

_THINKING = re.compile(r"<(think|thinking|reasoning)\b[^>]*>.*?(?:</\1\s*>|$)", re.I | re.S)
_FIELD = re.compile(r"^\*\*([^*\n]+)\*\*\s*:\s*", re.M)
_DECISION_FIELDS = {
    "Executive Summary": "executive_summary",
    "Investment Thesis": "investment_thesis",
    "Price Target": "price_target",
    "Time Horizon": "time_horizon",
}


def public_text(text: str) -> str:
    """Remove explicitly marked hidden reasoning, including unfinished blocks."""
    return _THINKING.sub("", text)


def report_sections(state: dict) -> dict[str, str]:
    """Allowlist report outputs; never forward messages, tool calls or duplicate history."""
    sections = {}

    def add(section, content):
        if isinstance(content, str) and (text := public_text(content)).strip():
            sections[section] = text

    for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report"):
        add(key, state.get(key))
    research = state.get("investment_debate_state") or {}
    for key in ("bull_history", "bear_history"):
        add(key, research.get(key))
    add("investment_plan", state.get("investment_plan") or research.get("judge_decision"))
    add("trader_investment_plan", state.get("trader_investment_plan"))
    risk = state.get("risk_debate_state") or {}
    for key in ("aggressive_history", "conservative_history", "neutral_history"):
        add(key, risk.get(key))
    add("decision", state.get("final_trade_decision") or risk.get("judge_decision"))
    return sections


def decision_view(markdown: str) -> dict:
    """Read the native PM Markdown fields without generating missing evidence."""
    markdown = public_text(markdown)
    view = {"rating": extract_rating(markdown) or RATING_REVIEW}
    fields = list(_FIELD.finditer(markdown))
    for index, match in enumerate(fields):
        key = _DECISION_FIELDS.get(match.group(1))
        end = fields[index + 1].start() if index + 1 < len(fields) else len(markdown)
        value = markdown[match.end():end].strip()
        if key and value:
            view[key] = value
    return view
