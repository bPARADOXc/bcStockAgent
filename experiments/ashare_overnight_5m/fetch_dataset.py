#!/usr/bin/env python3
"""Build a risk-controlled A-share main-board overnight 5-minute dataset.

The network paths intentionally reuse the repository's existing Tencent quote
and Eastmoney K-line provider helpers.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tradingagents.dataflows import a_stock_data_provider as provider_module  # noqa: E402
from tradingagents.dataflows.a_stock_data_provider import (  # noqa: E402
    AStockDataProvider,
    UA,
    em_get,
    get_secid,
    normalize_to_code,
)
from tradingagents.dataflows.ashare_main_board_screener import (  # noqa: E402
    MAIN_BOARD_PREFIXES,
    RISK_NAME_MARKERS,
    chunked,
    generate_main_board_codes,
)


CN_TZ = ZoneInfo("Asia/Shanghai")
AFTERNOON_TIMES = ("14:30", "14:35", "14:40", "14:45", "14:50", "14:55", "15:00")
NEXT_MORNING_TIMES = ("09:40", "09:45", "09:50", "09:55", "10:00", "10:05")
PRICE_MA_WINDOWS = (5, 10, 60)
VOLUME_MA_WINDOWS = (5, 10)
MIN_REQUEST_INTERVAL = 1.0
DEFAULT_REQUEST_INTERVAL = 1.8
SOURCE_POLICY_VERSION = "mootdx_sina_eastmoney_raw_v2"
SINA_MAX_BARS = 1023
TDX_MAX_SERVER_PROBES = 3


class NoDataError(RuntimeError):
    """The symbol has no usable bars; this must not trip the circuit breaker."""


class InfrastructureFetchError(RuntimeError):
    """All eligible sources failed for retryable infrastructure reasons."""


@dataclass(frozen=True)
class MinuteFetchResult:
    records: list[dict]
    source: str
    adjustment: str = "none"


@dataclass(frozen=True)
class Stock:
    code: str
    name: str

    @property
    def is_risk_name(self) -> bool:
        upper = self.name.upper()
        return any(marker in upper for marker in RISK_NAME_MARKERS)


def compact_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def is_main_board_code(code: str) -> bool:
    return len(code) == 6 and code.isdigit() and code.startswith(MAIN_BOARD_PREFIXES)


def safe_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if pd.notna(number) else None


def fetch_eastmoney_5m(code: str, start: date, end: date) -> list[dict]:
    """Fetch unadjusted 5-minute bars through the existing EM helper."""
    params = {
        "secid": get_secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": "5",
        "fqt": "0",
        "beg": compact_date(start),
        "end": compact_date(end),
        "lmt": "1000000",
    }
    response = em_get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params=params,
        headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
        timeout=25,
        max_retries=5,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") or {}
    records: list[dict] = []
    for line in data.get("klines") or []:
        parts = str(line).split(",")
        if len(parts) < 7:
            continue
        records.append(
            {
                "timestamp": parts[0],
                "open": safe_float(parts[1]),
                "close": safe_float(parts[2]),
                "high": safe_float(parts[3]),
                "low": safe_float(parts[4]),
                # Eastmoney minute volume is in lots. Store shares consistently.
                "volume": (safe_float(parts[5]) or 0.0) * 100.0,
                "amount": safe_float(parts[6]),
            }
        )
    return records


def fetch_eastmoney_market_calendar(start: date, end: date) -> list[str]:
    """Last-resort calendar from Shanghai Composite daily bars."""
    params = {
        "secid": "1.000001",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "klt": "101",
        "fqt": "0",
        "beg": compact_date(start),
        "end": compact_date(end),
        "lmt": "10000",
    }
    response = em_get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params=params,
        headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
        timeout=25,
        max_retries=5,
    )
    response.raise_for_status()
    lines = ((response.json().get("data") or {}).get("klines") or [])
    return sorted({str(line).split(",", 1)[0] for line in lines if line})


def _sina_jsonp_rows(response: requests.Response) -> list[dict]:
    response.raise_for_status()
    match = re.search(r"var\s+data=\((.*)\)\s*;?\s*$", response.text, flags=re.S)
    if not match:
        raise ValueError("新浪响应不是预期的K线JSONP")
    payload = json.loads(match.group(1))
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ValueError("新浪K线JSONP载荷不是列表")
    return [row for row in payload if isinstance(row, dict)]


def fetch_sina_kline(
    session: requests.Session,
    code: str,
    *,
    scale: int,
    datalen: int,
    market_prefix: str | None = None,
    timeout: int = 20,
) -> list[dict]:
    """Fetch one Sina K-line response using the repository's existing endpoint."""
    prefix = market_prefix or ("sh" if code.startswith("6") else "sz")
    response = session.get(
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20data=/CN_MarketDataService.getKLineData",
        params={"symbol": f"{prefix}{code}", "scale": str(scale), "ma": "no", "datalen": str(datalen)},
        timeout=timeout,
    )
    rows = _sina_jsonp_rows(response)
    records: list[dict] = []
    for row in rows:
        timestamp = row.get("day")
        if not timestamp:
            continue
        records.append(
            {
                "timestamp": timestamp,
                "open": safe_float(row.get("open")),
                "close": safe_float(row.get("close")),
                "high": safe_float(row.get("high")),
                "low": safe_float(row.get("low")),
                # Sina reports stock volume in shares.
                "volume": safe_float(row.get("volume")) or 0.0,
                "amount": safe_float(row.get("amount")),
            }
        )
    return records


