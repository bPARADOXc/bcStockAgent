"""LangChain tools for a-stock-data A-share chapters.

Each tool maps to one SKILL.md x.x data chapter and keeps SKILL cautions in the
tool contract: Eastmoney throttling, unit notes, unavailable semantics, and
top-N filtering for broad-market endpoints.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool

from tradingagents.dataflows.a_stock_data_provider import (
    _PROVIDER,
    _format_astock,
    _today,
)
from tradingagents.dataflows.ashare_provider import ProviderEnvelope


def _render(title: str, env: ProviderEnvelope) -> str:
    return _format_astock(title, env)


@tool
def get_cn_mootdx_market_data(
    symbol: Annotated[str, "A-share symbol, e.g. 600519.SH"],
    trade_date: Annotated[str, "Analysis date YYYY-MM-DD"],
) -> str:
    """1.1 mootdx K-line/quote data. TCP can fail by network; unavailable is a data gap, not bearish evidence."""
    return _render("1.1 mootdx market data", _PROVIDER.get_mootdx_market_data(symbol, trade_date))


@tool
def get_cn_tencent_quote(symbol: Annotated[str, "A-share symbol, e.g. 600519.SH"]) -> str:
    """1.2 Tencent quote. Field notes: 39=PE(TTM), 43=amplitude, 46=PB, 47/48=limit-up/down."""
    return _render("1.2 Tencent quote", _PROVIDER.get_tencent_quote_envelope(symbol))


@tool
def get_cn_main_board_momentum_screener(
    min_lot_amount: Annotated[float, "Minimum one-lot amount in CNY"] = 2000.0,
    max_lot_amount: Annotated[float, "Maximum one-lot amount in CNY"] = 3000.0,
    limit: Annotated[int, "Maximum candidates to return"] = 50,
    max_turnover_pct: Annotated[float, "Maximum turnover percent; use 0 to disable the upper cap"] = 10.0,
    volume_growth_days: Annotated[int, "Recent trading days for expanding volume check"] = 3,
    ma_slope_days: Annotated[int, "Recent trading days for MA5/MA10/MA20 upward slope check"] = 3,
    kline_lookback_days: Annotated[int, "Recent calendar days to fetch for K-line context"] = 45,
    recent_position_days: Annotated[int, "Recent trading days for low/mid/high price-position label"] = 20,
    kline_request_interval: Annotated[float, "Seconds to sleep between per-stock K-line checks"] = 1.8,
    eastmoney_min_interval: Annotated[float, "Minimum seconds between Eastmoney requests during screening"] = 1.8,
) -> str:
    """1.4 A-share main-board screener after 14:30: price, change, volume ratio, turnover, float cap, volume curve, and MA slope."""
    turnover_cap = None if max_turnover_pct <= 0 else max_turnover_pct
    return _render(
        "1.4 Main-board momentum screener",
        _PROVIDER.screen_main_board_candidates(
            min_lot_amount=min_lot_amount,
            max_lot_amount=max_lot_amount,
            limit=min(limit, 100),
            max_turnover_pct=turnover_cap,
            volume_growth_days=volume_growth_days,
            ma_slope_days=ma_slope_days,
            kline_lookback_days=kline_lookback_days,
            recent_position_days=recent_position_days,
            kline_request_interval=kline_request_interval,
            eastmoney_min_interval=eastmoney_min_interval,
        ),
    )


@tool
def get_cn_baidu_kline_ma(
    symbol: Annotated[str, "A-share symbol, e.g. 600519.SH"],
    start_date: Annotated[str, "Optional start date YYYY-MM-DD"] = "",
    end_date: Annotated[str, "Optional end date YYYY-MM-DD"] = "",
) -> str:
    """1.3 Baidu K-line with MA5/MA10/MA20. Used as K-line fallback, not the only price source."""
    return _render("1.3 Baidu K-line MA", _PROVIDER.get_baidu_kline_ma(symbol, start_date, end_date))


@tool
def get_cn_eastmoney_reports(symbol: Annotated[str, "A-share symbol"], max_pages: int = 1) -> str:
    """2.1 Eastmoney report list. Returns capped metadata; PDF download is intentionally not automatic."""
    return _render("2.1 Eastmoney reports", _PROVIDER.get_research_reports(symbol, max_pages=max_pages))


@tool
def get_cn_ths_eps_forecast(symbol: Annotated[str, "A-share symbol"]) -> str:
    """2.2 THS consensus EPS. Forecasts with fewer than 3 institutions should be treated cautiously."""
    return _render("2.2 THS EPS forecast", _PROVIDER.get_ths_eps_forecast(symbol))


@tool
def get_cn_iwencai_report_search(query: Annotated[str, "Chinese semantic report-search query"], limit: int = 20) -> str:
    """2.3 iwencai semantic report search. Requires IWENCAI_API_KEY; otherwise returns unavailable."""
    return _render("2.3 iwencai report search", _PROVIDER.get_iwencai_reports(query, limit=min(limit, 50)))


@tool
def get_cn_ths_hot_reason(
    trade_date: Annotated[str, "YYYY-MM-DD, empty means today"] = "",
    symbol: Annotated[str, "Optional A-share symbol to highlight if present"] = "",
    limit: int = 30,
) -> str:
    """3.1 THS hot themes/stocks. Broad market result is capped and target-stock hits are preserved."""
    return _render("3.1 THS hot reason", _PROVIDER.get_ths_hot_reason(trade_date or None, symbol=symbol or None, limit=min(limit, 50)))


@tool
def get_cn_northbound_flow(trade_date: Annotated[str, "YYYY-MM-DD, optional"] = "", history_days: int = 20) -> str:
    """3.2 Northbound flow. Unit is 亿元; zero/NaN may be upstream abnormal and is reliability-marked."""
    return _render("3.2 Northbound flow", _PROVIDER.get_northbound_flow(trade_date or None, min(history_days, 60)))


@tool
def get_cn_concept_blocks(symbol: Annotated[str, "A-share symbol"]) -> str:
    """3.3 Eastmoney concept/industry blocks for the target stock."""
    return _render("3.3 Concept blocks", _PROVIDER.get_concept_blocks(symbol))


@tool
def get_cn_intraday_fund_flow(symbol: Annotated[str, "A-share symbol"]) -> str:
    """3.4 Eastmoney minute fund flow. Raw unit is 元; reports must convert and label units."""
    return _render("3.4 Intraday fund flow", _PROVIDER.get_capital_flow(symbol))


@tool
def get_cn_dragon_tiger_board(
    symbol: Annotated[str, "A-share symbol"],
    trade_date: Annotated[str, "YYYY-MM-DD"],
    look_back: int = 30,
) -> str:
    """3.5 Target-stock dragon tiger board records over a recent window."""
    return _render("3.5 Dragon tiger board", _PROVIDER.get_dragon_tiger(symbol, trade_date, min(look_back, 90)))


@tool
def get_cn_lockup_expiry(
    symbol: Annotated[str, "A-share symbol"],
    trade_date: Annotated[str, "YYYY-MM-DD"],
    forward_days: int = 90,
) -> str:
    """3.6 Lockup expiry calendar. Focus on next 90 days by default."""
    return _render("3.6 Lockup expiry", _PROVIDER.get_lockup_expiry(symbol, trade_date, min(forward_days, 180)))


@tool
def get_cn_industry_comparison(top_n: int = 20) -> str:
    """3.7 Eastmoney industry ranking. Broad-market ranking is capped to top/bottom N."""
    return _render("3.7 Industry comparison", _PROVIDER.get_industry_comparison(min(top_n, 30)))


@tool
def get_cn_daily_dragon_tiger(
    trade_date: Annotated[str, "YYYY-MM-DD, empty means today"] = "",
    min_net_buy_wan: float | None = None,
    limit: int = 20,
) -> str:
    """3.8 Full-market dragon tiger list. Keeps strongest net-buy/sell records only."""
    return _render("3.8 Daily dragon tiger", _PROVIDER.get_daily_dragon_tiger(trade_date or None, min_net_buy_wan, min(limit, 50)))


@tool
def get_cn_signal_summary(symbol: Annotated[str, "A-share symbol"], trade_date: Annotated[str, "YYYY-MM-DD"] = "") -> str:
    """3.9 Combined theme + money confirmation summary for A-share trading context."""
    return _render("3.9 Signal summary", _PROVIDER.get_signal_summary(symbol, trade_date or None))


@tool
def get_cn_margin_trading(symbol: Annotated[str, "A-share symbol"], page_size: int = 30) -> str:
    """4.1 Margin trading details. Leverage signal; cross-check with price/volume."""
    return _render("4.1 Margin trading", _PROVIDER.get_margin_trading(symbol, min(page_size, 50)))


@tool
def get_cn_block_trades(symbol: Annotated[str, "A-share symbol"], page_size: int = 20) -> str:
    """4.2 Block trades. Watch discount/premium, buyers/sellers, and reduce-holding pressure."""
    return _render("4.2 Block trades", _PROVIDER.get_block_trades(symbol, min(page_size, 50)))


@tool
def get_cn_holder_changes(symbol: Annotated[str, "A-share symbol"], page_size: int = 10) -> str:
    """4.3 Holder-count changes. Falling holder count may imply chip concentration, not standalone buy signal."""
    return _render("4.3 Holder changes", _PROVIDER.get_holder_changes(symbol, min(page_size, 30)))


@tool
def get_cn_dividend_history(symbol: Annotated[str, "A-share symbol"], page_size: int = 20) -> str:
    """4.4 Dividend/split history for shareholder-return and quality checks."""
    return _render("4.4 Dividend history", _PROVIDER.get_dividends(symbol, min(page_size, 50)))


@tool
def get_cn_fund_flow_120d(symbol: Annotated[str, "A-share symbol"]) -> str:
    """4.5 120-day daily fund flow. Raw unit is 元; output includes 20/60/120-day summaries."""
    return _render("4.5 Fund flow 120d", _PROVIDER.get_stock_fund_flow_120d(symbol))


@tool
def get_cn_eastmoney_stock_news(symbol: Annotated[str, "A-share symbol"], page_size: int = 20) -> str:
    """5.1 Eastmoney stock news. Empty result can be IP throttling; do not infer no news."""
    return _render("5.1 Eastmoney stock news", _PROVIDER.get_news(symbol, "1900-01-01", _today()))


@tool
def get_cn_cls_telegraph_status() -> str:
    """5.2 CLS old telegraph endpoint status. It is down per SKILL.md; use 5.3 instead."""
    return _render("5.2 CLS telegraph status", _PROVIDER.get_cls_telegraph_status())


@tool
def get_cn_eastmoney_global_news(limit: int = 30) -> str:
    """5.3 Eastmoney 7x24 global news. Broad-market feed is capped and de-duplicated upstream when available."""
    return _render("5.3 Eastmoney global news", _PROVIDER.get_global_news(_today(), limit=min(limit, 50)))


@tool
def get_cn_mootdx_finance_snapshot(symbol: Annotated[str, "A-share symbol"]) -> str:
    """6.1 mootdx finance snapshot. Cross-check with formal financial statements."""
    return _render("6.1 mootdx finance snapshot", _PROVIDER.get_mootdx_finance_snapshot(symbol))


@tool
def get_cn_mootdx_f10(symbol: Annotated[str, "A-share symbol"], category: str = "公司概况") -> str:
    """6.2 mootdx F10 text. Long sections are serialized with provider-side truncation where applicable."""
    return _render("6.2 mootdx F10", _PROVIDER.get_f10(symbol, category=category))


@tool
def get_cn_eastmoney_stock_info(symbol: Annotated[str, "A-share symbol"]) -> str:
    """6.3 Eastmoney stock info: industry, shares, market cap, list date."""
    return _render("6.3 Eastmoney stock info", _PROVIDER.get_eastmoney_stock_info(symbol))


@tool
def get_cn_sina_financial_reports(symbol: Annotated[str, "A-share symbol"], report_type: str = "lrb", num: int = 8) -> str:
    """6.4 Sina financial statements. report_type: lrb income, fzb balance sheet, llb cash flow."""
    return _render("6.4 Sina financial reports", _PROVIDER.get_financial_report(symbol, report_type, min(num, 12)))


@tool
def get_cn_cninfo_announcements(symbol: Annotated[str, "A-share symbol"], page_size: int = 15) -> str:
    """7.1 Cninfo announcements. OrgId is dynamically resolved with fallback; important events are capped."""
    return _render("7.1 Cninfo announcements", _PROVIDER.get_announcements(symbol, min(page_size, 30)))


@tool
def get_cn_f10_announcement_summary(symbol: Annotated[str, "A-share symbol"]) -> str:
    """7.2 F10 latest notice summary. Keeps announcement/dividend/suspension/risk-related passages."""
    return _render("7.2 F10 announcement summary", _PROVIDER.get_f10_announcement_summary(symbol))


@tool
def get_cn_eastmoney_guba_sentiment(symbol: Annotated[str, "A-share symbol"]) -> str:
    """Eastmoney Guba public-page sentiment. Lightweight title scan; contract may be partial."""
    return _render("Reserved Eastmoney Guba sentiment", _PROVIDER.get_eastmoney_guba_sentiment(symbol))


@tool
def get_cn_xueqiu_sentiment(symbol: Annotated[str, "A-share symbol"]) -> str:
    """Xueqiu discussion search. Requires XUEQIU_COOKIE; returned records are partial sentiment evidence."""
    return _render("Reserved Xueqiu sentiment", _PROVIDER.get_xueqiu_sentiment(symbol))
