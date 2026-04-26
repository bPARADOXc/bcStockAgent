import pytest

from tradingagents.dataflows.config import set_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.interface import route_to_vendor


@pytest.mark.unit
def test_route_to_vendor_normalizes_cn_symbol_for_placeholder_vendor():
    cfg = DEFAULT_CONFIG.copy()
    # NOTE: explicitly force CN mode + CN placeholder for deterministic test behavior.
    cfg["market"] = {"default_market": "CN_A_SHARE"}
    cfg["tool_vendors"] = {"get_stock_data": "cn_placeholder"}
    cfg["provider_fallback_enabled"] = False
    set_config(cfg)

    out = route_to_vendor("get_stock_data", "sh600519", "2026-01-01", "2026-01-10")
    assert "600519.SH" in out
    assert "[CN_PLACEHOLDER]" in out


@pytest.mark.unit
def test_route_to_vendor_respects_disabled_fallback_chain():
    cfg = DEFAULT_CONFIG.copy()
    # NOTE: invalid vendor with fallback disabled should fail fast.
    cfg["tool_vendors"] = {"get_stock_data": "nonexistent_vendor"}
    cfg["provider_fallback_enabled"] = False
    set_config(cfg)

    with pytest.raises(RuntimeError):
        route_to_vendor("get_stock_data", "AAPL", "2026-01-01", "2026-01-10")
