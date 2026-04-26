"""Normalize user input into canonical A-share symbol format.

Supported inputs:
- Chinese security name (from local alias map), e.g. 贵州茅台
- Plain 6-digit code, e.g. 600519
- ts_code, e.g. 600519.SH
- prefixed symbol, e.g. sh600519
"""

from __future__ import annotations

from typing import Dict, Optional

from .ashare_utils import infer_exchange_from_code, is_ts_code, normalize_prefixed_symbol

# NOTE: tiny built-in alias map for deterministic unit tests and offline usage.
DEFAULT_CN_NAME_MAP: Dict[str, str] = {
    "贵州茅台": "600519.SH",
    "平安银行": "000001.SZ",
    "宁德时代": "300750.SZ",
}


def normalize_ashare_symbol(raw: str, name_map: Optional[Dict[str, str]] = None) -> str:
    """Normalize arbitrary A-share user input to canonical ts_code format.

    Raises:
        ValueError: if input cannot be normalized deterministically.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty symbol input")

    s = raw.strip()
    aliases = name_map or DEFAULT_CN_NAME_MAP

    # 1) Chinese name lookup first.
    if s in aliases:
        return aliases[s]

    upper_s = s.upper()

    # 2) Canonical ts_code passthrough.
    if is_ts_code(upper_s):
        return upper_s

    # 3) Vendor prefix style (e.g., sh600519).
    prefixed = normalize_prefixed_symbol(upper_s)
    if prefixed:
        return prefixed

    # 4) Pure six-digit code infer exchange by heuristic.
    if upper_s.isdigit() and len(upper_s) == 6:
        ex = infer_exchange_from_code(upper_s)
        if ex:
            return f"{upper_s}.{ex}"

    raise ValueError(f"Unsupported A-share symbol input: {raw}")
