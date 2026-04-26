"""CN placeholder provider methods used during phased A-share migration.

These functions intentionally return explicit "unavailable" payloads instead of
fabricating data, so downstream analysts can handle missing data safely.
"""

from __future__ import annotations


def get_cn_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    # NOTE: phase-2 placeholder, real AkShare/Tushare adapter comes in next phase.
    return (
        f"[CN_PLACEHOLDER] stock data unavailable for {symbol} "
        f"between {start_date} and {end_date}."
    )


def get_cn_indicator(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    # NOTE: phase-2 placeholder, indicator service will be implemented later.
    return (
        f"[CN_PLACEHOLDER] indicator '{indicator}' unavailable for {symbol} "
        f"as of {curr_date} (look_back_days={look_back_days})."
    )


def get_cn_fundamentals(ticker: str, curr_date: str) -> str:
    # NOTE: phase-2 placeholder; keep explicit unavailable semantics.
    return f"[CN_PLACEHOLDER] fundamentals unavailable for {ticker} as of {curr_date}."


def get_cn_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    # NOTE: phase-2 placeholder; keep explicit unavailable semantics.
    return f"[CN_PLACEHOLDER] balance sheet unavailable for {ticker} (freq={freq})."


def get_cn_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    # NOTE: phase-2 placeholder; keep explicit unavailable semantics.
    return f"[CN_PLACEHOLDER] cashflow unavailable for {ticker} (freq={freq})."


def get_cn_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    # NOTE: phase-2 placeholder; keep explicit unavailable semantics.
    return f"[CN_PLACEHOLDER] income statement unavailable for {ticker} (freq={freq})."


def get_cn_news(ticker: str, start_date: str, end_date: str) -> str:
    # NOTE: phase-2 placeholder; keep explicit unavailable semantics.
    return (
        f"[CN_PLACEHOLDER] company news unavailable for {ticker} "
        f"between {start_date} and {end_date}."
    )


def get_cn_global_news(curr_date: str, look_back_days: int = 7, limit: int = 5) -> str:
    # NOTE: phase-2 placeholder; keep explicit unavailable semantics.
    return (
        f"[CN_PLACEHOLDER] macro/policy news unavailable as of {curr_date} "
        f"(look_back_days={look_back_days}, limit={limit})."
    )


def get_cn_insider_transactions(ticker: str) -> str:
    # NOTE: phase-2 placeholder; keep explicit unavailable semantics.
    return f"[CN_PLACEHOLDER] insider-equivalent data unavailable for {ticker}."
