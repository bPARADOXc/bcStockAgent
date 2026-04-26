import pytest

from tradingagents.dataflows.ashare_provider import NullAShareProvider


@pytest.mark.unit
def test_null_ashare_provider_returns_unavailable_envelope():
    provider = NullAShareProvider()

    # NOTE: contract requires explicit unavailable status with diagnostics.
    quote = provider.get_quote("600519.SH")
    assert quote.status == "unavailable"
    assert quote.source == "null_ashare_provider"
    assert isinstance(quote.errors, list)
    assert quote.data == {}
