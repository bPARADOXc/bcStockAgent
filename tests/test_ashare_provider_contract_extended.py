import pytest

from tradingagents.dataflows.ashare_provider import NullAShareProvider, ProviderEnvelope


@pytest.mark.unit
def test_provider_envelope_defaults_are_stable():
    env = ProviderEnvelope(status="unavailable", source="x", as_of="")
    # NOTE: contract defaults should always be present for downstream parser safety.
    assert env.data == {}
    assert env.errors == []
    assert env.evidence == []
    assert env.contract_fulfilled is False
    assert env.fallback_level == "none"

    ok_env = ProviderEnvelope(status="ok", source="x", as_of="")
    assert ok_env.contract_fulfilled is True
    assert ok_env.fallback_level == "none"


@pytest.mark.unit
def test_null_provider_all_methods_return_unavailable():
    p = NullAShareProvider()

    # NOTE: verify every exposed method returns deterministic unavailable status.
    responses = [
        p.get_quote("600519.SH"),
        p.get_fundamentals("600519.SH"),
        p.get_news("600519.SH", "2026-01-01", "2026-01-07"),
        p.get_social("600519.SH", "2026-01-01", "2026-01-07"),
    ]
    assert all(r.status == "unavailable" for r in responses)
    assert all(r.source == "null_ashare_provider" for r in responses)
