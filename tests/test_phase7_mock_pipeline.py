from unittest.mock import MagicMock

import pytest

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.schemas import AShareTraderDecision, PortfolioRating, ResearchPlan, TraderDecisionAction
from tradingagents.agents.trader.trader import create_trader


@pytest.mark.unit
def test_mock_pipeline_bull_bear_to_trader_runs_end_to_end():
    # NOTE: lightweight mock pipeline for phase-7 integration sanity.
    text_llm = MagicMock()
    text_llm.invoke.return_value = MagicMock(content="mock argument")

    rm_structured = MagicMock()
    rm_structured.invoke.return_value = ResearchPlan(
        recommendation=PortfolioRating.HOLD,
        rationale="多空因素相对均衡。",
        strategic_actions="控制仓位，等待确认。",
    )
    rm_llm = MagicMock()
    rm_llm.with_structured_output.return_value = rm_structured

    trader_structured = MagicMock()
    trader_structured.invoke.return_value = AShareTraderDecision(
        symbol="600519.SH",
        decision=TraderDecisionAction.WATCH,
        confidence=58,
        suggested_position_ratio=0.1,
        risk_flags=["T+1"],
        evidence=["量能不足"],
        human_review_required=True,
        summary="先观察。",
    )
    trader_llm = MagicMock()
    trader_llm.with_structured_output.return_value = trader_structured

    state = {
        "company_of_interest": "600519.SH",
        "market_report": "market",
        "sentiment_report": "sent",
        "news_report": "news",
        "fundamentals_report": "fund",
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 0,
        },
    }

    bull_node = create_bull_researcher(text_llm)
    bear_node = create_bear_researcher(text_llm)
    rm_node = create_research_manager(rm_llm)
    trader_node = create_trader(trader_llm)

    state.update(bull_node(state))
    state.update(bear_node(state))
    state.update(rm_node(state))
    out = trader_node({
        "company_of_interest": state["company_of_interest"],
        "investment_plan": state["investment_plan"],
    })

    assert "FINAL TRANSACTION PROPOSAL" in out["trader_investment_plan"]
    assert "**Human Review Required**: True" in out["trader_investment_plan"]
