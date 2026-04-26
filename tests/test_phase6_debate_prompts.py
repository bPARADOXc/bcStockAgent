from unittest.mock import MagicMock

import pytest

from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.risk_mgmt.conservative_debator import create_conservative_debator


def _base_state():
    return {
        "market_report": "m",
        "sentiment_report": "s",
        "news_report": "n",
        "fundamentals_report": "f",
        "trader_investment_plan": "t",
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "count": 0,
        },
        "risk_debate_state": {
            "history": "",
            "aggressive_history": "",
            "conservative_history": "",
            "neutral_history": "",
            "latest_speaker": "",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 0,
        },
    }


@pytest.mark.unit
def test_bull_prompt_contains_ashare_constraints():
    llm = MagicMock()
    captured = {}
    
    def _capture(prompt):
        captured["prompt"] = prompt
        return MagicMock(content="ok")
    llm.invoke.side_effect = _capture
    node = create_bull_researcher(llm)
    node(_base_state())
    # NOTE: lock A-share execution-risk wording in bull prompt.
    assert "T+1" in captured["prompt"]
    assert "北向资金" in captured["prompt"]


@pytest.mark.unit
def test_bear_prompt_contains_overhang_risks():
    llm = MagicMock()
    captured = {}
    
    def _capture(prompt):
        captured["prompt"] = prompt
        return MagicMock(content="ok")
    llm.invoke.side_effect = _capture
    node = create_bear_researcher(llm)
    node(_base_state())
    # NOTE: lock capital-overhang language in bear prompt.
    assert "解禁压力" in captured["prompt"]
    assert "T+1" in captured["prompt"]


@pytest.mark.unit
def test_conservative_risk_prompt_contains_veto_terms():
    llm = MagicMock()
    captured = {}
    
    def _capture(prompt):
        captured["prompt"] = prompt
        return MagicMock(content="ok")
    llm.invoke.side_effect = _capture
    node = create_conservative_debator(llm)
    node(_base_state())
    # NOTE: lock hard-veto wording in conservative prompt.
    assert "ST/*ST" in captured["prompt"]
    assert "limit-down" in captured["prompt"]