def fetch_market_calendar_with_fallback(
    session: requests.Session,
    start: date,
    end: date,
    *,
    source_retries: int,
    eastmoney_retries: int,
) -> tuple[list[str], str]:
    """Prefer Sina for the calendar and use Eastmoney only as last resort."""
    errors: list[str] = []
    for attempt in range(max(source_retries, 1)):
        try:
            rows = fetch_sina_kline(session, "000001", scale=240, datalen=180, market_prefix="sh")
            dates = sorted(
                {
                    str(row["timestamp"])[:10]
                    for row in rows
                    if start.isoformat() <= str(row.get("timestamp", ""))[:10] <= end.isoformat()
                }
            )
            if dates:
                return dates, "sina_shanghai_composite_calendar"
            errors.append("sina calendar empty")
            break
        except Exception as exc:
            errors.append(f"sina calendar attempt {attempt + 1}: {exc}")
            if attempt + 1 < max(source_retries, 1):
                time.sleep(1.5 * (2**attempt) + random.uniform(0.1, 0.5))

    logging.warning("新浪交易日历不可用，最后兜底东方财富：%s", " | ".join(errors[-3:]))
    last_error: Exception | None = None
    for attempt in range(max(eastmoney_retries, 1)):
        try:
            dates = fetch_eastmoney_market_calendar(start, end)
            if dates:
                return dates, "eastmoney_last_resort_calendar"
            last_error = RuntimeError("东方财富交易日历为空")
        except Exception as exc:
            last_error = exc
        if attempt + 1 < max(eastmoney_retries, 1):
            delay = min(2.0 * (2**attempt), 30.0) + random.uniform(0.2, 0.8)
            logging.warning("东方财富交易日历最后兜底失败，%.1fs后重试", delay)
            time.sleep(delay)
    raise InfrastructureFetchError(f"交易日历所有来源均失败：{last_error}")


def _filter_bar_range(records: Sequence[dict], start: date, end: date) -> list[dict]:
    filtered: list[dict] = []
    for record in records:
        timestamp = pd.to_datetime(record.get("timestamp"), errors="coerce")
        if pd.isna(timestamp) or not (start <= timestamp.date() <= end):
            continue
        normalized = dict(record)
        normalized["timestamp"] = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        filtered.append(normalized)
    return filtered


def _sina_result_is_truncated(records: Sequence[dict], required_start: date) -> bool:
    if len(records) < SINA_MAX_BARS:
        return False
    timestamps = pd.to_datetime([row.get("timestamp") for row in records], errors="coerce")
    valid = [value for value in timestamps if not pd.isna(value)]
    return not valid or min(value.date() for value in valid) > required_start


