import pytest

from tradingagents.agents.analysts.fundamentals_analyst import _build_fundamentals_system_message


@pytest.mark.unit
def test_fundamentals_prompt_contains_ashare_financial_risk_terms():
    msg = _build_fundamentals_system_message("", market_label="A股")

    # NOTE: verify A-share-specific accounting/risk concepts are explicitly prompted.
    assert "年报" in msg
    assert "半年报" in msg
    assert "季报" in msg
    assert "商誉减值" in msg
    assert "应收账款" in msg
    assert "存货" in msg


@pytest.mark.unit
def test_fundamentals_prompt_contains_required_json_fields():
    msg = _build_fundamentals_system_message("", market_label="A股")

    # NOTE: ensure required structured output keys are guarded by unit tests.
    for key in (
        '"valuation_score"',
        '"growth_score"',
        '"profitability_score"',
        '"cashflow_score"',
        '"balance_sheet_score"',
        '"financial_quality_risk"',
        '"evidence"',
    ):
        assert key in msg
