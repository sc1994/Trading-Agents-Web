import pytest

from web.reports import decision_view, report_sections


@pytest.mark.parametrize("rating", ["Buy", "Overweight", "Hold", "Underweight", "Sell"])
def test_decision_preserves_native_rating_without_inventing_confidence(rating):
    view = decision_view(f"**Rating**: {rating}\n\n**Executive Summary**: Evidence-based plan")
    assert view == {"rating": rating, "executive_summary": "Evidence-based plan"}
    assert decision_view("unparseable") == {"rating": "REVIEW"}


def test_decision_extracts_only_present_markdown_fields_without_rewriting_them():
    view = decision_view(
        "**Rating**: Underweight\n\n**Executive Summary**: Reduce exposure.\n\n"
        "**Investment Thesis**: Evidence one.\n\n- Risk: funding costs.\n\n"
        "**Price Target**: 0.0\n\n**Time Horizon**: 3–6 months\n\n"
        "**Confidence**: 99%"
    )
    assert view == {
        "rating": "Underweight",
        "executive_summary": "Reduce exposure.",
        "investment_thesis": "Evidence one.\n\n- Risk: funding costs.",
        "price_target": "0.0",
        "time_horizon": "3–6 months",
    }


def test_sections_include_only_public_reports_and_existing_debate_outputs():
    state = {
        "messages": [{"content": "private tool payload"}],
        "reasoning": "hidden reasoning",
        "market_report": "Market evidence",
        "news_report": "",
        "investment_debate_state": {
            "bull_history": "Bull evidence", "bear_history": "Bear evidence",
            "judge_decision": "Research conclusion", "history": "duplicate history",
            "current_response": "duplicate latest response", "count": 2,
        },
        "trader_investment_plan": "Trading plan",
        "risk_debate_state": {
            "aggressive_history": "Risk taking case",
            "conservative_history": "Risk reducing case", "neutral_history": "Neutral case",
            "judge_decision": "**Rating**: Buy", "history": "duplicate risk history",
        },
        "final_trade_decision": "**Rating**: Buy",
    }
    assert report_sections(state) == {
        "market_report": "Market evidence",
        "bull_history": "Bull evidence", "bear_history": "Bear evidence",
        "investment_plan": "Research conclusion", "trader_investment_plan": "Trading plan",
        "aggressive_history": "Risk taking case", "conservative_history": "Risk reducing case",
        "neutral_history": "Neutral case", "decision": "**Rating**: Buy",
    }
    assert report_sections({"market_report": None, "risk_debate_state": None}) == {}


def test_hidden_thinking_blocks_never_become_public_report_content():
    assert report_sections({"market_report": "<think>private</think>Public evidence"}) == {
        "market_report": "Public evidence"
    }
    assert report_sections({"market_report": "<think>unfinished private"}) == {}
