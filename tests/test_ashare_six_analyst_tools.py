import inspect
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.utils import ashare_data_tools
from tradingagents.dataflows.a_stock_data_provider import AStockDataProvider
from tradingagents.graph.conditional_logic import ConditionalLogic
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph


@pytest.mark.unit
def test_hot_reason_filter_caps_records_and_preserves_target(monkeypatch):
    rows = [
        {"代码": f"{i:06d}", "名称": f"S{i}", "涨幅%": i, "换手率%": i, "成交额": i, "题材归因": "AI+算力"}
        for i in range(40)
    ]
    rows.append({"代码": "600519", "名称": "贵州茅台", "涨幅%": 1, "换手率%": 1, "成交额": 1, "题材归因": "白酒+消费"})
    provider = AStockDataProvider()
    monkeypatch.setattr(provider, "ths_hot_reason", lambda trade_date=None: rows)

    env = provider.get_ths_hot_reason("2026-01-02", symbol="600519.SH", limit=30)

    assert env.status == "ok"
    assert len(env.data["records"]) == 30
    assert env.data["target_records"][0]["代码"] == "600519"
    assert env.data["theme_summary"][0]["theme"] == "AI"


@pytest.mark.unit
def test_stock_fund_flow_120d_summary_uses_yuan_units(monkeypatch):
    provider = AStockDataProvider()
    monkeypatch.setattr(
        provider,
        "stock_fund_flow_120d",
        lambda code: [{"date": f"2026-01-{i:02d}", "main_net": 10_000_000, "small_net": 0, "mid_net": 0, "large_net": 0, "super_net": 0} for i in range(1, 31)],
    )

    env = provider.get_stock_fund_flow_120d("600519.SH")

    assert env.status == "ok"
    assert env.data["summary"]["main_net_20d_yi"] == 2.0
    assert env.data["summary"]["unit_raw"] == "元"


@pytest.mark.unit
def test_intraday_fund_flow_falls_back_to_120d(monkeypatch):
    provider = AStockDataProvider()
    monkeypatch.setattr(provider, "eastmoney_fund_flow_minute", MagicMock(side_effect=RuntimeError("minute down")))
    monkeypatch.setattr(
        provider,
        "stock_fund_flow_120d",
        lambda code: [{"date": "2026-01-01", "main_net": 10_000_000, "small_net": 0, "mid_net": 0, "large_net": 0, "super_net": 0}],
    )

    env = provider.get_capital_flow("600519.SH")

    assert env.status == "ok"
    assert env.source == "eastmoney_fund_flow_minute_fallback_120d"
    assert env.contract_fulfilled is False
    assert env.fallback_level == "partial"
    assert "minute down" in env.errors[0]


@pytest.mark.unit
def test_stock_fund_flow_falls_back_to_quote_context(monkeypatch):
    provider = AStockDataProvider()
    monkeypatch.setattr(provider, "stock_fund_flow_120d", MagicMock(side_effect=RuntimeError("push2his down")))
    monkeypatch.setattr(provider, "tencent_quote", lambda codes: {"600519": {"price": 1688, "amount_wan": 123456, "turnover_pct": 0.88}})
    monkeypatch.setattr(
        provider,
        "_sina_kline_records",
        lambda code, datalen=40: [{"Date": "2026-01-01", "Amount": 1000, "Volume": 2000}],
    )

    env = provider.get_stock_fund_flow_120d("600519.SH")

    assert env.status == "ok"
    assert env.source == "eastmoney_fund_flow_quote_fallback"
    assert env.data["fund_flow_available"] is False
    assert env.contract_fulfilled is False
    assert env.fallback_level == "diagnostic"
    assert "push2his down" in env.errors[0]


