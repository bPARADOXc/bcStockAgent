import pytest

from tradingagents.dataflows.stock_code_mapper import normalize_ashare_symbol


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("600519", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
        ("贵州茅台", "600519.SH"),
    ],
)
def test_normalize_ashare_symbol(raw: str, expected: str):
    # NOTE: these are the canonical acceptance examples for A-share onboarding.
    assert normalize_ashare_symbol(raw) == expected


@pytest.mark.unit
def test_normalize_ashare_symbol_rejects_invalid_input():
    # NOTE: mapper must fail fast rather than fabricate ambiguous symbols.
    with pytest.raises(ValueError):
        normalize_ashare_symbol("INVALID")
