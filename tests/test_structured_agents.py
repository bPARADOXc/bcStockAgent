"""Tests for structured-output agents (Trader and Research Manager)."""

from unittest.mock import MagicMock

import pytest

from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.schemas import (
    AShareTraderDecision,
    PortfolioRating,
    ResearchPlan,
    TraderDecisionAction,
    render_ashare_trader_decision,
    render_research_plan,
)
from tradingagents.agents.trader.trader import create_trader


@pytest.mark.unit
class TestRenderTraderDecision:
    def test_required_fields_render(self):
        d = AShareTraderDecision(
            symbol="600519.SH",
            decision=TraderDecisionAction.HOLD,
            confidence=63,
            suggested_position_ratio=0.2,
            human_review_required=True,
            summary="估值与景气基本匹配，等待更优胜率。",
        )
        md = render_ashare_trader_decision(d)
        assert "**Decision**: hold" in md
        assert "**Confidence**: 63%" in md
        assert "**Human Review Required**: True" in md
        assert "FINAL TRANSACTION PROPOSAL: **HOLD**" in md


@pytest.mark.unit
class TestRenderResearchPlan:
    def test_required_fields(self):
        p = ResearchPlan(
            recommendation=PortfolioRating.OVERWEIGHT,
            rationale="Bull case carried; tailwinds intact.",
            strategic_actions="Enter near the close only if funds hold; exit tomorrow morning.",
            confidence=61,
        )
        md = render_research_plan(p)
        assert "**Recommendation**: Overweight" in md
        assert "**Rationale**: Bull case carried" in md
        assert "**Strategic Actions**: Enter near the close" in md
        assert "**Confidence**: 61%" in md


def _make_trader_state():
    return {
        "company_of_interest": "600519.SH",
        "investment_plan": "**Recommendation**: Buy\n**Rationale**: ...\n**Strategic Actions**: ...",
    }


def _structured_trader_llm(captured: dict, decision: AShareTraderDecision | None = None):
    # NOTE: return AShareTraderDecision to match phase-6 trader schema.
    if decision is None:
        decision = AShareTraderDecision(
            symbol="600519.SH",
            decision=TraderDecisionAction.BUY,
            confidence=72,
            suggested_position_ratio=0.3,
            risk_flags=["T+1"],
            evidence=["MACD金叉", "北向资金净流入"],
            human_review_required=True,
            summary="趋势与资金共振，但需人工复核执行风险。",
        )

    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: captured.__setitem__("prompt", prompt) or decision
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.unit
class TestTraderAgent:
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        decision = AShareTraderDecision(
            symbol="600519.SH",
            decision=TraderDecisionAction.BUY,
            confidence=78,
            suggested_position_ratio=0.35,
            stop_loss_reference="跌破20日线",
            take_profit_reference="前高附近分批止盈",
            risk_flags=["T+1", "涨跌停执行风险"],
            evidence=["量价齐升"],
            human_review_required=True,
            summary="建议分批参与并严格风控。",
        )
        llm = _structured_trader_llm(captured, decision)
        trader = create_trader(llm)
        result = trader(_make_trader_state())
        plan = result["trader_investment_plan"]
        assert "**Decision**: buy" in plan
        assert "**Confidence**: 78%" in plan
        assert "**Suggested Position Ratio**: 0.35" in plan
        assert "FINAL TRANSACTION PROPOSAL: **BUY**" in plan
        assert plan in result["messages"][0].content

    def test_prompt_mentions_ashare_constraints(self):
        captured = {}
        llm = _structured_trader_llm(captured)
        trader = create_trader(llm)
        trader(_make_trader_state())
        prompt = captured["prompt"]
        assert any("T+1" in m["content"] for m in prompt)

    def test_falls_back_to_freetext_when_structured_unavailable(self):
        plain_response = (
            "**Decision**: watch\n\n"
            "**Human Review Required**: True\n\n"
            "FINAL TRANSACTION PROPOSAL: **WATCH**"
        )
        llm = MagicMock()
        llm.with_structured_output.side_effect = NotImplementedError("provider unsupported")
        llm.invoke.return_value = MagicMock(content=plain_response)
        trader = create_trader(llm)
        result = trader(_make_trader_state())
        assert result["trader_investment_plan"] == plain_response


# Research Manager tests

def _make_rm_state():
    return {
        "company_of_interest": "NVDA",
        "investment_debate_state": {
            "history": "Bull and bear arguments here.",
            "bull_history": "Bull says...",
            "bear_history": "Bear says...",
            "current_response": "",
            "judge_decision": "",
            "count": 1,
        },
    }


def _structured_rm_llm(captured: dict, plan: ResearchPlan | None = None):
    if plan is None:
        plan = ResearchPlan(
            recommendation=PortfolioRating.HOLD,
            rationale="Balanced view across both sides.",
            strategic_actions="Hold current position; reassess after earnings.",
        )
    structured = MagicMock()
    structured.invoke.side_effect = lambda prompt: captured.__setitem__("prompt", prompt) or plan
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


@pytest.mark.unit
class TestResearchManagerAgent:
    def test_structured_path_produces_rendered_markdown(self):
        captured = {}
        plan = ResearchPlan(
            recommendation=PortfolioRating.OVERWEIGHT,
            rationale="Bull case is stronger; AI tailwind intact.",
            strategic_actions="Enter near the close only if volume holds; sell tomorrow morning.",
            confidence=66,
        )
        llm = _structured_rm_llm(captured, plan)
        rm = create_research_manager(llm)
        result = rm(_make_rm_state())
        ip = result["investment_plan"]
        assert "**Recommendation**: Overweight" in ip
        assert "**Rationale**: Bull case" in ip
        assert "**Strategic Actions**: Enter near the close" in ip
        assert "**Confidence**: 66%" in ip

    def test_prompt_uses_5_tier_rating_scale(self):
        captured = {}
        llm = _structured_rm_llm(captured)
        rm = create_research_manager(llm)
        rm(_make_rm_state())
        prompt = captured["prompt"]
        for tier in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
            assert f"**{tier}**" in prompt
