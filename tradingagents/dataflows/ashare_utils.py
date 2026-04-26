"""Utility helpers for China A-share symbol conventions and exchange inference."""

from __future__ import annotations

import re
from typing import Optional

# NOTE: canonical internal symbol format is six-digit code + exchange suffix.
TS_CODE_PATTERN = re.compile(r"^(?P<code>\d{6})\.(?P<ex>SH|SZ|BJ)$")
PREFIX_CODE_PATTERN = re.compile(r"^(?P<ex>SH|SZ|BJ)(?P<code>\d{6})$")


def infer_exchange_from_code(code: str) -> Optional[str]:
    """Infer mainland exchange from a 6-digit stock code.

    Heuristic follows common market conventions:
    - SH: 600/601/603/605/688/689/900...
    - SZ: 000/001/002/003/300/301/200...
    - BJ: 4xx/8xx prefixes (simplified fallback)
    """
    if len(code) != 6 or not code.isdigit():
        return None

    # NOTE: simplified production-safe heuristic; can be replaced by symbol master data.
    if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
        return "SH"
    if code.startswith(("000", "001", "002", "003", "300", "301", "200")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return None


def is_ts_code(symbol: str) -> bool:
    """Return True when symbol is in canonical ts_code style, e.g. 600519.SH."""
    return bool(TS_CODE_PATTERN.match(symbol.upper().strip()))


def normalize_prefixed_symbol(raw: str) -> Optional[str]:
    """Normalize vendor-prefixed symbols like sh600519 / sz000001 / bj430047."""
    s = raw.strip().upper()
    s = s.replace(".", "")
    match = PREFIX_CODE_PATTERN.match(s)
    if not match:
        return None
    code = match.group("code")
    ex = match.group("ex")
    return f"{code}.{ex}"
