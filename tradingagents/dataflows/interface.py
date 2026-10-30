from typing import Tuple

# Import from vendor-specific modules
from .y_finance import (
    get_YFin_data_online,
    get_stock_stats_indicators_window,
    get_fundamentals as get_yfinance_fundamentals,
    get_balance_sheet as get_yfinance_balance_sheet,
    get_cashflow as get_yfinance_cashflow,
    get_income_statement as get_yfinance_income_statement,
    get_insider_transactions as get_yfinance_insider_transactions,
)
from .yfinance_news import get_news_yfinance, get_global_news_yfinance
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_fundamentals as get_alpha_vantage_fundamentals,
    get_balance_sheet as get_alpha_vantage_balance_sheet,
    get_cashflow as get_alpha_vantage_cashflow,
    get_income_statement as get_alpha_vantage_income_statement,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news,
)
from .cn_data_placeholder import (
    get_cn_stock_data,
    get_cn_indicator,
    get_cn_fundamentals,
    get_cn_balance_sheet,
    get_cn_cashflow,
    get_cn_income_statement,
    get_cn_news,
    get_cn_global_news,
    get_cn_insider_transactions,
)
from .a_stock_data_provider import (
    get_astock_stock_data,
    get_astock_indicator,
    get_astock_fundamentals,
    get_astock_balance_sheet,
    get_astock_cashflow,
    get_astock_income_statement,
    get_astock_news,
    get_astock_global_news,
    get_astock_insider_equivalent,
)
from .alpha_vantage_common import AlphaVantageRateLimitError
from .stock_code_mapper import normalize_ashare_symbol

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "fundamental_data": {
        "description": "Company fundamentals",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement"
        ]
    },
    "news_data": {
        "description": "News and insider data",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "yfinance",
    "alpha_vantage",
    "a_stock_data",
    "cn_placeholder",
]

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "a_stock_data": get_astock_stock_data,
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "cn_placeholder": get_cn_stock_data,
    },
    # technical_indicators
    "get_indicators": {
        "a_stock_data": get_astock_indicator,
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "cn_placeholder": get_cn_indicator,
    },
    # fundamental_data
    "get_fundamentals": {
        "a_stock_data": get_astock_fundamentals,
        "alpha_vantage": get_alpha_vantage_fundamentals,
        "yfinance": get_yfinance_fundamentals,
        "cn_placeholder": get_cn_fundamentals,
    },
    "get_balance_sheet": {
        "a_stock_data": get_astock_balance_sheet,
        "alpha_vantage": get_alpha_vantage_balance_sheet,
        "yfinance": get_yfinance_balance_sheet,
        "cn_placeholder": get_cn_balance_sheet,
    },
    "get_cashflow": {
        "a_stock_data": get_astock_cashflow,
        "alpha_vantage": get_alpha_vantage_cashflow,
        "yfinance": get_yfinance_cashflow,
        "cn_placeholder": get_cn_cashflow,
    },
    "get_income_statement": {
        "a_stock_data": get_astock_income_statement,
        "alpha_vantage": get_alpha_vantage_income_statement,
        "yfinance": get_yfinance_income_statement,
        "cn_placeholder": get_cn_income_statement,
    },
    # news_data
    "get_news": {
        "a_stock_data": get_astock_news,
        "alpha_vantage": get_alpha_vantage_news,
        "yfinance": get_news_yfinance,
        "cn_placeholder": get_cn_news,
    },
    "get_global_news": {
        "a_stock_data": get_astock_global_news,
        "yfinance": get_global_news_yfinance,
        "alpha_vantage": get_alpha_vantage_global_news,
        "cn_placeholder": get_cn_global_news,
    },
    "get_insider_transactions": {
        "a_stock_data": get_astock_insider_equivalent,
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        "cn_placeholder": get_cn_insider_transactions,
    },
}

# NOTE: methods whose first positional argument is a ticker/symbol.
_SYMBOL_METHODS = {
    "get_stock_data",
    "get_indicators",
    "get_fundamentals",
    "get_balance_sheet",
    "get_cashflow",
    "get_income_statement",
    "get_news",
    "get_insider_transactions",
}


def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")


def _is_cn_ashare_mode() -> bool:
    """Return True when config indicates CN A-share as default market."""
    config = get_config()
    market_cfg = config.get("market", {})
    default_market = str(market_cfg.get("default_market", "")).upper()
    return default_market == "CN_A_SHARE"


def _normalize_symbol_args(method: str, args: Tuple, kwargs: dict) -> Tuple[Tuple, dict]:
    """Normalize symbol input in CN A-share mode for symbol-carrying methods."""
    if method not in _SYMBOL_METHODS or not _is_cn_ashare_mode():
        return args, kwargs

    # NOTE: all symbol methods currently pass ticker as first positional arg.
    if not args:
        return args, kwargs

    symbol_raw = args[0]
    if not isinstance(symbol_raw, str):
        return args, kwargs

    try:
        normalized = normalize_ashare_symbol(symbol_raw)
    except ValueError:
        # NOTE: keep legacy behavior if input is not a valid A-share symbol.
        return args, kwargs

    new_args = (normalized, *args[1:])
    return new_args, kwargs


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation.

    Fallback behavior is controlled by config key `provider_fallback_enabled`
    (default True to preserve historical behavior).
    """
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(',') if v.strip()]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Normalize args for CN mode before vendor call.
    args, kwargs = _normalize_symbol_args(method, args, kwargs)

    # Build vendor chain.
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_enabled = bool(get_config().get("provider_fallback_enabled", True))

    if fallback_enabled:
        fallback_vendors = primary_vendors.copy()
        for vendor in all_available_vendors:
            if vendor not in fallback_vendors:
                fallback_vendors.append(vendor)
    else:
        fallback_vendors = primary_vendors

    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        impl_func = vendor_impl[0] if isinstance(vendor_impl, list) else vendor_impl

        try:
            return impl_func(*args, **kwargs)
        except AlphaVantageRateLimitError:
            continue  # Only rate limits trigger fallback

    raise RuntimeError(f"No available vendor for '{method}'")
