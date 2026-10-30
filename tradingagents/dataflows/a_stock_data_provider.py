"""A-share data provider adapted from simonlin1212/a-stock-data.

The provider keeps live CN market integrations behind ``ProviderEnvelope`` so
agent tools can consume deterministic strings while callers still get structured
diagnostics and evidence when integrations fail.
"""

from __future__ import annotations

import json
import math
import os
import random
import re
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import StringIO
from typing import Any, Callable, Dict, Iterable, List, Optional

import pandas as pd
import requests

from .ashare_provider import ProviderEnvelope
from .config import get_config
from .stock_code_mapper import normalize_ashare_symbol


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT_API = "https://reportapi.eastmoney.com/report/list"
REPORT_PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"

EM_SESSION = requests.Session()
EM_SESSION.headers.update(
    {
        "User-Agent": UA,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "close",
    }
)
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]
_CNINFO_ORGID_MAP: Dict[str, str] = {}
DEFAULT_STOCK_LIMIT = 30
DEFAULT_EVENT_LIMIT = 15
DEFAULT_REPORT_LIMIT = 10


def normalize_to_code(symbol: str) -> str:
    """Normalize A-share input to a pure six-digit code."""
    normalized = normalize_ashare_symbol(symbol)
    return normalized.split(".", 1)[0]


def get_prefix(code: str) -> str:
    """Return vendor market prefix for a pure six-digit A-share code."""
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith("8"):
        return "bj"
    return "sz"


def get_market_id(code: str) -> int:
    """Return Eastmoney market id used in secid values."""
    return 1 if code.startswith(("6", "9")) else 0


def get_secid(code: str) -> str:
    """Return Eastmoney secid, e.g. 1.600519."""
    return f"{get_market_id(code)}.{code}"


def _eastmoney_url_candidates(url: str) -> list[str]:
    """Return conservative Eastmoney host fallbacks for flaky push2/push2his edges."""
    candidates = [url]
    if url.startswith("https://push2.eastmoney.com/"):
        suffix = url[len("https://push2.eastmoney.com/") :]
        candidates.extend(
            [
                "http://push2.eastmoney.com/" + suffix,
                "https://82.push2.eastmoney.com/" + suffix,
                "https://80.push2.eastmoney.com/" + suffix,
            ]
        )
    elif url.startswith("https://push2his.eastmoney.com/"):
        suffix = url[len("https://push2his.eastmoney.com/") :]
        candidates.append("http://push2his.eastmoney.com/" + suffix)
    return list(dict.fromkeys(candidates))


def em_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    max_retries: int = 3,
    **kwargs,
):
    """Eastmoney unified HTTP entry with throttling and session reuse."""
    last_exc: Exception | None = None
    candidates = _eastmoney_url_candidates(url)
    for attempt in range(max(max_retries, 1)):
        request_url = candidates[min(attempt, len(candidates) - 1)]
        wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
        if wait > 0:
            time.sleep(wait + random.uniform(0.1, 0.5))
        try:
            return EM_SESSION.get(request_url, params=params, headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            EM_SESSION.close()
            if attempt >= max_retries - 1:
                raise
            time.sleep(0.8 * (attempt + 1) + random.uniform(0.1, 0.5))
        finally:
            _em_last_call[0] = time.time()
    if last_exc:
        raise last_exc
    raise RuntimeError("Eastmoney request failed without an exception")

def em_json_with_status_retries(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    max_retries: int = 5,
) -> dict:
    """Eastmoney JSON GET with explicit retry for 429/502/503/504."""
    last_error: Exception | None = None
    retry_status = {429, 502, 503, 504}
    for attempt in range(max(max_retries, 1)):
        try:
            response = em_get(url, params=params, headers=headers, timeout=timeout, max_retries=1)
            if response.status_code in retry_status:
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                if attempt + 1 < max(max_retries, 1):
                    delay = min(1.0 * (2**attempt), 30.0) + random.uniform(0.2, 0.8)
                    time.sleep(delay)
                    continue
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < max(max_retries, 1):
                delay = min(1.0 * (2**attempt), 30.0) + random.uniform(0.2, 0.8)
                time.sleep(delay)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("Eastmoney JSON request failed without an exception")


def eastmoney_datacenter(
    report_name: str,
    columns: str = "ALL",
    filter_str: str = "",
    page_size: int = 50,
    sort_columns: str = "",
    sort_types: str = "-1",
) -> list[dict]:
    """Eastmoney datacenter shared query helper."""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    r.raise_for_status()
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def _cninfo_ts_to_date(ts: Any) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
    return str(ts)[:10] if ts else ""


def _format_records(title: str, records: Iterable[dict]) -> str:
    rows = list(records)
    if not rows:
        return f"{title}\nNo records."
    return title + "\n\n" + pd.DataFrame(rows).to_csv(index=False)


def _limit_records(records: Iterable[dict], limit: int) -> list[dict]:
    return list(records)[: max(limit, 0)]


def _limit_abs(records: Iterable[dict], key: str, limit: int) -> list[dict]:
    rows = list(records)
    return sorted(rows, key=lambda r: abs(_safe_float(r.get(key))), reverse=True)[:limit]


def _theme_summary(records: list[dict], field: str = "题材归因", limit: int = 12) -> list[dict]:
    counts: dict[str, int] = {}
    for row in records:
        raw = str(row.get(field, "") or "")
        for token in re.split(r"[+、,/，；;|\s]+", raw):
            token = token.strip()
            if not token:
                continue
            counts[token] = counts.get(token, 0) + 1
    return [
        {"theme": theme, "count": count}
        for theme, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]
    ]


def _recent_records(records: Iterable[dict], limit: int) -> list[dict]:
    rows = list(records)
    return rows[-limit:] if len(rows) > limit else rows


_FALLBACK_RANK = {"none": 0, "equivalent": 1, "partial": 2, "diagnostic": 3}


def _combined_fallback_level(levels: Iterable[str]) -> str:
    best = "none"
    for level in levels:
        if _FALLBACK_RANK.get(level, 0) > _FALLBACK_RANK[best]:
            best = level
    return best


def serialize_envelope(envelope: ProviderEnvelope, title: str = "A-Share Data") -> str:
    """Render a ProviderEnvelope into the existing tool string shape."""
    header = [
        f"# {title}",
        f"# Source: {envelope.source}",
        f"# Status: {envelope.status}",
        f"# Contract Fulfilled: {str(envelope.contract_fulfilled).lower()}",
        f"# Fallback Level: {envelope.fallback_level}",
    ]
    if envelope.as_of:
        header.append(f"# As of: {envelope.as_of}")
    if envelope.errors:
        header.append("# Errors: " + "; ".join(envelope.errors))

    data = envelope.data
    body = ""
    if isinstance(data, dict) and data:
        if "csv" in data:
            body = str(data["csv"])
        elif "records" in data and isinstance(data["records"], list):
            body = pd.DataFrame(data["records"]).to_csv(index=False) if data["records"] else "No records."
        else:
            body = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    elif envelope.evidence:
        body = json.dumps(envelope.evidence, ensure_ascii=False, indent=2, default=str)
    else:
        body = "No data."
    return "\n".join(header) + "\n\n" + body


