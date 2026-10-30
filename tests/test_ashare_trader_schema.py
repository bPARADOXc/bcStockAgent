import pytest

from tradingagents.agents.schemas import (
    AShareTraderDecision,
    TraderDecisionAction,
    render_ashare_trader_decision,
)


@pytest.mark.unit
def test_render_ashare_trader_decision_includes_required_fields():
    d = AShareTraderDecision(
        symbol="600519.SH",
        decision=TraderDecisionAction.WATCH,
        confidence=55,
        suggested_position_ratio=0.1,
        risk_flags=["T+1"],
        evidence=["成交量放大"],
        human_review_required=True,
        summary="等待回调确认后再评估。",
    )
    md = render_ashare_trader_decision(d)
    # NOTE: ensure mandatory review marker and stop-signal remain in rendered output.
    assert "**Confidence**: 55%" in md
    assert "**Human Review Required**: True" in md
    assert "FINAL TRANSACTION PROPOSAL: **WATCH**" in md
