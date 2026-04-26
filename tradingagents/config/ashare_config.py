"""A-share (China mainland equities) default configuration profile.

This module provides a reusable config template that can be merged into
DEFAULT_CONFIG without forcing immediate behavioral changes in the graph.
"""

from __future__ import annotations

# NOTE: keep this dict flat/serializable so CLI and user scripts can deep-copy it.
ASHARE_CONFIG = {
    # Market identity defaults for CN A-share context.
    "market": {
        "default_market": "CN_A_SHARE",
        "timezone": "Asia/Shanghai",
        "currency": "CNY",
        "code_format": "ts_code",  # e.g. 600519.SH
    },
    # Data-source routing preferences (provider names only, no API keys here).
    "data_sources": {
        "quote_provider": "akshare",
        "fundamentals_provider": "tushare",
        "news_provider": "eastmoney",
        "announcement_provider": "cninfo",
        "social_provider": "eastmoney_guba",
    },
    # A-share risk policy defaults (advisory-only system, no auto execution).
    "risk": {
        "max_single_position": 0.05,
        "max_industry_position": 0.20,
        "forbid_st": True,
        "forbid_suspended": True,
        "forbid_limit_up_buy": True,
        "warn_limit_down_sell": True,
        "require_human_review": True,
    },
    # LLM output controls for Chinese structured reporting.
    "llm": {
        "output_language": "zh-CN",
        "structured_output": True,
    },
}