@dataclass
class AStockDataProvider:
    """Concrete CN A-share provider backed by a-stock-data endpoints."""

    source: str = "a_stock_data"
    _mootdx_client: Any = field(default=None, init=False, repr=False)
    _baidu_kline_cache: Dict[str, list[dict]] = field(default_factory=dict, init=False, repr=False)

    def _ok(
        self,
        data: Optional[Dict[str, Any]] = None,
        *,
        source: Optional[str] = None,
        evidence: Optional[List[Dict[str, Any]]] = None,
        as_of: Optional[str] = None,
        contract_fulfilled: bool = True,
        fallback_level: str = "none",
    ) -> ProviderEnvelope:
        return ProviderEnvelope(
            status="ok",
            source=source or self.source,
            as_of=as_of or _today(),
            data=data or {},
            evidence=evidence or [],
            contract_fulfilled=contract_fulfilled,
            fallback_level=fallback_level,
        )

    def _unavailable(self, reason: str, *, source: Optional[str] = None) -> ProviderEnvelope:
        return ProviderEnvelope(
            status="unavailable",
            source=source or self.source,
            as_of=_today(),
            data={},
            errors=[reason],
            evidence=[],
            contract_fulfilled=False,
            fallback_level="none",
        )

    def _error(self, reason: str, *, source: Optional[str] = None) -> ProviderEnvelope:
        return ProviderEnvelope(
            status="error",
            source=source or self.source,
            as_of=_today(),
            data={},
            errors=[reason],
            evidence=[],
            contract_fulfilled=False,
            fallback_level="none",
        )

    def _guard(self, source: str, func: Callable[[], ProviderEnvelope]) -> ProviderEnvelope:
        try:
            return func()
        except Exception as exc:
            return self._error(str(exc), source=source)

    def _client(self):
        if self._mootdx_client is None:
            from mootdx.quotes import Quotes

            self._mootdx_client = Quotes.factory(market="std")
        return self._mootdx_client

    def get_mootdx_market_data(
        self, symbol: str, trade_date: str, include_ticks: bool = False
    ) -> ProviderEnvelope:
        """Layer 1.1: mootdx K-line, quote, and optional transaction data."""
        code = normalize_to_code(symbol)

        def run():
            client = self._client()
            data: Dict[str, Any] = {}
            evidence: list[dict] = []

            bars = self._filter_date_records(self._mootdx_bars(code), "1900-01-01", trade_date)
            data["daily_bars"] = _recent_records(bars, 120)
            evidence.extend(data["daily_bars"][-5:])

            quotes = client.quotes(symbol=[code])
            if isinstance(quotes, pd.DataFrame):
                quote_records = quotes.to_dict(orient="records")
            elif isinstance(quotes, list):
                quote_records = quotes
            else:
                quote_records = [quotes] if quotes else []
            data["quote"] = quote_records[:1]
            evidence.extend(quote_records[:1])

            if include_ticks:
                try:
                    raw_ticks = client.transaction(symbol=code, date=trade_date.replace("-", ""))
                    if isinstance(raw_ticks, pd.DataFrame):
                        ticks = raw_ticks.to_dict(orient="records")
                    elif isinstance(raw_ticks, list):
                        ticks = raw_ticks
                    else:
                        ticks = [raw_ticks] if raw_ticks else []
                    data["transactions"] = _recent_records(ticks, 60)
                except Exception as exc:
                    data["transactions_error"] = str(exc)

            return self._ok(data, source="mootdx_market_data", evidence=evidence)

        env = self._guard("mootdx_market_data", run)
        if env.status == "ok":
            return env

        fallback_errors = [f"mootdx: {'; '.join(env.errors)}"]
        data: Dict[str, Any] = {
            "fallback_note": "mootdx unavailable; using Eastmoney daily K-line and Tencent quote instead.",
        }
        evidence: list[dict] = []
        try:
            bars = self._filter_date_records(
                self._eastmoney_kline_records(code, "1900-01-01", trade_date),
                "1900-01-01",
                trade_date,
            )
            data["daily_bars"] = _recent_records(bars, 120)
            evidence.extend(data["daily_bars"][-5:])
        except Exception as exc:
            fallback_errors.append(f"eastmoney kline fallback: {exc}")
        try:
            quote = self.tencent_quote([code]).get(code, {})
            if quote:
                data["quote"] = [quote]
                evidence.append(quote)
        except Exception as exc:
            fallback_errors.append(f"tencent quote fallback: {exc}")

        if len(data) == 1:
            fallback = self._unavailable("mootdx market data unavailable and fallback sources failed", source="mootdx_market_data_fallback")
            fallback.errors.extend(fallback_errors)
            return fallback

        fallback = self._ok(
            data,
            source="mootdx_market_data_fallback",
            evidence=evidence,
            contract_fulfilled=not include_ticks,
            fallback_level="equivalent" if not include_ticks else "partial",
        )
        fallback.errors.extend(fallback_errors)
        return fallback

    def get_tencent_quote_envelope(self, symbol: str) -> ProviderEnvelope:
        """Layer 1.2: Tencent quote with PE/PB/market-cap/limit prices."""
        return self.get_quote(symbol)

    def get_baidu_kline_ma(self, symbol: str, start_date: str = "", end_date: str = "") -> ProviderEnvelope:
        """Layer 1.3: Baidu K-line with MA5/MA10/MA20 fallback data."""
        code = normalize_to_code(symbol)

        def run():
            errors: list[str] = []
            records = self._baidu_kline_records(code)
            source = "baidu_kline_with_ma"
            if not records:
                errors.append("baidu kline returned no records")
                try:
                    records = self._eastmoney_kline_records(code, start_date or "1900-01-01", end_date or _today())
                    source = "baidu_kline_with_ma+eastmoney_kline_fallback"
                except Exception as exc:
                    errors.append(f"eastmoney kline fallback: {exc}")
                    records = self._sina_kline_records(code)
                    source = "baidu_kline_with_ma+sina_kline_fallback"
            if start_date or end_date:
                records = self._filter_date_records(records, start_date or "1900-01-01", end_date or _today())
            records = _recent_records(records, 120)
            if not records:
                env = self._unavailable("kline data unavailable from Baidu and Eastmoney fallback", source=source)
                env.errors.extend(errors)
                return env
            env = self._ok(
                {"records": records},
                source=source,
                evidence=records[-5:],
                contract_fulfilled=True,
                fallback_level="equivalent" if "fallback" in source else "none",
            )
            env.errors.extend(errors)
            return env

        return self._guard("baidu_kline_with_ma", run)

    def ths_eps_forecast(self, code: str) -> list[dict]:
        """Layer 2.2: THS consensus EPS; rows with <3 institutions are risky."""
        url = f"https://basic.10jqka.com.cn/new/{code}/worth.html"
        r = requests.get(
            url,
            headers={"User-Agent": UA, "Referer": "https://basic.10jqka.com.cn/"},
            timeout=15,
        )
        r.raise_for_status()
        r.encoding = "gbk"
        dfs = pd.read_html(StringIO(r.text))
        target = pd.DataFrame()
        for df in dfs:
            cols = [str(c) for c in df.columns]
            if any("每股收益" in c or "均值" in c for c in cols):
                target = df
                break
        if target.empty and dfs:
            target = dfs[0]
        return target.head(8).to_dict(orient="records") if not target.empty else []

    def get_ths_eps_forecast(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "ths_eps_forecast",
            lambda: self._ok(
                {
                    "records": self.ths_eps_forecast(code),
                    "note": "预测机构数 < 3 时应降低可信度，不能把一致预期当作财务事实。",
                },
                source="ths_eps_forecast",
            ),
        )

    def ths_hot_reason(self, trade_date: str | None = None) -> list[dict]:
        """Layer 3.1: THS hot stocks with reason tags."""
        if not trade_date:
            trade_date = _today()
        url = f"http://zx.10jqka.com.cn/event/api/getharden/date/{trade_date}/orderby/date/orderway/desc/charset/GBK/"
        r = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "Chrome/117.0.0.0 Safari/537.36"
                )
            },
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("errocode", 0) != 0:
            raise RuntimeError(f"同花顺热点错误: {payload.get('errormsg', '')}")
        df = pd.DataFrame(payload.get("data") or [])
        if df.empty:
            return []
        rename_map = {
            "name": "名称",
            "code": "代码",
            "reason": "题材归因",
            "close": "收盘价",
            "zhangdie": "涨跌额",
            "zhangfu": "涨幅%",
            "huanshou": "换手率%",
            "chengjiaoe": "成交额",
            "chengjiaoliang": "成交量",
            "ddejingliang": "大单净量",
            "market": "市场",
        }
        df = df.rename(columns=rename_map)
        sort_cols = [c for c in ["涨幅%", "换手率%", "成交额"] if c in df.columns]
        if sort_cols:
            df = df.sort_values(sort_cols, ascending=False)
        return df.to_dict(orient="records")

    def get_ths_hot_reason(
        self, trade_date: str | None = None, symbol: str | None = None, limit: int = DEFAULT_STOCK_LIMIT
    ) -> ProviderEnvelope:
        def run():
            rows = self.ths_hot_reason(trade_date)
            target_code = normalize_to_code(symbol) if symbol else None
            target_rows = [r for r in rows if str(r.get("代码", "")).zfill(6) == target_code] if target_code else []
            filtered = _limit_records(rows, limit)
            return self._ok(
                {
                    "records": filtered,
                    "target_records": target_rows,
                    "theme_summary": _theme_summary(rows),
                    "filter_note": f"全市场热点仅保留强度前 {limit} 条；若目标股票命中则单独保留。",
                },
                source="ths_hot_reason",
                evidence=(target_rows or filtered[:5]),
            )

        return self._guard("ths_hot_reason", run)

    def hsgt_realtime(self) -> list[dict]:
        """Layer 3.2: THS northbound minute flow, unit: 亿元."""
        r = requests.get(
            "https://data.hexin.cn/market/hsgtApi/method/dayChart/",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "Chrome/117.0.0.0 Safari/537.36"
                ),
                "Host": "data.hexin.cn",
                "Referer": "https://data.hexin.cn/",
            },
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        times = payload.get("time", [])
        hgt = payload.get("hgt", [])
        sgt = payload.get("sgt", [])
        rows = []
        for idx, item_time in enumerate(times):
            rows.append(
                {
                    "time": item_time,
                    "hgt_yi": hgt[idx] if idx < len(hgt) else None,
                    "sgt_yi": sgt[idx] if idx < len(sgt) else None,
                }
            )
        return rows

    def _northbound_cache_path(self):
        cache_dir = get_config().get("data_cache_dir")
        path = os.path.join(cache_dir, "northbound_daily.csv") if cache_dir else os.path.expanduser("~/.tradingagents/cache/northbound_daily.csv")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    def _load_northbound_history(self, n: int = 20) -> list[dict]:
        path = self._northbound_cache_path()
        if not os.path.exists(path):
            return []
        return pd.read_csv(path).tail(n).to_dict(orient="records")

    def get_northbound_flow(self, trade_date: str | None = None, history_days: int = 20) -> ProviderEnvelope:
        def run():
            realtime = self.hsgt_realtime()
            latest = [r for r in realtime if r.get("hgt_yi") is not None or r.get("sgt_yi") is not None][-5:]
            history = self._load_northbound_history(history_days)
            reliability = "normal"
            if latest:
                last = latest[-1]
                if _safe_float(last.get("hgt_yi")) == 0 and _safe_float(last.get("sgt_yi")) == 0:
                    reliability = "low"
            return self._ok(
                {
                    "latest_points": latest,
                    "history": history,
                    "unit": "亿元",
                    "reliability": reliability,
                    "note": "北向历史字段存在上游断供/异常风险；0/NaN 不应直接解释为无资金流。",
                },
                source="ths_hsgt",
                evidence=latest,
            )

        return self._guard("ths_hsgt", run)

    def tencent_quote(self, codes: list[str]) -> dict[str, dict]:
        """Batch Tencent quote endpoint."""
        prefixed = [f"{get_prefix(normalize_to_code(c))}{normalize_to_code(c)}" for c in codes]
        req = urllib.request.Request("https://qt.gtimg.cn/q=" + ",".join(prefixed))
        req.add_header("User-Agent", UA)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("gbk")

        result: dict[str, dict] = {}
        for line in data.strip().split(";"):
            if not line.strip() or "=" not in line or '"' not in line:
                continue
            key = line.split("=", 1)[0].split("_")[-1]
            vals = line.split('"')[1].split("~")
            if len(vals) < 53:
                continue
            code = key[2:]
            result[code] = {
                "code": code,
                "name": vals[1],
                "price": _safe_float(vals[3]),
                "last_close": _safe_float(vals[4]),
                "open": _safe_float(vals[5]),
                "change_amt": _safe_float(vals[31]),
                "change_pct": _safe_float(vals[32]),
                "high": _safe_float(vals[33]),
                "low": _safe_float(vals[34]),
                "amount_wan": _safe_float(vals[37]),
                "turnover_pct": _safe_float(vals[38]),
                "pe_ttm": _safe_float(vals[39]),
                "amplitude_pct": _safe_float(vals[43]),
                "float_mcap_yi": _safe_float(vals[44]),
                "mcap_yi": _safe_float(vals[45]),
                "pb": _safe_float(vals[46]),
                "limit_up": _safe_float(vals[47]),
                "limit_down": _safe_float(vals[48]),
                "vol_ratio": _safe_float(vals[49]),
                "pe_static": _safe_float(vals[52]),
            }
        return result

    def baidu_kline_with_ma(self, code: str, start_time: str = "") -> dict:
        url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
        params = {
            "all": "1",
            "isIndex": "false",
            "isBk": "false",
            "isBlock": "false",
            "isFutures": "false",
            "isStock": "true",
            "newFormat": "1",
            "group": "quotation_kline_ab",
            "finClientType": "pc",
            "code": code,
            "start_time": start_time,
            "ktype": "1",
        }
        headers = {
            "User-Agent": UA,
            "Accept": "application/vnd.finance-web.v1+json",
            "Origin": "https://gushitong.baidu.com",
            "Referer": "https://gushitong.baidu.com/",
        }
        payload: dict[str, Any] = {}
        for attempt in range(3):
            r = requests.get(url, params=params, headers=headers, timeout=10)
            r.raise_for_status()
            payload = r.json()
            result_probe = payload.get("Result")
            if result_probe not in (None, [], {}):
                break
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1) + random.uniform(0.1, 0.4))

        result = payload.get("Result") or {}
        if isinstance(result, list):
            result = next((item for item in result if isinstance(item, dict)), {})
        if not isinstance(result, dict):
            result = {}

        md = result.get("newMarketData") or {}
        if isinstance(md, list):
            md = next((item for item in md if isinstance(item, dict)), {})
        if not isinstance(md, dict):
            md = {}

        rows = md.get("marketData", "")
        if isinstance(rows, str):
            rows = [row for row in rows.split(";") if row]
        elif not isinstance(rows, list):
            rows = []
        return {"keys": md.get("keys", []), "rows": rows}

    def _mootdx_bars(self, code: str) -> list[dict]:
        client = self._client()
        try:
            raw = client.bars(symbol=code, category=4, offset=0, count=800)
        except TypeError:
            raw = client.bars(symbol=code, category=4, offset=0)
        if raw is None:
            return []
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        rename = {
            "datetime": "Date",
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "vol": "Volume",
            "volume": "Volume",
            "amount": "Amount",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        if "Date" not in df.columns and df.index.name:
            df = df.reset_index().rename(columns={df.index.name: "Date"})
        return df.to_dict(orient="records")

    def _baidu_kline_records(self, code: str) -> list[dict]:
        if code in self._baidu_kline_cache:
            return list(self._baidu_kline_cache[code])
        payload = self.baidu_kline_with_ma(code)
        keys = payload.get("keys") or []
        records = []
        for row in payload.get("rows") or []:
            if isinstance(row, dict):
                rec = row
            else:
                parts = str(row).split(",")
                if len(parts) != len(keys):
                    continue
                rec = dict(zip(keys, parts))
            records.append(
                {
                    "Date": rec.get("time", "")[:10],
                    "Open": _safe_float(rec.get("open")),
                    "High": _safe_float(rec.get("high")),
                    "Low": _safe_float(rec.get("low")),
                    "Close": _safe_float(rec.get("close")),
                    "Volume": _safe_float(rec.get("volume")),
                    "Amount": _safe_float(rec.get("amount")),
                    "ma5avgprice": _safe_float(rec.get("ma5avgprice")),
                    "ma10avgprice": _safe_float(rec.get("ma10avgprice")),
                    "ma20avgprice": _safe_float(rec.get("ma20avgprice")),
                }
            )
        if records:
            self._baidu_kline_cache[code] = list(records)
        return records

    def _with_price_mas(self, records: list[dict]) -> list[dict]:
        if not records:
            return records
        df = pd.DataFrame(records)
        if "Close" not in df.columns:
            return records
        df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
        for window in (5, 10, 20):
            key = f"ma{window}avgprice"
            if key not in df.columns:
                df[key] = df["Close"].rolling(window, min_periods=1).mean().round(2)
        return df.to_dict(orient="records")

    def _eastmoney_kline_records(
        self, code: str, start_date: str = "1900-01-01", end_date: str = ""
    ) -> list[dict]:
        def compact_date(value: str, fallback: str) -> str:
            digits = re.sub(r"\D", "", value or "")
            return digits if len(digits) >= 8 else fallback

        params = {
            "secid": get_secid(code),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "klt": "101",
            "fqt": "1",
            "beg": compact_date(start_date, "19000101"),
            "end": compact_date(end_date, "20500101"),
        }
        r = em_get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=20,
            max_retries=5,
        )
        r.raise_for_status()
        rows = []
        for line in r.json().get("data", {}).get("klines", []) or []:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            rows.append(
                {
                    "Date": parts[0],
                    "Open": _safe_float(parts[1]),
                    "Close": _safe_float(parts[2]),
                    "High": _safe_float(parts[3]),
                    "Low": _safe_float(parts[4]),
                    # Eastmoney volume is in lots; keep the public schema in shares.
                    "Volume": _safe_float(parts[5]) * 100,
                    "Amount": _safe_float(parts[6]),
                }
            )
        return self._with_price_mas(rows)

    def _sina_kline_records(self, code: str, datalen: int = 800) -> list[dict]:
        paper_code = f"{get_prefix(code)}{code}"
        r = requests.get(
            "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20data=/CN_MarketDataService.getKLineData",
            params={"symbol": paper_code, "scale": "240", "ma": "no", "datalen": str(datalen)},
            headers={"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"},
            timeout=15,
        )
        r.raise_for_status()
        match = re.search(r"var\s+data=\((.*)\)\s*;?\s*$", r.text, flags=re.S)
        if not match:
            return []
        rows = []
        for item in json.loads(match.group(1)):
            rows.append(
                {
                    "Date": item.get("day", ""),
                    "Open": _safe_float(item.get("open")),
                    "High": _safe_float(item.get("high")),
                    "Low": _safe_float(item.get("low")),
                    "Close": _safe_float(item.get("close")),
                    "Volume": _safe_float(item.get("volume")),
                    "Amount": _safe_float(item.get("amount")),
                }
            )
        return self._with_price_mas(rows)

    def _filter_date_records(self, records: list[dict], start_date: str, end_date: str) -> list[dict]:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        filtered = []
        for rec in records:
            date_value = rec.get("Date") or rec.get("datetime") or rec.get("date")
            if not date_value:
                continue
            dt = pd.to_datetime(date_value, errors="coerce")
            if pd.isna(dt):
                continue
            if start <= dt <= end:
                rec = dict(rec)
                rec["Date"] = dt.strftime("%Y-%m-%d")
                filtered.append(rec)
        return filtered

    def get_quote(self, symbol: str, trade_date: Optional[str] = None) -> ProviderEnvelope:
        code = normalize_to_code(symbol)

        def run():
            data = self.tencent_quote([code]).get(code)
            if not data:
                return self._unavailable(f"quote unavailable for {symbol}", source="tencent_quote")
            return self._ok({"quote": data}, source="tencent_quote", evidence=[data])

        return self._guard("tencent_quote", run)

    def screen_main_board_candidates(
        self,
        min_lot_amount: float = 2000.0,
        max_lot_amount: float = 3000.0,
        *,
        max_turnover_pct: float | None = 10.0,
        limit: int = 50,
        codes: Optional[list[str]] = None,
        batch_size: int = 80,
        quote_batch_interval: float = 1.0,
        volume_growth_days: int = 3,
        ma_slope_days: int = 3,
        kline_lookback_days: int = 45,
        recent_position_days: int = 20,
        kline_request_interval: float = 1.8,
        eastmoney_min_interval: float = 1.8,
        verbose: bool = False,
        progress: Optional[Callable[[str], None]] = None,
    ) -> ProviderEnvelope:
        """Screen A-share main-board candidates after the user-defined 14:30 strategy window."""
        from .ashare_main_board_screener import (
            AStockMainBoardScreenerConfig,
            screen_main_board_candidates,
        )

        def run():
            global EM_MIN_INTERVAL
            config = AStockMainBoardScreenerConfig(
                min_lot_amount=min_lot_amount,
                max_lot_amount=max_lot_amount,
                max_turnover_pct=max_turnover_pct,
                limit=limit,
                codes=tuple(codes) if codes else None,
                batch_size=batch_size,
                quote_batch_interval=quote_batch_interval,
                volume_growth_days=volume_growth_days,
                ma_slope_days=ma_slope_days,
                kline_lookback_days=kline_lookback_days,
                recent_position_days=recent_position_days,
                kline_request_interval=kline_request_interval,
                eastmoney_min_interval=eastmoney_min_interval,
            )
            progress_callback = progress or (print if verbose else None)
            original_em_interval = EM_MIN_INTERVAL
            EM_MIN_INTERVAL = max(float(EM_MIN_INTERVAL), float(eastmoney_min_interval))
            try:
                payload = screen_main_board_candidates(self, config, progress=progress_callback)
            finally:
                EM_MIN_INTERVAL = original_em_interval
            if payload["summary"]["quote_count"] == 0 and payload.get("errors"):
                return ProviderEnvelope(
                    status="unavailable",
                    source="a_stock_main_board_screener",
                    as_of=_today(),
                    data=payload,
                    errors=list(payload.get("errors", [])),
                    evidence=[],
                )
            env = self._ok(
                payload,
                source="a_stock_main_board_screener",
                evidence=payload.get("records", [])[:5],
                as_of=payload["summary"].get("as_of") or _today(),
                contract_fulfilled=not payload.get("errors"),
                fallback_level="partial" if payload.get("errors") else "none",
            )
            env.errors.extend(payload.get("errors", []))
            return env

        return self._guard("a_stock_main_board_screener", run)

    def get_stock_data(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        errors = []
        source = "mootdx_bars"
        try:
            records = self._filter_date_records(self._mootdx_bars(code), start_date, end_date)
        except Exception as exc:
            records = []
            errors.append(f"mootdx unavailable: {exc}")

        if not records:
            source = "baidu_kline_with_ma"
            try:
                records = self._filter_date_records(self._baidu_kline_records(code), start_date, end_date)
                if not records:
                    errors.append("baidu kline returned no records")
            except Exception as exc:
                errors.append(f"baidu kline unavailable: {exc}")

        if not records:
            source = "eastmoney_kline"
            try:
                records = self._filter_date_records(
                    self._eastmoney_kline_records(code, start_date, end_date),
                    start_date,
                    end_date,
                )
                if not records:
                    errors.append("eastmoney kline returned no records")
            except Exception as exc:
                errors.append(f"eastmoney kline unavailable: {exc}")

        if not records:
            source = "sina_kline"
            try:
                records = self._filter_date_records(
                    self._sina_kline_records(code),
                    start_date,
                    end_date,
                )
                if not records:
                    errors.append("sina kline returned no records")
            except Exception as exc:
                errors.append(f"sina kline unavailable: {exc}")

        if not records:
            env = self._unavailable(f"stock data unavailable for {symbol} ({start_date}~{end_date})", source=source)
            env.errors.extend(errors)
            return env

        df = pd.DataFrame(records)
        env = self._ok(
            {"records": records, "csv": df.to_csv(index=False)},
            source=source,
            evidence=records[:5],
            contract_fulfilled=True,
            fallback_level="equivalent" if errors else "none",
        )
        env.errors.extend(errors)
        return env

    def get_indicators(
        self, symbol: str, indicator: str, curr_date: str, look_back_days: int = 30
    ) -> ProviderEnvelope:
        from stockstats import wrap

        start_date = (datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=max(look_back_days, 260))).strftime("%Y-%m-%d")
        stock_env = self.get_stock_data(symbol, start_date, curr_date)
        if stock_env.status != "ok" or not stock_env.data.get("records"):
            return self._unavailable(f"indicator {indicator} unavailable; no OHLCV data", source=stock_env.source)

        df = pd.DataFrame(stock_env.data["records"])
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date", "Close"])
        sdf = wrap(df)
        sdf["Date"] = sdf["Date"].dt.strftime("%Y-%m-%d")
        sdf[indicator]

        end = datetime.strptime(curr_date, "%Y-%m-%d")
        start = end - timedelta(days=look_back_days)
        rows = []
        for _, row in sdf.iterrows():
            dt = datetime.strptime(row["Date"], "%Y-%m-%d")
            if start <= dt <= end:
                value = row.get(indicator)
                rows.append({"date": row["Date"], indicator: None if pd.isna(value) else value})
        return self._ok({"indicator": indicator, "records": rows}, source="stockstats+a_stock_data", evidence=rows[-5:])

    def eastmoney_stock_info(self, code: str) -> dict:
        params = {
            "fltt": "2",
            "invt": "2",
            "fields": "f57,f58,f84,f85,f127,f116,f117,f189,f43",
            "secid": get_secid(code),
        }
        r = em_get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params=params,
            headers={"User-Agent": UA},
            timeout=10,
        )
        r.raise_for_status()
        d = r.json().get("data", {}) or {}
        return {
            "code": d.get("f57", ""),
            "name": d.get("f58", ""),
            "industry": d.get("f127", ""),
            "total_shares": d.get("f84", 0),
            "float_shares": d.get("f85", 0),
            "mcap": d.get("f116", 0),
            "float_mcap": d.get("f117", 0),
            "list_date": str(d.get("f189", "")),
            "price": d.get("f43", 0),
        }

    def _public_stock_info_fallback(self, code: str) -> tuple[dict, list[str]]:
        errors: list[str] = []
        info: dict[str, Any] = {
            "code": code,
            "fallback_note": "Eastmoney push2 stock-info failed; using Tencent quote and report metadata where available.",
        }
        try:
            quote = self.tencent_quote([code]).get(code) or {}
            if quote:
                info.update(
                    {
                        "name": quote.get("name", ""),
                        "price": quote.get("price", 0),
                        "mcap_yi": quote.get("mcap_yi", 0),
                        "float_mcap_yi": quote.get("float_mcap_yi", 0),
                        "pe_ttm": quote.get("pe_ttm", 0),
                        "pe_static": quote.get("pe_static", 0),
                        "pb": quote.get("pb", 0),
                        "turnover_pct": quote.get("turnover_pct", 0),
                        "amount_wan": quote.get("amount_wan", 0),
                    }
                )
        except Exception as exc:
            errors.append(f"tencent quote fallback: {exc}")

        try:
            reports = self.eastmoney_reports(code, max_pages=1)
            if reports:
                first = reports[0]
                info["industry"] = first.get("indvInduName") or first.get("industryName") or ""
                info["market"] = first.get("market") or ""
                info["new_listing_date"] = first.get("newListingDate") or ""
        except Exception as exc:
            errors.append(f"eastmoney report metadata fallback: {exc}")
        return info, errors

    def get_eastmoney_stock_info(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        env = self._guard(
            "eastmoney_stock_info",
            lambda: self._ok({"info": self.eastmoney_stock_info(code)}, source="eastmoney_stock_info"),
        )
        if env.status == "ok":
            return env

        info, fallback_errors = self._public_stock_info_fallback(code)
        if len(info) > 2:
            fallback = self._ok(
                {"info": info},
                source="eastmoney_stock_info_fallback_public",
                evidence=[info],
                contract_fulfilled=False,
                fallback_level="partial",
            )
            fallback.errors.extend([f"eastmoney stock info: {'; '.join(env.errors)}"] + fallback_errors)
            return fallback
        env.errors.extend(fallback_errors)
        return env

    def get_mootdx_finance_snapshot(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)

        def run():
            raw = self._client().finance(symbol=code)
            if isinstance(raw, pd.DataFrame):
                data = raw.to_dict(orient="records")
            elif hasattr(raw, "to_dict"):
                data = raw.to_dict()
            else:
                data = raw
            return self._ok(
                {
                    "finance_snapshot": data,
                    "note": "mootdx 财务快照为季报快照字段，需与新浪三表交叉验证。",
                },
                source="mootdx_finance_snapshot",
            )

        env = self._guard("mootdx_finance_snapshot", run)
        if env.status == "ok":
            return env

        errors = [f"mootdx: {'; '.join(env.errors)}"]
        data: Dict[str, Any] = {
            "fallback_note": "mootdx finance snapshot unavailable; using public stock info and Sina latest statements instead.",
        }
        stock_env = self.get_eastmoney_stock_info(code)
        if stock_env.status == "ok":
            data["stock_info"] = stock_env.data.get("info", {})
            errors.extend(stock_env.errors)
        else:
            errors.append(f"stock info fallback: {'; '.join(stock_env.errors)}")
        for report_type, label in (("lrb", "income_statement"), ("fzb", "balance_sheet"), ("llb", "cashflow")):
            try:
                data[label] = self.sina_financial_report(code, report_type, num=1)
            except Exception as exc:
                errors.append(f"sina {label} fallback: {exc}")

        if len(data) == 1:
            fallback = self._unavailable("mootdx finance snapshot unavailable and fallback sources failed", source="mootdx_finance_snapshot_fallback")
            fallback.errors.extend(errors)
            return fallback

        fallback = self._ok(
            data,
            source="mootdx_finance_snapshot_fallback",
            evidence=[data],
            contract_fulfilled=False,
            fallback_level="partial",
        )
        fallback.errors.extend(errors)
        return fallback

    def get_fundamentals(self, symbol: str, report_period: Optional[str] = None) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        data: Dict[str, Any] = {}
        evidence = []
        errors = []
        contract_fulfilled = True
        fallback_levels: list[str] = []
        for name, func in [
            ("quote", lambda: self.tencent_quote([code]).get(code, {})),
            ("stock_info", lambda: self.get_eastmoney_stock_info(code)),
            ("finance_snapshot", lambda: self.get_mootdx_finance_snapshot(code)),
            ("research_reports", lambda: self.eastmoney_reports(code, max_pages=1)[:5]),
            ("f10_latest", lambda: self.get_f10(code, category="最新提示")),
        ]:
            try:
                value = func()
                if isinstance(value, ProviderEnvelope):
                    errors.extend(f"{name}: {err}" for err in value.errors)
                    fallback_levels.append(value.fallback_level)
                    if not value.contract_fulfilled:
                        contract_fulfilled = False
                    if value.status != "ok":
                        continue
                    if name == "stock_info":
                        value = value.data.get("info", {})
                    elif name == "f10_latest":
                        value = value.data.get("text", "")
                    else:
                        value = value.data
                data[name] = value
                if value:
                    evidence.append({"source": name, "data": value if name != "f10_latest" else str(value)[:500]})
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                contract_fulfilled = False
        if not data:
            return self._unavailable(f"fundamentals unavailable for {symbol}")
        if errors:
            contract_fulfilled = False
            fallback_levels.append("partial")
        env = self._ok(
            data,
            source=self.source,
            evidence=evidence,
            contract_fulfilled=contract_fulfilled,
            fallback_level=_combined_fallback_level(fallback_levels),
        )
        env.errors.extend(errors)
        return env

    def eastmoney_reports(self, code: str, max_pages: int = 5) -> list[dict]:
        all_records = []
        for page in range(1, max_pages + 1):
            params = {
                "industryCode": "*",
                "pageSize": "100",
                "industry": "*",
                "rating": "*",
                "ratingChange": "*",
                "beginTime": "2000-01-01",
                "endTime": "2030-01-01",
                "pageNo": str(page),
                "fields": "",
                "qType": "0",
                "orgCode": "",
                "code": code,
                "rcode": "",
                "p": str(page),
                "pageNum": str(page),
                "pageNumber": str(page),
            }
            r = em_get(REPORT_API, params=params, headers={"Referer": "https://data.eastmoney.com/"}, timeout=30)
            r.raise_for_status()
            d = r.json()
            rows = d.get("data") or []
            if not rows:
                break
            all_records.extend(rows)
            if page >= (d.get("TotalPage", 1) or 1):
                break
        return all_records

    def get_research_reports(self, symbol: str, max_pages: int = 1) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "eastmoney_reports",
            lambda: self._ok({"records": self.eastmoney_reports(code, max_pages=max_pages)}, source="eastmoney_reports"),
        )

    def get_iwencai_reports(self, query: str, limit: int = 50) -> ProviderEnvelope:
        api_key = os.getenv("IWENCAI_API_KEY") or os.getenv("WENCAI_API_KEY")
        if not api_key:
            return self._unavailable("IWENCAI_API_KEY/WENCAI_API_KEY is not set", source="iwencai")

        def run():
            base_url = os.getenv("IWENCAI_BASE_URL", "https://openapi.iwencai.com").rstrip("/")
            configured_endpoint = os.getenv("IWENCAI_ENDPOINT", "").strip()
            endpoints = [configured_endpoint] if configured_endpoint else ["/v1/comprehensive/search", "/api/report-search"]
            headers = {
                "User-Agent": UA,
                "Accept": "application/json,text/plain,*/*",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "x-api-key": api_key,
                "X-Token": api_key,
                "token": api_key,
            }
            errors: list[str] = []
            for endpoint in endpoints:
                url = endpoint if endpoint.startswith("http") else f"{base_url}{endpoint}"
                body = {"query": query, "page": 1, "limit": limit}
                if "comprehensive" in endpoint:
                    body["channels"] = ["report"]
                try:
                    r = requests.post(url, json=body, headers=headers, timeout=20)
                    if r.status_code in (401, 403):
                        errors.append(f"{url}: authentication failed ({r.status_code})")
                        continue
                    r.raise_for_status()
                    payload = r.json()
                    records = self._extract_iwencai_records(payload)
                    env = self._ok(
                        {"query": query, "endpoint": url, "records": records},
                        source="iwencai",
                        evidence=records[:5] if isinstance(records, list) else [],
                        contract_fulfilled=True,
                        fallback_level="equivalent" if errors else "none",
                    )
                    env.errors.extend(errors)
                    return env
                except Exception as exc:
                    errors.append(f"{url}: {exc}")
            reason = (
                "iwencai request failed; check IWENCAI_API_KEY, IWENCAI_BASE_URL/IWENCAI_ENDPOINT, "
                "and whether the key is authorized for report/comprehensive search. "
                + "; ".join(errors)
            )
            return self._error(reason, source="iwencai")

        return self._guard("iwencai", run)

    def _extract_iwencai_records(self, payload: Any) -> list[dict]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        candidates = [
            payload.get("data"),
            payload.get("result"),
            payload.get("records"),
        ]
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.extend(
                [
                    data.get("records"),
                    data.get("list"),
                    data.get("items"),
                    data.get("report"),
                    data.get("reports"),
                ]
            )
            report = data.get("report")
            if isinstance(report, dict):
                candidates.extend([report.get("records"), report.get("list"), report.get("items")])
        for candidate in candidates:
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return []

    def eastmoney_stock_news(self, code: str, page_size: int = 20) -> list[dict]:
        cb = "jQuery_news"
        inner_params = json.dumps(
            {
                "uid": "",
                "keyword": code,
                "type": ["cmsArticleWebOld"],
                "client": "web",
                "clientType": "web",
                "clientVersion": "curr",
                "param": {
                    "cmsArticleWebOld": {
                        "searchScope": "default",
                        "sort": "default",
                        "pageIndex": 1,
                        "pageSize": page_size,
                        "preTag": "",
                        "postTag": "",
                    }
                },
            },
            separators=(",", ":"),
        )
        r = em_get(
            "https://search-api-web.eastmoney.com/search/jsonp",
            params={"cb": cb, "param": inner_params},
            headers={"User-Agent": UA, "Referer": "https://so.eastmoney.com/"},
            timeout=15,
        )
        r.raise_for_status()
        text = r.text
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
        rows = []
        for item in d.get("result", {}).get("cmsArticleWebOld", []) or []:
            rows.append(
                {
                    "title": _clean_html(item.get("title", "")),
                    "content": _clean_html(item.get("content", ""))[:200],
                    "time": item.get("date", ""),
                    "source": item.get("mediaName", ""),
                    "url": item.get("url", ""),
                }
            )
        return rows

    def get_news(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        data: Dict[str, Any] = {}
        evidence = []
        errors = []
        try:
            news = self.eastmoney_stock_news(code)
            data["stock_news"] = news
            evidence.extend(news[:5])
        except Exception as exc:
            errors.append(f"eastmoney_stock_news: {exc}")
        try:
            anns = self.cninfo_announcements(code, page_size=10)
            data["announcements"] = anns
            evidence.extend(anns[:5])
        except Exception as exc:
            errors.append(f"cninfo_announcements: {exc}")
        if not data:
            return self._unavailable(f"news unavailable for {symbol} ({start_date}~{end_date})")
        env = self._ok(
            data,
            source="eastmoney_news+cninfo",
            evidence=evidence,
            contract_fulfilled=not errors,
            fallback_level="partial" if errors else "none",
        )
        env.errors.extend(errors)
        return env

    def get_social(self, symbol: str, start_date: str, end_date: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self.get_concept_blocks(code)

    def eastmoney_global_news(self, page_size: int = 50) -> list[dict]:
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": str(page_size),
            "req_trace": str(uuid.uuid4()),
        }
        r = em_get(
            "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
            params=params,
            headers={"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"},
            timeout=10,
        )
        r.raise_for_status()
        rows = []
        for item in r.json().get("data", {}).get("fastNewsList", []) or []:
            rows.append(
                {
                    "title": item.get("title", ""),
                    "summary": item.get("summary", "")[:200],
                    "time": item.get("showTime", ""),
                }
            )
        return rows

    def get_global_news(self, curr_date: str, look_back_days: int = 7, limit: int = 50) -> ProviderEnvelope:
        return self._guard(
            "eastmoney_global_news",
            lambda: self._ok({"records": self.eastmoney_global_news(limit)}, source="eastmoney_global_news"),
        )

    def sina_financial_report(self, code: str, report_type: str = "lrb", num: int = 8) -> list[dict]:
        paper_code = f"{get_prefix(code)}{code}"
        params = {
            "paperCode": paper_code,
            "source": report_type,
            "type": "0",
            "page": "1",
            "num": str(num),
        }
        r = requests.get(
            "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
            params=params,
            headers={"User-Agent": UA},
            timeout=15,
        )
        r.raise_for_status()
        report_list = r.json().get("result", {}).get("data", {}).get("report_list", {}) or {}
        rows = []
        for period in sorted(report_list.keys(), reverse=True)[:num]:
            obj = report_list[period]
            rec = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
            for item in obj.get("data", []) or []:
                title = item.get("item_title", "")
                if not title or item.get("item_value") is None:
                    continue
                rec[title] = item.get("item_value")
                tongbi = item.get("item_tongbi")
                if tongbi not in (None, ""):
                    rec[title + "_同比"] = tongbi
            rows.append(rec)
        return rows

    def get_financial_report(self, symbol: str, report_type: str, num: int = 8) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "sina_financial_report",
            lambda: self._ok(
                {"report_type": report_type, "records": self.sina_financial_report(code, report_type, num)},
                source="sina_financial_report",
            ),
        )

    def get_balance_sheet(self, symbol: str, freq: str = "quarterly", curr_date: str = None) -> ProviderEnvelope:
        return self.get_financial_report(symbol, "fzb")

    def get_cashflow(self, symbol: str, freq: str = "quarterly", curr_date: str = None) -> ProviderEnvelope:
        return self.get_financial_report(symbol, "llb")

    def get_income_statement(self, symbol: str, freq: str = "quarterly", curr_date: str = None) -> ProviderEnvelope:
        return self.get_financial_report(symbol, "lrb")

    def eastmoney_fund_flow_minute(self, code: str) -> list[dict]:
        params = {
            "secid": get_secid(code),
            "klt": 1,
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }
        r = em_get(
            "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get",
            params=params,
            headers={
                "User-Agent": UA,
                "Referer": "https://quote.eastmoney.com/",
                "Origin": "https://quote.eastmoney.com",
            },
            timeout=10,
        )
        r.raise_for_status()
        rows = []
        for line in r.json().get("data", {}).get("klines", []) or []:
            parts = line.split(",")
            if len(parts) >= 6:
                rows.append(
                    {
                        "time": parts[0],
                        "main_net": _safe_float(parts[1]),
                        "small_net": _safe_float(parts[2]),
                        "mid_net": _safe_float(parts[3]),
                        "large_net": _safe_float(parts[4]),
                        "super_net": _safe_float(parts[5]),
                    }
                )
        return rows

    def get_capital_flow(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        env = self._guard(
            "eastmoney_fund_flow_minute",
            lambda: self._ok({"records": self.eastmoney_fund_flow_minute(code)}, source="eastmoney_fund_flow_minute"),
        )
        if env.status == "ok":
            return env

        fallback = self.get_stock_fund_flow_120d(code)
        fallback.errors.insert(0, f"intraday fund-flow unavailable: {'; '.join(env.errors)}")
        if fallback.status == "ok":
            if fallback.data.get("fund_flow_available") is False:
                fallback.source = "eastmoney_fund_flow_unavailable_quote_fallback"
                fallback.contract_fulfilled = False
                fallback.fallback_level = "diagnostic"
                fallback.data["fallback_note"] = (
                    "Minute-level and 120-day Eastmoney fund-flow endpoints failed; "
                    "using quote/turnover context only. Do not infer main-net flow from this fallback."
                )
            else:
                fallback.source = "eastmoney_fund_flow_minute_fallback_120d"
                fallback.contract_fulfilled = False
                fallback.fallback_level = "partial"
                fallback.data["fallback_note"] = "Minute-level fund flow failed; using 120-day daily fund flow instead."
        return fallback

    def eastmoney_concept_blocks(self, code: str) -> dict:
        params = {
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "spt": "3",
            "secid": get_secid(code),
            "fields": "f12,f14,f3,f128,f140,f141",
        }
        r = em_get(
            "https://push2.eastmoney.com/api/qt/slist/get",
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json().get("data", {}) or {}
        return {"blocks": data.get("diff", []) or []}

    def get_concept_blocks(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "eastmoney_concept_blocks",
            lambda: self._ok(self.eastmoney_concept_blocks(code), source="eastmoney_concept_blocks"),
        )

    def eastmoney_board_list(self, board_type: str = "concept", page_size: int = 500) -> list[dict]:
        """Eastmoney board list for current industry/concept strength.

        board_type="industry" uses Eastmoney industry boards; "concept" uses
        concept/theme boards.  This endpoint is current-snapshot oriented and
        should not be used as a historical backtest factor without lagged
        snapshots.
        """
        board_type = (board_type or "concept").lower()
        fs = "m:90+t:2" if board_type in {"industry", "sector"} else "m:90+t:3"
        params = {
            "pn": "1",
            "pz": str(max(1, min(int(page_size), 1000))),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": fs,
            "fields": "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f20,f21,f62",
        }
        payload = em_json_with_status_retries(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=15,
            max_retries=5,
        )
        rows = []
        for item in ((payload.get("data") or {}).get("diff") or []):
            rows.append(
                {
                    "board_code": item.get("f12", ""),
                    "board_name": item.get("f14", ""),
                    "board_type": board_type,
                    "price": _safe_float(item.get("f2")),
                    "change_pct": _safe_float(item.get("f3")),
                    "amount": _safe_float(item.get("f6")),
                    "turnover_pct": _safe_float(item.get("f8")),
                    "main_net": _safe_float(item.get("f62")),
                    "float_mcap": _safe_float(item.get("f21")),
                    "total_mcap": _safe_float(item.get("f20")),
                }
            )
        return rows

    def eastmoney_board_constituents(self, board_code: str, page_size: int = 500) -> list[dict]:
        """Eastmoney current constituents for one board code, e.g. BK0475."""
        params = {
            "pn": "1",
            "pz": str(max(1, min(int(page_size), 1000))),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": f"b:{board_code}",
            "fields": "f12,f13,f14,f2,f3,f4,f5,f6,f7,f8,f20,f21,f62",
        }
        payload = em_json_with_status_retries(
            "https://push2.eastmoney.com/api/qt/clist/get",
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=15,
            max_retries=5,
        )
        rows = []
        for item in ((payload.get("data") or {}).get("diff") or []):
            rows.append(
                {
                    "code": str(item.get("f12", "")).zfill(6),
                    "name": item.get("f14", ""),
                    "board_code": board_code,
                    "price": _safe_float(item.get("f2")),
                    "change_pct": _safe_float(item.get("f3")),
                    "amount": _safe_float(item.get("f6")),
                    "turnover_pct": _safe_float(item.get("f8")),
                    "main_net": _safe_float(item.get("f62")),
                    "float_mcap": _safe_float(item.get("f21")),
                    "total_mcap": _safe_float(item.get("f20")),
                }
            )
        return rows

    def get_eastmoney_board_list(self, board_type: str = "concept", page_size: int = 500) -> ProviderEnvelope:
        return self._guard(
            "eastmoney_board_list",
            lambda: self._ok({"records": self.eastmoney_board_list(board_type, page_size)}, source="eastmoney_board_list"),
        )

    def get_eastmoney_board_constituents(self, board_code: str, page_size: int = 500) -> ProviderEnvelope:
        return self._guard(
            "eastmoney_board_constituents",
            lambda: self._ok({"records": self.eastmoney_board_constituents(board_code, page_size)}, source="eastmoney_board_constituents"),
        )

    def dragon_tiger_board(self, code: str, trade_date: str, look_back: int = 30) -> dict:
        end = datetime.strptime(trade_date, "%Y-%m-%d")
        start = (end - timedelta(days=look_back)).strftime("%Y-%m-%d")
        rows = eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f'(SECURITY_CODE="{code}")(TRADE_DATE>="{start}")(TRADE_DATE<="{trade_date}")',
            page_size=50,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )
        return {"records": rows}

    def get_dragon_tiger(self, symbol: str, trade_date: str, look_back: int = 30) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "eastmoney_dragon_tiger",
            lambda: self._ok(self.dragon_tiger_board(code, trade_date, look_back), source="eastmoney_datacenter"),
        )

    def get_lockup_expiry(self, symbol: str, trade_date: str, forward_days: int = 90) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        end = (datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)).strftime("%Y-%m-%d")
        return self._guard(
            "eastmoney_lockup_expiry",
            lambda: self._ok(
                {
                    "records": eastmoney_datacenter(
                        "RPT_LIFT_STAGE",
                        filter_str=f'(SECURITY_CODE="{code}")(LIFT_DATE>="{trade_date}")(LIFT_DATE<="{end}")',
                        page_size=50,
                        sort_columns="LIFT_DATE",
                        sort_types="1",
                    )
                },
                source="eastmoney_datacenter",
            ),
        )

    def get_margin_trading(self, symbol: str, page_size: int = 30) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "eastmoney_margin_trading",
            lambda: self._ok(
                {
                    "records": eastmoney_datacenter(
                        "RPTA_WEB_RZRQ_GGMX",
                        filter_str=f'(SCODE="{code}")',
                        page_size=min(page_size, 50),
                        sort_columns="DATE",
                        sort_types="-1",
                    ),
                    "note": "融资融券为日级筹码/杠杆指标，需结合价格和成交量确认。",
                },
                source="eastmoney_datacenter",
            ),
        )

    def get_block_trades(self, symbol: str, page_size: int = 20) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "eastmoney_block_trades",
            lambda: self._ok(
                {
                    "records": eastmoney_datacenter(
                        "RPT_DATA_BLOCKTRADE",
                        filter_str=f'(SECURITY_CODE="{code}")',
                        page_size=min(page_size, 50),
                        sort_columns="TRADE_DATE",
                        sort_types="-1",
                    ),
                    "note": "大宗交易需关注折溢价、买卖方和后续减持压力。",
                },
                source="eastmoney_datacenter",
            ),
        )

    def get_holder_changes(self, symbol: str, page_size: int = 10) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "eastmoney_holder_changes",
            lambda: self._ok(
                {"records": eastmoney_datacenter("RPT_HOLDERNUMLATEST", filter_str=f'(SECURITY_CODE="{code}")', page_size=page_size)},
                source="eastmoney_datacenter",
            ),
        )

    def get_dividends(self, symbol: str, page_size: int = 20) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "eastmoney_dividends",
            lambda: self._ok(
                {
                    "records": eastmoney_datacenter(
                        "RPT_SHAREBONUS_DET",
                        filter_str=f'(SECURITY_CODE="{code}")',
                        page_size=min(page_size, 50),
                        sort_columns="EX_DIVIDEND_DATE",
                        sort_types="-1",
                    )
                },
                source="eastmoney_datacenter",
            ),
        )

    def get_industry_comparison(self, top_n: int = 20) -> ProviderEnvelope:
        def run():
            params = {
                "pn": "1",
                "pz": "100",
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fs": "m:90+t:2",
                "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
            }
            r = em_get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params=params,
                headers={"User-Agent": UA},
                timeout=15,
            )
            r.raise_for_status()
            rows = []
            for idx, item in enumerate(r.json().get("data", {}).get("diff", []) or []):
                rows.append(
                    {
                        "rank": idx + 1,
                        "name": item.get("f14", ""),
                        "change_pct": item.get("f3", 0),
                        "code": item.get("f12", ""),
                        "up_count": item.get("f104", 0),
                        "down_count": item.get("f105", 0),
                        "leader": item.get("f140", ""),
                        "leader_change": item.get("f136", 0),
                    }
                )
            return self._ok(
                {"top": rows[:top_n], "bottom": rows[-min(top_n, len(rows)):], "total": len(rows)},
                source="eastmoney_industry_comparison",
                evidence=rows[:5],
            )

        env = self._guard("eastmoney_industry_comparison", run)
        if env.status == "ok":
            return env

        try:
            rows = self.ths_hot_reason(_today())
            themes = _theme_summary(rows)
            fallback = self._ok(
                {
                    "fallback_note": "Eastmoney industry ranking failed; using THS hot-theme summary instead. This is not a sector ranking.",
                    "theme_summary": themes[:top_n],
                    "records": _limit_records(rows, top_n),
                },
                source="eastmoney_industry_comparison_fallback_ths_hot",
                evidence=_limit_records(rows, 5),
                contract_fulfilled=False,
                fallback_level="partial",
            )
            fallback.errors.extend(env.errors)
            return fallback
        except Exception as exc:
            env.errors.append(f"ths hot fallback: {exc}")
            return env

    def daily_dragon_tiger(
        self, trade_date: str | None = None, min_net_buy_wan: float | None = None, limit: int = 20
    ) -> dict:
        """Layer 3.8: full-market dragon tiger list, filtered by net-buy strength."""
        trade_date = trade_date or _today()
        data = eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
            page_size=500,
            sort_columns="BILLBOARD_NET_AMT",
            sort_types="-1",
        )
        stocks = []
        for row in data:
            net_buy = _safe_float(row.get("BILLBOARD_NET_AMT")) / 10000
            if min_net_buy_wan is not None and net_buy < min_net_buy_wan:
                continue
            stocks.append(
                {
                    "code": row.get("SECURITY_CODE", ""),
                    "name": row.get("SECURITY_NAME_ABBR", ""),
                    "reason": row.get("EXPLANATION", ""),
                    "close": row.get("CLOSE_PRICE") or 0,
                    "change_pct": round(_safe_float(row.get("CHANGE_RATE")), 2),
                    "net_buy_wan": round(net_buy, 1),
                    "buy_wan": round(_safe_float(row.get("BILLBOARD_BUY_AMT")) / 10000, 1),
                    "sell_wan": round(_safe_float(row.get("BILLBOARD_SELL_AMT")) / 10000, 1),
                    "turnover_pct": round(_safe_float(row.get("TURNOVERRATE")), 2),
                }
            )
        stocks = _limit_abs(stocks, "net_buy_wan", limit)
        return {"date": trade_date, "total_records": len(stocks), "stocks": stocks}

    def get_daily_dragon_tiger(
        self, trade_date: str | None = None, min_net_buy_wan: float | None = None, limit: int = 20
    ) -> ProviderEnvelope:
        return self._guard(
            "eastmoney_daily_dragon_tiger",
            lambda: self._ok(
                self.daily_dragon_tiger(trade_date, min_net_buy_wan, limit),
                source="eastmoney_datacenter",
            ),
        )

    def stock_fund_flow_120d(self, code: str) -> list[dict]:
        """Layer 4.5: 120-day stock fund flow, unit: 元."""
        params = {
            "secid": get_secid(code),
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            "lmt": "120",
        }
        r = em_get(
            "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get",
            params=params,
            headers={
                "User-Agent": UA,
                "Referer": "https://quote.eastmoney.com/",
                "Origin": "https://quote.eastmoney.com",
            },
            timeout=15,
        )
        r.raise_for_status()
        rows = []
        for line in r.json().get("data", {}).get("klines", []) or []:
            parts = line.split(",")
            if len(parts) >= 6:
                rows.append(
                    {
                        "date": parts[0],
                        "main_net": _safe_float(parts[1]),
                        "small_net": _safe_float(parts[2]),
                        "mid_net": _safe_float(parts[3]),
                        "large_net": _safe_float(parts[4]),
                        "super_net": _safe_float(parts[5]),
                    }
                )
        return rows

    def get_stock_fund_flow_120d(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)

        def run():
            records = self.stock_fund_flow_120d(code)
            recent_20 = records[-20:]
            summary = {
                "main_net_20d_yi": round(sum(r["main_net"] for r in recent_20) / 1e8, 4),
                "main_net_60d_yi": round(sum(r["main_net"] for r in records[-60:]) / 1e8, 4),
                "main_net_120d_yi": round(sum(r["main_net"] for r in records[-120:]) / 1e8, 4),
                "unit_raw": "元",
            }
            return self._ok(
                {
                    "summary": summary,
                    "records": _recent_records(records, 60),
                    "note": "push2/push2his 资金流原始单位是元，报告必须换算后注明单位。",
                },
                source="eastmoney_fund_flow_120d",
                evidence=_recent_records(records, 5),
            )

        env = self._guard("eastmoney_fund_flow_120d", run)
        if env.status == "ok":
            return env

        fallback = self._fund_flow_quote_fallback(code)
        fallback.errors.insert(0, f"eastmoney fund-flow 120d unavailable: {'; '.join(env.errors)}")
        return fallback

    def _fund_flow_quote_fallback(self, code: str) -> ProviderEnvelope:
        data: dict[str, Any] = {
            "fund_flow_available": False,
            "fallback_note": (
                "Eastmoney fund-flow endpoints are unavailable. This payload contains quote/turnover context only; "
                "main_net/super_net fields are intentionally absent."
            ),
        }
        errors: list[str] = []
        try:
            quote = self.tencent_quote([code]).get(code) or {}
            if quote:
                data["quote"] = quote
                data["liquidity_snapshot"] = {
                    "price": quote.get("price"),
                    "change_pct": quote.get("change_pct"),
                    "amount_wan": quote.get("amount_wan"),
                    "turnover_pct": quote.get("turnover_pct"),
                    "vol_ratio": quote.get("vol_ratio"),
                }
        except Exception as exc:
            errors.append(f"tencent quote fallback: {exc}")

        try:
            records = self._recent_records_for_flow_fallback(code)
            if records:
                recent = records[-20:]
                data["recent_ohlcv"] = recent
                data["turnover_context"] = {
                    "recent_days": len(recent),
                    "avg_amount": round(sum(_safe_float(r.get("Amount")) for r in recent) / len(recent), 2),
                    "avg_volume": round(sum(_safe_float(r.get("Volume")) for r in recent) / len(recent), 2),
                }
        except Exception as exc:
            errors.append(f"kline turnover fallback: {exc}")

        if len(data) <= 2:
            env = self._unavailable("Eastmoney fund-flow unavailable and quote fallback failed", source="eastmoney_fund_flow_quote_fallback")
            env.errors.extend(errors)
            return env
        env = self._ok(
            data,
            source="eastmoney_fund_flow_quote_fallback",
            evidence=[data],
            contract_fulfilled=False,
            fallback_level="diagnostic",
        )
        env.errors.extend(errors)
        return env

    def _recent_records_for_flow_fallback(self, code: str) -> list[dict]:
        try:
            return self._sina_kline_records(code, datalen=40)
        except Exception:
            return self._eastmoney_kline_records(code, "1900-01-01", "2050-01-01")[-40:]

    def get_signal_summary(self, symbol: str, trade_date: str | None = None) -> ProviderEnvelope:
        """Layer 3.9: compact synthesis of theme heat and money confirmation."""
        code = normalize_to_code(symbol)
        data: Dict[str, Any] = {}
        errors: list[str] = []
        contract_fulfilled = True
        fallback_levels: list[str] = []
        for key, func in [
            ("hot_reason", lambda: self.get_ths_hot_reason(trade_date, symbol=code, limit=30)),
            ("concept_blocks", lambda: self.get_concept_blocks(code)),
            ("intraday_fund_flow", lambda: self.get_capital_flow(code)),
            ("fund_flow_120d", lambda: self.get_stock_fund_flow_120d(code)),
            ("industry_comparison", lambda: self.get_industry_comparison(20)),
        ]:
            env = func()
            errors.extend(f"{key}: {err}" for err in env.errors)
            fallback_levels.append(env.fallback_level)
            if env.status != "ok" or not env.contract_fulfilled:
                contract_fulfilled = False
            if env.status == "ok":
                data[key] = env.data
        status = "ok" if data else "unavailable"
        return ProviderEnvelope(
            status=status,
            source="a_stock_data_signal_summary",
            as_of=_today(),
            data=data,
            errors=errors,
            evidence=[],
            contract_fulfilled=contract_fulfilled if status == "ok" else False,
            fallback_level=_combined_fallback_level(fallback_levels if status == "ok" else ["none"]),
        )

    def get_cls_telegraph_status(self) -> ProviderEnvelope:
        return self._unavailable(
            "财联社旧公开接口已在 2026-05 下线；按 SKILL.md 要求改用东财全球资讯 5.3。",
            source="cls_telegraph_status",
        )

    def get_eastmoney_guba_sentiment(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "eastmoney_guba_sentiment",
            lambda: self._ok(
                self.eastmoney_guba_sentiment(code),
                source="eastmoney_guba_sentiment",
                contract_fulfilled=False,
                fallback_level="partial",
            ),
        )

    def eastmoney_guba_sentiment(self, code: str, page_size: int = 30) -> dict:
        r = requests.get(
            f"https://guba.eastmoney.com/list,{code}.html",
            headers={"User-Agent": UA, "Referer": "https://guba.eastmoney.com/"},
            timeout=15,
        )
        r.raise_for_status()
        if not r.encoding:
            r.encoding = r.apparent_encoding or "utf-8"
        html = r.text
        posts: list[dict[str, str]] = []
        seen: set[str] = set()
        pattern = re.compile(
            rf'<a[^>]+href="(?P<href>[^"]*(?:news|question),{code},[^"]+)"[^>]*(?:title="(?P<title>[^"]+)")?[^>]*>(?P<body>.*?)</a>',
            flags=re.I | re.S,
        )
        for match in pattern.finditer(html):
            href = match.group("href")
            title = match.group("title") or _clean_html(match.group("body"))
            title = _clean_html(title).strip()
            if not title or title in seen:
                continue
            seen.add(title)
            posts.append({"title": title[:120], "url": f"https://guba.eastmoney.com{href}" if href.startswith("/") else href})
            if len(posts) >= page_size:
                break
        if not posts:
            raise RuntimeError("guba page returned no parsable posts; page markup may have changed or IP was challenged")

        bullish_words = ("利好", "上涨", "看多", "买入", "突破", "增持", "涨停", "强势")
        bearish_words = ("利空", "下跌", "看空", "卖出", "减持", "破位", "跌停", "风险")
        bullish = sum(any(word in item["title"] for word in bullish_words) for item in posts)
        bearish = sum(any(word in item["title"] for word in bearish_words) for item in posts)
        score = round((bullish - bearish) / max(len(posts), 1), 4)
        return {
            "records": posts,
            "summary": {
                "post_count": len(posts),
                "bullish_title_hits": bullish,
                "bearish_title_hits": bearish,
                "sentiment_score": score,
                "note": "Lightweight title-keyword scan from Eastmoney Guba public page; not a volume-weighted sentiment model.",
            },
        }

    def get_xueqiu_sentiment(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        cookie = os.getenv("XUEQIU_COOKIE")
        if not cookie:
            return self._unavailable(
                f"雪球讨论搜索通常需要登录 Cookie；设置 XUEQIU_COOKIE 后可尝试抓取；symbol={code}",
                source="xueqiu_cookie_required",
            )

        def run():
            r = requests.get(
                "https://xueqiu.com/query/v1/search/status.json",
                params={"q": code, "count": "20", "page": "1"},
                headers={
                    "User-Agent": UA,
                    "Referer": f"https://xueqiu.com/S/{get_prefix(code).upper()}{code}",
                    "Cookie": cookie,
                },
                timeout=15,
            )
            if r.status_code in (401, 403):
                return self._unavailable("XUEQIU_COOKIE is invalid or expired", source="xueqiu_cookie_required")
            r.raise_for_status()
            payload = r.json()
            rows = payload.get("list") or payload.get("data") or []
            records = []
            for item in rows[:20]:
                if not isinstance(item, dict):
                    continue
                text = _clean_html(str(item.get("text") or item.get("title") or ""))
                if text:
                    records.append({"text": text[:200], "created_at": item.get("created_at"), "user": item.get("user", {}).get("screen_name") if isinstance(item.get("user"), dict) else ""})
            if not records:
                return self._unavailable("xueqiu search returned no parsable discussion records", source="xueqiu")
            return self._ok(
                {"records": records},
                source="xueqiu",
                evidence=records[:5],
                contract_fulfilled=False,
                fallback_level="partial",
            )

        return self._guard("xueqiu", run)

    def _cninfo_orgid(self, code: str) -> str:
        global _CNINFO_ORGID_MAP
        if not _CNINFO_ORGID_MAP:
            try:
                r = requests.get(
                    "http://www.cninfo.com.cn/new/data/szse_stock.json",
                    headers={"User-Agent": UA},
                    timeout=15,
                )
                r.raise_for_status()
                _CNINFO_ORGID_MAP = {s["code"]: s["orgId"] for s in r.json().get("stockList", [])}
            except Exception:
                _CNINFO_ORGID_MAP = {}
        org = _CNINFO_ORGID_MAP.get(code)
        if org:
            return org
        if code.startswith("6"):
            return f"gssh0{code}"
        if code.startswith(("8", "4")):
            return f"gsbj0{code}"
        return f"gssz0{code}"

    def cninfo_announcements(self, code: str, page_size: int = 30) -> list[dict]:
        payload = {
            "stock": f"{code},{self._cninfo_orgid(code)}",
            "tabName": "fulltext",
            "pageSize": str(page_size),
            "pageNum": "1",
            "column": "",
            "category": "",
            "plate": "",
            "seDate": "",
            "searchkey": "",
            "secid": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        r = requests.post(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data=payload,
            headers={
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.cninfo.com.cn/new/disclosure",
                "Origin": "https://www.cninfo.com.cn",
            },
            timeout=15,
        )
        r.raise_for_status()
        rows = []
        for item in r.json().get("announcements", []) or []:
            rows.append(
                {
                    "title": item.get("announcementTitle", ""),
                    "type": item.get("announcementTypeName", ""),
                    "date": _cninfo_ts_to_date(item.get("announcementTime")),
                    "url": f"https://www.cninfo.com.cn/new/disclosure/detail?annoId={item.get('announcementId', '')}",
                }
            )
        return rows

    def get_announcements(self, symbol: str, page_size: int = 30) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        return self._guard(
            "cninfo_announcements",
            lambda: self._ok({"records": self.cninfo_announcements(code, page_size)}, source="cninfo_announcements"),
        )

    def get_full_valuation(self, symbol: str) -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        data: Dict[str, Any] = {}
        errors = []
        try:
            data["quote"] = self.tencent_quote([code]).get(code, {})
        except Exception as exc:
            errors.append(f"quote: {exc}")
        try:
            reports = self.eastmoney_reports(code, max_pages=1)
            data["research_report_count"] = len(reports)
            data["eps_forecasts"] = [
                {
                    "publishDate": r.get("publishDate"),
                    "orgSName": r.get("orgSName"),
                    "predictThisYearEps": r.get("predictThisYearEps"),
                    "predictNextYearEps": r.get("predictNextYearEps"),
                }
                for r in reports[:10]
            ]
        except Exception as exc:
            errors.append(f"reports: {exc}")

        quote = data.get("quote") or {}
        eps_values = [
            _safe_float(r.get("predictThisYearEps"), default=0)
            for r in data.get("eps_forecasts", [])
            if _safe_float(r.get("predictThisYearEps"), default=0) > 0
        ]
        eps_cur = sum(eps_values) / len(eps_values) if eps_values else None
        price = quote.get("price")
        if eps_cur and price:
            data["pe_fwd"] = round(price / eps_cur, 1)
        data["peg_note"] = "PEG requires forward EPS growth; use report evidence when available."
        env = self._ok(
            data,
            source=self.source,
            evidence=[data],
            contract_fulfilled=not errors,
            fallback_level="partial" if errors else "none",
        )
        env.errors.extend(errors)
        return env

    def _f10_fallback_text(self, code: str, category: str) -> str:
        parts = [
            f"mootdx F10 `{category}` unavailable; generated fallback from public web sources.",
        ]
        if "公司" in category or "概况" in category:
            info_env = self.get_eastmoney_stock_info(code)
            if info_env.status == "ok":
                parts.append("Public stock info:\n" + json.dumps(info_env.data.get("info", {}), ensure_ascii=False, indent=2, default=str))
                if info_env.errors:
                    parts.append("Stock info fallback errors:\n" + "; ".join(info_env.errors))
            else:
                parts.append("Public stock info unavailable:\n" + "; ".join(info_env.errors))
        elif "财务" in category:
            for report_type, label in (("lrb", "income"), ("fzb", "balance"), ("llb", "cashflow")):
                rows = self.sina_financial_report(code, report_type, num=3)
                parts.append(f"Sina {label} report:\n" + pd.DataFrame(rows).to_csv(index=False))
        elif "股东" in category:
            holders = self.get_holder_changes(code, page_size=10)
            blocks = self.get_block_trades(code, page_size=10)
            dividends = self.get_dividends(code, page_size=10)
            for label, env in (("holder_changes", holders), ("block_trades", blocks), ("dividends", dividends)):
                if env.status == "ok":
                    rows = env.data.get("records", [])
                    parts.append(f"{label}:\n" + pd.DataFrame(rows).to_csv(index=False))
                elif env.errors:
                    parts.append(f"{label} unavailable: {'; '.join(env.errors)}")
        else:
            rows = self.cninfo_announcements(code, page_size=30)
            parts.append("Cninfo latest announcements:\n" + pd.DataFrame(rows).to_csv(index=False))
        return "\n\n".join(parts)

    def get_f10(self, symbol: str, category: str = "最新提示") -> ProviderEnvelope:
        code = normalize_to_code(symbol)
        env = self._guard(
            "mootdx_f10",
            lambda: self._ok({"category": category, "text": self._client().F10(symbol=code, name=category)}, source="mootdx_f10"),
        )
        if env.status == "ok":
            return env

        errors = [f"mootdx: {'; '.join(env.errors)}"]
        try:
            text = self._f10_fallback_text(code, category)
        except Exception as exc:
            fallback = self._unavailable("mootdx F10 unavailable and fallback sources failed", source="mootdx_f10_fallback")
            fallback.errors.extend(errors + [f"fallback: {exc}"])
            return fallback

        fallback = self._ok(
            {"category": category, "text": text},
            source="mootdx_f10_fallback",
            evidence=[{"text": text[:500]}],
            contract_fulfilled=False,
            fallback_level="partial",
        )
        fallback.errors.extend(errors)
        return fallback

    def get_f10_announcement_summary(self, symbol: str) -> ProviderEnvelope:
        env = self.get_f10(symbol, category="最新提示")
        if env.status != "ok":
            return env
        text = str(env.data.get("text", ""))
        keywords = ["公告", "分红", "股东大会", "停牌", "复牌", "减持", "质押", "问询", "风险"]
        lines = [line for line in text.splitlines() if any(k in line for k in keywords)]
        summary = "\n".join(lines[:80]) if lines else text[:4000]
        out = self._ok(
            {
                "category": "最新提示",
                "text": summary,
                "filter_note": "F10 最新提示仅保留公告/分红/停复牌/减持/质押/问询等关键段落，避免 token 过载。",
            },
            source="mootdx_f10_announcement_summary",
            evidence=[{"text": summary[:500]}],
            contract_fulfilled=env.contract_fulfilled,
            fallback_level=env.fallback_level,
        )
        out.errors.extend(env.errors)
        return out


_PROVIDER = AStockDataProvider()


def _format_astock(method: str, env: ProviderEnvelope) -> str:
    return serialize_envelope(env, title=f"A-Share {method}")


def get_astock_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    return _format_astock("Stock Data", _PROVIDER.get_stock_data(symbol, start_date, end_date))


def get_astock_main_board_screener(
    min_lot_amount: float = 2000.0,
    max_lot_amount: float = 3000.0,
    limit: int = 50,
    max_turnover_pct: float | None = 10.0,
    volume_growth_days: int = 3,
    ma_slope_days: int = 3,
    kline_lookback_days: int = 45,
    recent_position_days: int = 20,
    kline_request_interval: float = 1.8,
    eastmoney_min_interval: float = 1.8,
) -> str:
    return _format_astock(
        "Main Board Screener",
        _PROVIDER.screen_main_board_candidates(
            min_lot_amount=min_lot_amount,
            max_lot_amount=max_lot_amount,
            limit=limit,
            max_turnover_pct=max_turnover_pct,
            volume_growth_days=volume_growth_days,
            ma_slope_days=ma_slope_days,
            kline_lookback_days=kline_lookback_days,
            recent_position_days=recent_position_days,
            kline_request_interval=kline_request_interval,
            eastmoney_min_interval=eastmoney_min_interval,
        ),
    )


def get_astock_indicator(symbol: str, indicator: str, curr_date: str, look_back_days: int = 30) -> str:
    return _format_astock("Indicator", _PROVIDER.get_indicators(symbol, indicator, curr_date, look_back_days))


def get_astock_fundamentals(ticker: str, curr_date: str = None) -> str:
    return _format_astock("Fundamentals", _PROVIDER.get_fundamentals(ticker, curr_date))


def get_astock_balance_sheet(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _format_astock("Balance Sheet", _PROVIDER.get_balance_sheet(ticker, freq, curr_date))


def get_astock_cashflow(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _format_astock("Cashflow", _PROVIDER.get_cashflow(ticker, freq, curr_date))


def get_astock_income_statement(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _format_astock("Income Statement", _PROVIDER.get_income_statement(ticker, freq, curr_date))


def get_astock_news(ticker: str, start_date: str, end_date: str) -> str:
    return _format_astock("News", _PROVIDER.get_news(ticker, start_date, end_date))


def get_astock_global_news(curr_date: str, look_back_days: int = 7, limit: int = 50) -> str:
    return _format_astock("Global News", _PROVIDER.get_global_news(curr_date, look_back_days, limit))


def get_astock_insider_equivalent(ticker: str) -> str:
    data: Dict[str, Any] = {}
    errors: List[str] = []
    for key, func in [
        ("holder_changes", lambda: _PROVIDER.get_holder_changes(ticker)),
        ("block_trades", lambda: _PROVIDER.get_block_trades(ticker)),
        ("dividends", lambda: _PROVIDER.get_dividends(ticker)),
    ]:
        env = func()
        if env.status == "ok":
            data[key] = env.data.get("records", env.data)
        else:
            errors.extend(env.errors)
    status = "ok" if data else "unavailable"
    env = ProviderEnvelope(
        status=status,
        source="a_stock_data_insider_equivalent",
        as_of=_today(),
        data=data,
        errors=errors,
        contract_fulfilled=(status == "ok" and not errors),
        fallback_level="partial" if status == "ok" and errors else "none",
    )
    return _format_astock("Insider Equivalent", env)