@pytest.mark.unit
def test_industry_comparison_falls_back_to_ths_hot_reason(monkeypatch):
    provider = AStockDataProvider()
    monkeypatch.setattr(provider, "ths_hot_reason", lambda trade_date=None: [{"代码": "600519", "名称": "贵州茅台", "题材归因": "白酒+消费"}])
    monkeypatch.setattr(ashare_data_tools._PROVIDER, "get_industry_comparison", provider.get_industry_comparison)
    monkeypatch.setattr("tradingagents.dataflows.a_stock_data_provider.em_get", MagicMock(side_effect=RuntimeError("industry down")))

    env = provider.get_industry_comparison(5)

    assert env.status == "ok"
    assert env.source == "eastmoney_industry_comparison_fallback_ths_hot"
    assert env.data["theme_summary"][0]["theme"] == "白酒"


@pytest.mark.unit
def test_guba_sentiment_parses_public_page(monkeypatch):
    provider = AStockDataProvider()

    html = """
    <a href="/news,600519,123.html" title="利好不断 看多"></a>
    <a href="/news,600519,124.html" title="风险提示 减持压力"></a>
    """
    monkeypatch.setattr("tradingagents.dataflows.a_stock_data_provider.requests.get", lambda *args, **kwargs: type("Resp", (), {"text": html, "encoding": "utf-8", "apparent_encoding": "utf-8", "raise_for_status": lambda self: None})())

    guba = provider.get_eastmoney_guba_sentiment("600519.SH")

    assert guba.status == "ok"
    assert guba.source == "eastmoney_guba_sentiment"
    assert guba.contract_fulfilled is False
    assert guba.fallback_level == "partial"
    assert guba.data["summary"]["post_count"] == 2


@pytest.mark.unit
def test_xueqiu_source_requires_cookie(monkeypatch):
    monkeypatch.delenv("XUEQIU_COOKIE", raising=False)
    provider = AStockDataProvider()
    xueqiu = provider.get_xueqiu_sentiment("600519.SH")

    assert xueqiu.status == "unavailable"
    assert "XUEQIU_COOKIE" in xueqiu.errors[0]


@pytest.mark.unit
def test_chapter_tool_names_exist():
    expected = {
        "get_cn_mootdx_market_data",
        "get_cn_tencent_quote",
        "get_cn_baidu_kline_ma",
        "get_cn_eastmoney_reports",
        "get_cn_ths_eps_forecast",
        "get_cn_iwencai_report_search",
        "get_cn_ths_hot_reason",
        "get_cn_northbound_flow",
        "get_cn_concept_blocks",
        "get_cn_intraday_fund_flow",
        "get_cn_dragon_tiger_board",
        "get_cn_lockup_expiry",
        "get_cn_industry_comparison",
        "get_cn_daily_dragon_tiger",
        "get_cn_signal_summary",
        "get_cn_margin_trading",
        "get_cn_block_trades",
        "get_cn_holder_changes",
        "get_cn_dividend_history",
        "get_cn_fund_flow_120d",
        "get_cn_eastmoney_stock_news",
        "get_cn_cls_telegraph_status",
        "get_cn_eastmoney_global_news",
        "get_cn_mootdx_finance_snapshot",
        "get_cn_mootdx_f10",
        "get_cn_eastmoney_stock_info",
        "get_cn_sina_financial_reports",
        "get_cn_cninfo_announcements",
        "get_cn_f10_announcement_summary",
        "get_cn_eastmoney_guba_sentiment",
        "get_cn_xueqiu_sentiment",
    }

    assert expected.issubset(set(dir(ashare_data_tools)))


@pytest.mark.unit
def test_graph_defaults_and_state_include_six_analyst_reports():
    default_analysts = inspect.signature(TradingAgentsGraph.__init__).parameters["selected_analysts"].default
    state = Propagator().create_initial_state("600519.SH", "2026-01-02")
    logic = ConditionalLogic()

    assert default_analysts == ["market", "social", "news", "fundamentals", "capital_flow", "disclosure"]
    assert state["capital_flow_report"] == ""
    assert state["disclosure_report"] == ""
    assert hasattr(logic, "should_continue_capital_flow")
    assert hasattr(logic, "should_continue_disclosure")
