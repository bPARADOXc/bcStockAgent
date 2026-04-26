"""Phase 9 E2E mock demo for A-share workflow.

This script runs a lightweight end-to-end advisory flow with mocked LLM outputs:
market/social/news/fundamentals reports -> bull/bear debate -> research manager ->
trader advisory decision.

NOTE: no real market APIs or broker integrations are called.
"""

from __future__ import annotations

from pprint import pprint
from unittest.mock import MagicMock

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.schemas import AShareTraderDecision, PortfolioRating, ResearchPlan, TraderDecisionAction
from tradingagents.agents.trader.trader import create_trader


def build_mock_text_llm(text: str) -> MagicMock:
    """Create a text LLM mock used by bull/bear nodes."""
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=text)
    return llm


def build_mock_structured_llm(obj):
    """Create a structured-output-capable mock LLM returning the provided object."""
    structured = MagicMock()
    structured.invoke.return_value = obj
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def run_demo() -> dict:
    # NOTE: fixed mock reports keep demo deterministic for CI and docs snapshots.
    state = {
        "company_of_interest": "600519.SH",
        "market_report": '{"symbol":"600519.SH","technical_score":71,"summary":"趋势偏强"}',
        "sentiment_report": '{"symbol":"600519.SH","sentiment_score":28,"summary":"情绪中性偏多"}',
        "news_report": '{"symbol":"600519.SH","event_importance":64,"summary":"政策面中性"}',
        "fundamentals_report": '{"symbol":"600519.SH","valuation_score":62,"summary":"估值不便宜"}',
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "judge_decision": "",
            "count": 0,
        },
    }

    bull_llm = build_mock_text_llm("多头：政策与业绩共振，维持中等仓位配置。")
    bear_llm = build_mock_text_llm("空头：估值抬升后需防业绩不及预期。")

    rm_llm = build_mock_structured_llm(
        ResearchPlan(
            recommendation=PortfolioRating.HOLD,
            rationale="多空均有依据，短期边际优势不足。",
            strategic_actions="保持观察仓位，等待催化确认。",
        )
    )

    trader_llm = build_mock_structured_llm(
        AShareTraderDecision(
            symbol="600519.SH",
            name="贵州茅台",
            decision=TraderDecisionAction.WATCH,
            confidence=60,
            suggested_position_ratio=0.15,
            stop_loss_reference="跌破关键支撑后减仓",
            take_profit_reference="接近阶段压力位分批止盈",
            risk_flags=["T+1", "高位波动"],
            evidence=["技术面偏强但估值中性", "政策面暂无超预期"],
            human_review_required=True,
            summary="建议观察为主，等待更优赔率。",
        )
    )

    bull_node = create_bull_researcher(bull_llm)
    bear_node = create_bear_researcher(bear_llm)
    rm_node = create_research_manager(rm_llm)
    trader_node = create_trader(trader_llm)

    state.update(bull_node(state))
    state.update(bear_node(state))
    state.update(rm_node(state))

    trader_result = trader_node(
        {
            "company_of_interest": state["company_of_interest"],
            "investment_plan": state["investment_plan"],
        }
    )

    return {
        "investment_plan": state["investment_plan"],
        "trader_investment_plan": trader_result["trader_investment_plan"],
    }


if __name__ == "__main__":
    output = run_demo()
    print("=== Phase 9 A-share E2E Mock Demo ===")
    pprint(output)