class MinuteSourceChain:
    """Risk-controlled 5-minute source chain with Eastmoney strictly last."""

    def __init__(
        self,
        provider: AStockDataProvider,
        *,
        source_retries: int,
        eastmoney_retries: int,
        tdx_interval: float,
        sina_interval: float,
    ) -> None:
        self.provider = provider
        self.source_retries = max(int(source_retries), 1)
        self.eastmoney_retries = max(int(eastmoney_retries), 1)
        self.tdx_interval = max(float(tdx_interval), 0.2)
        self.sina_interval = max(float(sina_interval), 0.5)
        self.sina_session = requests.Session()
        self.sina_session.headers.update({"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"})
        self._last_tdx_call = 0.0
        self._last_sina_call = 0.0
        self._mootdx_client = None
        self._mootdx_disabled_reason = ""
        try:
            # Reuse the repository provider. If BESTIP is not configured, fail
            # closed instead of scanning public TDX servers during a bulk run.
            self._mootdx_client = provider._client()
        except Exception as exc:
            configured_error = str(exc)
            try:
                from mootdx.consts import HQ_HOSTS
                from mootdx.quotes import Quotes

                probe_errors: list[str] = []
                for _, address, port in HQ_HOSTS[:TDX_MAX_SERVER_PROBES]:
                    try:
                        self._mootdx_client = Quotes.factory(
                            market="std",
                            server=(address, int(port)),
                            timeout=4,
                            auto_retry=True,
                            raise_exception=True,
                        )
                        provider._mootdx_client = self._mootdx_client
                        logging.info("mootdx 使用受限探测节点 %s:%s", address, port)
                        break
                    except Exception as probe_exc:
                        probe_errors.append(f"{address}:{port} {probe_exc}")
                if self._mootdx_client is None:
                    raise RuntimeError("；".join(probe_errors[-3:]))
            except Exception as fallback_exc:
                self._mootdx_disabled_reason = f"configured={configured_error}; probes={fallback_exc}"
                logging.warning("mootdx 首选源不可用，本轮禁用：%s", self._mootdx_disabled_reason)

    @staticmethod
    def _sleep_for_interval(last_call: float, interval: float) -> None:
        wait = interval - (time.monotonic() - last_call)
        if wait > 0:
            time.sleep(wait + random.uniform(0.05, 0.2))

    def _fetch_mootdx(self, code: str, start: date, end: date) -> list[dict]:
        if self._mootdx_client is None:
            return []
        all_rows: list[dict] = []
        for offset in range(0, 3200, 800):
            self._sleep_for_interval(self._last_tdx_call, self.tdx_interval)
            try:
                raw = self._mootdx_client.bars(symbol=code, frequency="5m", start=offset, offset=800)
            finally:
                self._last_tdx_call = time.monotonic()
            if raw is None:
                break
            frame = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
            if frame.empty:
                break
            if "datetime" not in frame.columns and "date" not in frame.columns:
                frame = frame.reset_index()
            timestamp_column = "datetime" if "datetime" in frame.columns else "date" if "date" in frame.columns else frame.columns[0]
            volume_column = "volume" if "volume" in frame.columns else "vol" if "vol" in frame.columns else None
            for _, row in frame.iterrows():
                all_rows.append(
                    {
                        "timestamp": row.get(timestamp_column),
                        "open": safe_float(row.get("open")),
                        "close": safe_float(row.get("close")),
                        "high": safe_float(row.get("high")),
                        "low": safe_float(row.get("low")),
                        "volume": safe_float(row.get(volume_column)) if volume_column else 0.0,
                        "amount": safe_float(row.get("amount")),
                    }
                )
            timestamps = pd.to_datetime([row.get("timestamp") for row in all_rows], errors="coerce")
            valid = [value for value in timestamps if not pd.isna(value)]
            if len(frame) < 800 or (valid and min(value.date() for value in valid) <= start):
                break
        return _filter_bar_range(all_rows, start, end)

    def _fetch_sina(self, code: str, start: date, end: date) -> list[dict]:
        last_error: Exception | None = None
        for attempt in range(self.source_retries):
            self._sleep_for_interval(self._last_sina_call, self.sina_interval)
            try:
                rows = fetch_sina_kline(self.sina_session, code, scale=5, datalen=SINA_MAX_BARS)
                if _sina_result_is_truncated(rows, start):
                    raise NoDataError("新浪5分钟线达到1023根上限，无法覆盖完整实验窗口")
                return _filter_bar_range(rows, start, end)
            except NoDataError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.source_retries:
                    time.sleep(1.2 * (2**attempt) + random.uniform(0.1, 0.5))
            finally:
                self._last_sina_call = time.monotonic()
        raise InfrastructureFetchError(f"新浪重试耗尽：{last_error}")

    def _fetch_eastmoney_last(self, code: str, start: date, end: date) -> list[dict]:
        last_error: Exception | None = None
        for attempt in range(self.eastmoney_retries):
            try:
                rows = fetch_eastmoney_5m(code, start, end)
                return rows
            except requests.HTTPError as exc:
                last_error = exc
                status = exc.response.status_code if exc.response is not None else None
                if status not in {429, 500, 502, 503, 504}:
                    raise
            except requests.RequestException as exc:
                last_error = exc
            if attempt + 1 < self.eastmoney_retries:
                delay = min(2.0 * (2**attempt), 30.0) + random.uniform(0.2, 0.8)
                logging.warning("%s 东方财富最后兜底第%s次失败，%.1fs后重试", code, attempt + 1, delay)
                time.sleep(delay)
        raise InfrastructureFetchError(f"东方财富最后兜底重试耗尽：{last_error}")

    def fetch(self, code: str, start: date, end: date) -> MinuteFetchResult:
        fallback_notes: list[str] = []
        if self._mootdx_client is not None:
            for attempt in range(self.source_retries):
                try:
                    rows = self._fetch_mootdx(code, start, end)
                    if rows:
                        return MinuteFetchResult(rows, "mootdx_tdx_5m")
                    fallback_notes.append("mootdx empty")
                    break
                except Exception as exc:
                    fallback_notes.append(f"mootdx attempt {attempt + 1}: {exc}")
                    if attempt + 1 < self.source_retries:
                        time.sleep(0.8 * (2**attempt) + random.uniform(0.1, 0.4))

        try:
            rows = self._fetch_sina(code, start, end)
            if rows:
                return MinuteFetchResult(rows, "sina_5m")
            fallback_notes.append("sina empty")
        except Exception as exc:
            fallback_notes.append(str(exc))

        try:
            rows = self._fetch_eastmoney_last(code, start, end)
            if rows:
                return MinuteFetchResult(rows, "eastmoney_5m_last_resort")
            raise NoDataError(f"{code} 所有分钟源均无数据；" + " | ".join(fallback_notes[-4:]))
        except NoDataError:
            raise
        except Exception as exc:
            detail = " | ".join(fallback_notes[-4:])
            raise InfrastructureFetchError(f"{code} 全部分钟源失败；{detail} | {exc}") from exc

    def close(self) -> None:
        self.sina_session.close()
        client = self._mootdx_client
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass


