import pytest

from scripts.e2e_mock_ashare_demo import run_demo


@pytest.mark.unit
def test_phase9_mock_demo_returns_expected_sections():
    result = run_demo()
    # NOTE: e2e mock demo should expose both research plan and trader advisory output.
    assert "investment_plan" in result
    assert "trader_investment_plan" in result
    assert "FINAL TRANSACTION PROPOSAL" in result["trader_investment_plan"]
