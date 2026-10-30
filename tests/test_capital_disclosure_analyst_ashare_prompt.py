import pytest

from tradingagents.agents.analysts.capital_flow_analyst import _build_capital_flow_system_message
from tradingagents.agents.analysts.disclosure_research_analyst import _build_disclosure_system_message


@pytest.mark.unit
def test_capital_flow_prompt_contains_overnight_tool_coverage_and_schema_keys():
    msg = _build_capital_flow_system_message("", market_label="A股")

    assert "今天下午/尾盘买，明天上午卖" in msg
    assert "四分之三" in msg
    assert "资金确认 + 板块共振 + 尾盘承接" in msg

    for key in (
        '"fund_flow_contract"',
        '"liquidity_exit_risk"',
        '"tomorrow_morning_flow_plan"',
        '"tool_coverage"',
        '"missing_critical_data"',
        '"confidence_pct"',
    ):
        assert key in msg


@pytest.mark.unit
def test_disclosure_prompt_contains_overnight_veto_and_schema_keys():
    msg = _build_disclosure_system_message("", market_label="A股")

    assert "今天下午/尾盘买，明天上午卖" in msg
    assert "四分之三" in msg
    assert "监管立案" in msg
    assert "盘后公告风险" in msg

    for key in (
        '"overnight_disclosure_risk"',
        '"next_morning_catalyst"',
        '"tool_coverage"',
        '"missing_critical_data"',
        '"confidence_pct"',
    ):
        assert key in msg
