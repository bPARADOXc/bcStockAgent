# A-Share Deployment Notes (Phase 8)

This document summarizes the current A-share adaptation status and gives copy-ready configuration examples.

## 1) Current capability scope

- ✅ Symbol normalization to `ts_code` style (`600519.SH`, `000001.SZ`, ...).
- ✅ CN-aware routing with `cn_placeholder` deterministic fallback responses.
- ✅ A-share prompt context for market/news/social/fundamentals analysts.
- ✅ Advisory-only trader schema with mandatory human review flag.
- ❌ No live broker execution (intentionally disabled).
- ❌ Real CN data adapters (AkShare/Tushare/Eastmoney/Cninfo) are planned, placeholders currently used.

## 2) Recommended config template

```python
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()

# NOTE: enable China A-share market mode.
config["market"] = {
    "default_market": "CN_A_SHARE",
    "timezone": "Asia/Shanghai",
    "currency": "CNY",
    "code_format": "ts_code",
}

# NOTE: use placeholder CN vendors in phased rollout.
config["data_vendors"] = {
    "core_stock_apis": "cn_placeholder",
    "technical_indicators": "cn_placeholder",
    "fundamental_data": "cn_placeholder",
    "news_data": "cn_placeholder",
}

# NOTE: avoid cross-vendor fallback for deterministic behavior.
config["provider_fallback_enabled"] = False

# NOTE: Chinese output for user-facing analyst/trader reports.
config["output_language"] = "zh-CN"
```

## 3) Input symbol examples

- `贵州茅台`
- `600519`
- `600519.SH`
- `sh600519`

All should normalize to canonical `600519.SH` in CN mode.

## 4) Trader output policy

The trader must remain **advisory-only** and include:

- `decision`: `buy/sell/hold/watch`
- `confidence`
- `suggested_position_ratio`
- `risk_flags`
- `evidence`
- `human_review_required` (always true by policy)

## 5) Risk reminders (A-share specific)

- T+1 sell constraint
- Limit-up chase risk / limit-down exit risk
- ST/*ST and delisting risk
- Suspension/resumption uncertainty
- Regulatory inquiry and announcement event risk