def enrich_rolling_indicators(records: Sequence[dict]) -> pd.DataFrame:
    """Normalize bars and calculate continuous 5-minute price/volume MAs."""
    frame = pd.DataFrame(records)
    required = {"timestamp", "close", "volume"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    for column in ("open", "close", "high", "low", "volume", "amount"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["timestamp", "close", "volume"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
        .reset_index(drop=True)
    )
    if frame.empty:
        return frame

    frame["trade_date"] = frame["timestamp"].dt.strftime("%Y-%m-%d")
    frame["bar_time"] = frame["timestamp"].dt.strftime("%H:%M")
    for window in PRICE_MA_WINDOWS:
        frame[f"price_ma{window}"] = frame["close"].rolling(window, min_periods=window).mean()
    for window in VOLUME_MA_WINDOWS:
        frame[f"volume_ma{window}"] = frame["volume"].rolling(window, min_periods=window).mean()
    return frame


def record_columns() -> list[str]:
    columns = [
        "code",
        "name",
        "is_risk_name",
        "signal_date",
        "next_trade_date",
        "signal_close",
        "adjustment",
        "source",
        "source_policy",
    ]
    for bar_time in AFTERNOON_TIMES:
        prefix = f"afternoon_{bar_time.replace(':', '')}"
        columns.extend(
            [
                f"{prefix}_close",
                f"{prefix}_price_ma5",
                f"{prefix}_price_ma10",
                f"{prefix}_price_ma60",
                f"{prefix}_volume_ma5",
                f"{prefix}_volume_ma10",
            ]
        )
    for bar_time in NEXT_MORNING_TIMES:
        columns.append(f"next_{bar_time.replace(':', '')}_close")
    columns.extend(["quality_ok", "quality_flags"])
    return columns


def _row_at(group: pd.DataFrame, bar_time: str) -> pd.Series | None:
    rows = group.loc[group["bar_time"] == bar_time]
    return None if rows.empty else rows.iloc[-1]


def build_stock_day_records(
    stock: Stock,
    bars: Sequence[dict],
    market_calendar: Sequence[str],
    signal_start: date,
    signal_end: date,
    *,
    source: str = "unknown_5m_source",
    adjustment: str = "none",
) -> list[dict]:
    """Build one wide record per stock and signal trading day."""
    frame = enrich_rolling_indicators(bars)
    if frame.empty:
        return []

    calendar = sorted(dict.fromkeys(market_calendar))
    next_day = {calendar[i]: calendar[i + 1] for i in range(len(calendar) - 1)}
    grouped = {key: value for key, value in frame.groupby("trade_date", sort=True)}
    start_text, end_text = signal_start.isoformat(), signal_end.isoformat()
    output: list[dict] = []

    for signal_date in calendar:
        if signal_date < start_text or signal_date > end_text or signal_date not in grouped:
            continue
        target_date = next_day.get(signal_date)
        if not target_date:
            continue

        signal_group = grouped[signal_date]
        target_group = grouped.get(target_date, pd.DataFrame(columns=frame.columns))
        close_row = _row_at(signal_group, "15:00")
        if close_row is None:
            # Without an exact daily close, the experiment anchor is ambiguous.
            continue

        record: dict = {
            "code": stock.code,
            "name": stock.name,
            "is_risk_name": int(stock.is_risk_name),
            "signal_date": signal_date,
            "next_trade_date": target_date,
            "signal_close": safe_float(close_row["close"]),
            "adjustment": adjustment,
            "source": source,
            "source_policy": SOURCE_POLICY_VERSION,
        }
        missing: list[str] = []

        for bar_time in AFTERNOON_TIMES:
            prefix = f"afternoon_{bar_time.replace(':', '')}"
            row = _row_at(signal_group, bar_time)
            values = {
                f"{prefix}_close": None,
                f"{prefix}_price_ma5": None,
                f"{prefix}_price_ma10": None,
                f"{prefix}_price_ma60": None,
                f"{prefix}_volume_ma5": None,
                f"{prefix}_volume_ma10": None,
            }
            if row is None:
                missing.append(prefix)
            else:
                values = {
                    f"{prefix}_close": safe_float(row["close"]),
                    f"{prefix}_price_ma5": safe_float(row["price_ma5"]),
                    f"{prefix}_price_ma10": safe_float(row["price_ma10"]),
                    f"{prefix}_price_ma60": safe_float(row["price_ma60"]),
                    f"{prefix}_volume_ma5": safe_float(row["volume_ma5"]),
                    f"{prefix}_volume_ma10": safe_float(row["volume_ma10"]),
                }
                for key, value in values.items():
                    if value is None:
                        missing.append(key)
            record.update(values)

        for bar_time in NEXT_MORNING_TIMES:
            key = f"next_{bar_time.replace(':', '')}_close"
            row = _row_at(target_group, bar_time)
            value = None if row is None else safe_float(row["close"])
            record[key] = value
            if value is None:
                missing.append(key)

        record["quality_ok"] = int(not missing)
        record["quality_flags"] = ";".join(sorted(set(missing)))
        output.append(record)
    return output


def discover_universe(
    provider: AStockDataProvider,
    batch_size: int,
    quote_interval: float,
    allow_partial: bool,
) -> list[Stock]:
    """Discover listed main-board symbols through existing Tencent quotes."""
    universe: dict[str, Stock] = {}
    failures: list[str] = []
    batches = chunked(generate_main_board_codes(), batch_size)
    for index, codes in enumerate(batches, start=1):
        last_error: Exception | None = None
        quotes: dict[str, dict] = {}
        for attempt in range(3):
            try:
                quotes = provider.tencent_quote(codes)
                last_error = None
                break
            except Exception as exc:  # network boundary
                last_error = exc
                time.sleep((attempt + 1) * 1.5 + random.uniform(0.1, 0.5))
        if last_error is not None:
            failures.append(f"batch {index}: {last_error}")
        for code, quote in quotes.items():
            normalized = normalize_to_code(code)
            if is_main_board_code(normalized):
                universe[normalized] = Stock(normalized, str(quote.get("name") or ""))
        if index < len(batches):
            time.sleep(max(quote_interval, 0.2))
        if index % 10 == 0:
            logging.info("股票池进度 %s/%s，已识别 %s 只", index, len(batches), len(universe))

    if failures and not allow_partial:
        sample = " | ".join(failures[:3])
        raise RuntimeError(f"股票池有 {len(failures)} 个批次失败，为避免静默漏股已停止：{sample}")
    if failures:
        logging.warning("股票池允许部分结果：%s", " | ".join(failures[:3]))
    return sorted(universe.values(), key=lambda item: item.code)


def names_for_explicit_codes(provider: AStockDataProvider, codes: Sequence[str]) -> list[Stock]:
    quotes: dict[str, dict] = {}
    for batch in chunked(list(codes), 80):
        try:
            quotes.update(provider.tencent_quote(batch))
        except Exception as exc:
            logging.warning("代码名称查询失败，仍继续分钟线拉取：%s", exc)
    return [Stock(code, str(quotes.get(code, {}).get("name") or "")) for code in sorted(set(codes))]


def open_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    columns = record_columns()
    text_columns = {
        "code",
        "name",
        "signal_date",
        "next_trade_date",
        "adjustment",
        "source",
        "source_policy",
        "quality_flags",
    }
    integer_columns = {"is_risk_name", "quality_ok"}
    definitions = [
        f'"{column}" '
        f'{"TEXT" if column in text_columns else "INTEGER" if column in integer_columns else "REAL"}'
        for column in columns
    ]
    definitions.append("PRIMARY KEY (code, signal_date)")
    connection.execute(f'CREATE TABLE IF NOT EXISTS experiment_records ({", ".join(definitions)})')
    record_schema = {row[1] for row in connection.execute("PRAGMA table_info(experiment_records)")}
    if "source_policy" not in record_schema:
        connection.execute("ALTER TABLE experiment_records ADD COLUMN source_policy TEXT NOT NULL DEFAULT ''")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS fetch_status (
            code TEXT PRIMARY KEY,
            coverage_start TEXT NOT NULL,
            coverage_end TEXT NOT NULL,
            source_policy TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            record_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    status_columns = {row[1] for row in connection.execute("PRAGMA table_info(fetch_status)")}
    if "source_policy" not in status_columns:
        connection.execute("ALTER TABLE fetch_status ADD COLUMN source_policy TEXT NOT NULL DEFAULT ''")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_universe (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            is_risk_name INTEGER NOT NULL,
            discovered_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


def save_universe(connection: sqlite3.Connection, stocks: Sequence[Stock]) -> None:
    now = datetime.now(CN_TZ).isoformat(timespec="seconds")
    connection.executemany(
        """
        INSERT INTO stock_universe(code, name, is_risk_name, discovered_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            name=excluded.name,
            is_risk_name=excluded.is_risk_name,
            discovered_at=excluded.discovered_at
        """,
        [(stock.code, stock.name, int(stock.is_risk_name), now) for stock in stocks],
    )
    connection.commit()


def already_complete(connection: sqlite3.Connection, code: str, start: date, end: date) -> bool:
    row = connection.execute(
        "SELECT coverage_start, coverage_end, status, source_policy FROM fetch_status WHERE code=?", (code,)
    ).fetchone()
    return bool(
        row
        and row[2] in {"ok", "no_data"}
        and row[3] == SOURCE_POLICY_VERSION
        and row[0] <= start.isoformat()
        and row[1] >= end.isoformat()
    )


def save_result(
    connection: sqlite3.Connection,
    stock: Stock,
    start: date,
    end: date,
    records: Sequence[dict],
    error: str = "",
    status: str | None = None,
) -> None:
    columns = record_columns()
    final_status = status or ("error" if error else "ok")
    if final_status in {"ok", "no_data"}:
        connection.execute(
            "DELETE FROM experiment_records WHERE code=? AND signal_date BETWEEN ? AND ?",
            (stock.code, start.isoformat(), end.isoformat()),
        )
    if records:
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f'"{column}"=excluded."{column}"' for column in columns if column not in {"code", "signal_date"})
        quoted_columns = ",".join(f'"{column}"' for column in columns)
        sql = (
            f"INSERT INTO experiment_records ({quoted_columns}) "
            f"VALUES ({placeholders}) ON CONFLICT(code, signal_date) DO UPDATE SET {updates}"
        )
        connection.executemany(sql, [[record.get(column) for column in columns] for record in records])
    now = datetime.now(CN_TZ).isoformat(timespec="seconds")
    connection.execute(
        """
        INSERT INTO fetch_status(
            code, coverage_start, coverage_end, source_policy, status, record_count, last_error, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET
            coverage_start=excluded.coverage_start,
            coverage_end=excluded.coverage_end,
            source_policy=excluded.source_policy,
            status=excluded.status,
            record_count=excluded.record_count,
            last_error=excluded.last_error,
            updated_at=excluded.updated_at
        """,
        (
            stock.code,
            start.isoformat(),
            end.isoformat(),
            SOURCE_POLICY_VERSION,
            final_status,
            len(records),
            error[:2000],
            now,
        ),
    )
    connection.commit()


def export_csv(connection: sqlite3.Connection, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    first = True
    selected_columns = ",".join(f'"{column}"' for column in record_columns())
    query = f"SELECT {selected_columns} FROM experiment_records WHERE source_policy=? ORDER BY signal_date, code"
    for frame in pd.read_sql_query(query, connection, params=(SOURCE_POLICY_VERSION,), chunksize=10_000):
        frame.to_csv(destination, mode="w" if first else "a", header=first, index=False, encoding="utf-8-sig")
        total += len(frame)
        first = False
    if first:
        pd.DataFrame(columns=record_columns()).to_csv(destination, index=False, encoding="utf-8-sig")
    return total


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须是 YYYY-MM-DD") from exc


def parse_codes(raw: str) -> list[str]:
    if not raw.strip():
        return []
    codes = [normalize_to_code(item.strip()) for item in raw.split(",") if item.strip()]
    invalid = [code for code in codes if not is_main_board_code(code)]
    if invalid:
        raise ValueError(f"不是沪深主板代码：{','.join(invalid)}")
    return sorted(set(codes))


def in_continuous_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.timetz().replace(tzinfo=None)
    return dt_time(9, 15) <= current <= dt_time(15, 15)


def configure_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers.append(logging.FileHandler(output_dir / "fetch.log", encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="拉取A股主板隔夜实验所需的5分钟数据。")
    parser.add_argument("--codes", default="", help="逗号分隔的小样本代码；与 --full-market 二选一。")
    parser.add_argument("--full-market", action="store_true", help="显式确认拉取当前A股主板全市场。")
    parser.add_argument("--start-date", type=parse_iso_date, help="信号日起点，默认 end-date 前30个自然日。")
    parser.add_argument("--end-date", type=parse_iso_date, help="信号日终点，默认今天（中国时区）。")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--request-interval", type=float, default=DEFAULT_REQUEST_INTERVAL)
    parser.add_argument("--tdx-request-interval", type=float, default=0.35)
    parser.add_argument("--sina-request-interval", type=float, default=1.0)
    parser.add_argument("--source-retries", type=int, default=3)
    parser.add_argument("--eastmoney-retries", type=int, default=5)
    parser.add_argument("--quote-batch-interval", type=float, default=1.0)
    parser.add_argument("--quote-batch-size", type=int, default=80)
    parser.add_argument("--cooldown-every", type=int, default=100)
    parser.add_argument("--cooldown-seconds", type=float, default=20.0)
    parser.add_argument("--max-consecutive-failures", type=int, default=6)
    parser.add_argument("--max-infrastructure-failure-rate", type=float, default=0.20)
    parser.add_argument("--max-stocks", type=int, default=0, help="调试限量；0 表示不限制。")
    parser.add_argument("--exclude-risk-names", action="store_true", help="排除 ST、*ST、退市整理名称。")
    parser.add_argument("--allow-partial-universe", action="store_true", help="股票池批次失败时仍继续（不推荐）。")
    parser.add_argument("--allow-market-hours", action="store_true", help="允许交易时段全市场请求（不推荐）。")
    parser.add_argument("--force", action="store_true", help="忽略成功断点并重新拉取。")
    parser.add_argument("--dry-run", action="store_true", help="只生成股票池和日期范围，不拉分钟线。")
    return parser


def run(args: argparse.Namespace) -> int:
    configure_logging(args.output_dir)
    now = datetime.now(CN_TZ)
    signal_end = args.end_date or now.date()
    signal_start = args.start_date or (signal_end - timedelta(days=30))
    if signal_start > signal_end:
        raise ValueError("start-date 不能晚于 end-date")
    if signal_end > now.date():
        raise ValueError("end-date 不能晚于中国时区的今天")
    if args.request_interval < MIN_REQUEST_INTERVAL:
        raise ValueError(f"为保护现有公共数据源，request-interval 不能低于 {MIN_REQUEST_INTERVAL:.1f} 秒")
    if args.tdx_request_interval < 0.2 or args.sina_request_interval < 0.5:
        raise ValueError("风控限制：TDX请求间隔不能低于0.2秒，新浪不能低于0.5秒")
    if args.source_retries < 1 or args.eastmoney_retries < 1:
        raise ValueError("重试次数必须至少为1")
    if not 0 < args.max_infrastructure_failure_rate <= 1:
        raise ValueError("max-infrastructure-failure-rate 必须在 (0, 1] 范围")
    if args.full_market == bool(args.codes.strip()):
        raise ValueError("必须且只能选择 --codes 或 --full-market")
    if args.full_market and in_continuous_market_hours(now) and not args.allow_market_hours:
        raise RuntimeError("当前处于A股交易时段；全市场任务已拒绝。请在收盘后运行。")

    provider_module.EM_MIN_INTERVAL = max(float(args.request_interval), MIN_REQUEST_INTERVAL)
    provider = AStockDataProvider()
    if args.full_market:
        stocks = discover_universe(
            provider,
            batch_size=max(1, min(args.quote_batch_size, 100)),
            quote_interval=max(args.quote_batch_interval, 0.2),
            allow_partial=args.allow_partial_universe,
        )
    else:
        stocks = names_for_explicit_codes(provider, parse_codes(args.codes))
    if args.exclude_risk_names:
        stocks = [stock for stock in stocks if not stock.is_risk_name]
    if args.max_stocks > 0:
        stocks = stocks[: args.max_stocks]
    if not stocks:
        raise RuntimeError("股票池为空，停止运行")

    database_path = args.output_dir / "ashare_overnight_5m.sqlite3"
    csv_path = args.output_dir / "ashare_overnight_5m.csv"
    connection = open_database(database_path)
    save_universe(connection, stocks)
    logging.info(
        "任务范围：%s 至 %s，共 %s 只；源优先级=mootdx→新浪→东方财富(最后)，东财最小间隔 %.1fs",
        signal_start,
        signal_end,
        len(stocks),
        provider_module.EM_MIN_INTERVAL,
    )
    if args.dry_run:
        logging.info("dry-run 完成，股票池已写入 %s", database_path)
        connection.close()
        return 0

    # Ten calendar days before start provide ample MA60 warm-up. Ten days after
    # an explicit historical end allow locating its next exchange trading day.
    fetch_start = signal_start - timedelta(days=10)
    fetch_end = min(signal_end + timedelta(days=10), now.date())
    source_chain = MinuteSourceChain(
        provider,
        source_retries=args.source_retries,
        eastmoney_retries=args.eastmoney_retries,
        tdx_interval=args.tdx_request_interval,
        sina_interval=args.sina_request_interval,
    )
    calendar, calendar_source = fetch_market_calendar_with_fallback(
        source_chain.sina_session,
        signal_start,
        fetch_end,
        source_retries=args.source_retries,
        eastmoney_retries=args.eastmoney_retries,
    )
    if len(calendar) < 2:
        source_chain.close()
        raise RuntimeError("交易日历不足两个交易日，无法构造 next_trade_date")
    logging.info("交易日历来源：%s", calendar_source)

    consecutive_failures = 0
    completed = skipped = failed = no_data = attempted = 0
    try:
        for index, stock in enumerate(stocks, start=1):
            if not args.force and already_complete(connection, stock.code, signal_start, signal_end):
                skipped += 1
                logging.info("[%s/%s] %s 已完成，断点跳过", index, len(stocks), stock.code)
                continue
            attempted += 1
            try:
                fetch_result = source_chain.fetch(stock.code, fetch_start, fetch_end)
                records = build_stock_day_records(
                    stock,
                    fetch_result.records,
                    calendar,
                    signal_start,
                    signal_end,
                    source=fetch_result.source,
                    adjustment=fetch_result.adjustment,
                )
                save_result(connection, stock, signal_start, signal_end, records)
                completed += 1
                consecutive_failures = 0
                complete_rows = sum(int(record["quality_ok"]) for record in records)
                logging.info(
                    "[%s/%s] %s %s：%s，写入 %s 行，完整 %s 行",
                    index,
                    len(stocks),
                    stock.code,
                    stock.name,
                    fetch_result.source,
                    len(records),
                    complete_rows,
                )
            except NoDataError as exc:
                no_data += 1
                consecutive_failures = 0
                save_result(
                    connection,
                    stock,
                    signal_start,
                    signal_end,
                    [],
                    error=str(exc),
                    status="no_data",
                )
                logging.warning("[%s/%s] %s 无可用分钟数据，标记no_data，不计入熔断", index, len(stocks), stock.code)
            except Exception as exc:  # keep a durable per-stock failure checkpoint
                failed += 1
                consecutive_failures += 1
                save_result(connection, stock, signal_start, signal_end, [], error=str(exc))
                logging.exception("[%s/%s] %s 拉取失败", index, len(stocks), stock.code)
                if consecutive_failures >= args.max_consecutive_failures:
                    raise RuntimeError(
                        f"连续 {consecutive_failures} 只股票失败，触发熔断；请检查数据源后断点续跑"
                    ) from exc
                failure_rate = failed / max(attempted, 1)
                if attempted >= 30 and failed >= 5 and failure_rate > args.max_infrastructure_failure_rate:
                    raise RuntimeError(
                        f"基础设施失败率 {failure_rate:.1%} 超过阈值 "
                        f"{args.max_infrastructure_failure_rate:.1%}，触发熔断"
                    ) from exc

            if args.cooldown_every > 0 and index % args.cooldown_every == 0 and index < len(stocks):
                logging.info("完成 %s 只，冷却 %.1f 秒", index, args.cooldown_seconds)
                time.sleep(max(args.cooldown_seconds, 0.0))
    except KeyboardInterrupt:
        logging.warning("收到中断，已完成股票均已提交；下次使用同一命令可续跑")
    finally:
        source_chain.close()
        total_rows = export_csv(connection, csv_path)
        connection.close()

    logging.info(
        "结束：新完成=%s，跳过=%s，无数据=%s，基础设施失败=%s，CSV总行数=%s；%s",
        completed,
        skipped,
        no_data,
        failed,
        total_rows,
        csv_path,
    )
    return 0 if failed == 0 else 2


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(run(args))
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
