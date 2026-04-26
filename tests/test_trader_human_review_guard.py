import pytest

from tradingagents.agents.schemas import (
    AShareTraderDecision,
    TraderDecisionAction,
    render_ashare_trader_decision,
)


@pytest.mark.unit
def test_ashare_trader_decision_defaults_human_review_true():
    d = AShareTraderDecision(
        symbol="600519.SH",
        decision=TraderDecisionAction.BUY,
        confidence=80,
        suggested_position_ratio=0.2,
        summary="测试",
    )
    # NOTE: advisory workflow must default to human review required.
    assert d.human_review_required is True


@pytest.mark.unit
def test_render_ashare_trader_decision_includes_risk_and_evidence_lines():
    d = AShareTraderDecision(
        symbol="600519.SH",
        decision=TraderDecisionAction.SELL,
        confidence=62,
        suggested_position_ratio=0.0,
        risk_flags=["ST风险", "跌停流动性风险"],
        evidence=["公告问询", "业绩预警"],
        human_review_required=True,
        summary="先规避风险。",
    )
    md = render_ashare_trader_decision(d)
    assert "**Risk Flags**:" in md
    assert "**Evidence**:" in md
