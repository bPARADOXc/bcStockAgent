import pytest

from tradingagents.agents.analysts.market_analyst import _build_market_system_message


@pytest.mark.unit
def test_market_prompt_contains_ashare_constraints_and_json_shape():
    msg = _build_market_system_message("", market_label="A股")

    # NOTE: ensure key A-share rules are present in the market prompt.
    assert "涨跌停" in msg
    assert "T+1" in msg
    assert "停复牌" in msg
    assert "ST风险" in msg
    assert "明天上午" in msg
    assert "四分之三" in msg

    # NOTE: ensure required JSON output fields are present.
    for key in (
        '"symbol"',
        '"technical_score"',
        '"risk_flags"',
        '"evidence"',
        '"missing_critical_data"',
        '"confidence_pct"',
    ):
        assert key in msg


@pytest.mark.unit
def test_market_prompt_includes_language_instruction_suffix():
    msg = _build_market_system_message(" Write your entire response in zh-CN.", market_label="A股")
    assert "zh-CN" in msg
