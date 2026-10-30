"""A-share main-board momentum screener.

This module keeps the screening rules pure and testable while letting
``AStockDataProvider`` supply live quote/K-line data from existing sources.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, time as dt_time
from typing import Any, Callable, Mapping, Protocol
from zoneinfo import ZoneInfo

import pandas as pd


CN_TZ = ZoneInfo("Asia/Shanghai")
MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
RISK_NAME_MARKERS = ("*ST", "ST", "退")
ProgressCallback = Callable[[str], None]


class MainBoardScreenerProvider(Protocol):
    """Duck-typed subset of AStockDataProvider used by the screener."""

    def tencent_quote(self, codes: list[str]) -> dict[str, dict]:
        """Fetch Tencent quote rows keyed by six-digit code."""

    def _baidu_kline_records(self, code: str) -> list[dict]:
        """Fetch Baidu daily K-line records."""

    def _eastmoney_kline_records(self, code: str, start_date: str = "1900-01-01", end_date: str = "") -> list[dict]:
        """Fetch Eastmoney daily K-line records."""

    def _sina_kline_records(self, code: str, datalen: int = 800) -> list[dict]:
        """Fetch Sina daily K-line records."""


@dataclass(frozen=True)
class AStockMainBoardScreenerConfig:
    """Configurable thresholds for the main-board screening strategy."""

    min_lot_amount: float = 2000.0
    max_lot_amount: float = 3000.0
    lot_size: int = 100
    min_change_pct: float = 2.0
    max_change_pct: float = 6.0
    min_vol_ratio: float = 1.0
    min_turnover_pct: float = 5.0
    max_turnover_pct: float | None = 10.0
    min_float_mcap_yi: float = 50.0
    max_float_mcap_yi: float = 200.0
    volume_growth_days: int = 3
    ma_slope_days: int = 3
    kline_lookback_days: int = 45
    min_kline_records: int = 20
    recent_position_days: int = 20
    batch_size: int = 80
    quote_batch_interval: float = 1.0
    max_quote_retries: int = 2
    kline_request_interval: float = 1.8
    eastmoney_min_interval: float = 1.8
    limit: int = 50
    codes: tuple[str, ...] | None = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_code(code: Any) -> str:
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    return digits[-6:].zfill(6) if digits else ""


def symbol_for_code(code: str) -> str:
    """Return normalized A-share symbol, e.g. 600000.SH or 000001.SZ."""
    code = _normalize_code(code)
    suffix = "SH" if code.startswith(("600", "601", "603", "605")) else "SZ"
    return f"{code}.{suffix}"


def generate_main_board_codes() -> list[str]:
    """Generate possible Shanghai/Shenzhen main-board ordinary A-share codes."""
    codes: list[str] = []
    for prefix in MAIN_BOARD_PREFIXES:
        codes.extend(f"{prefix}{i:03d}" for i in range(1000))
    return codes


def chunked(items: list[str], batch_size: int) -> list[list[str]]:
    size = max(int(batch_size), 1)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _emit_progress(progress: ProgressCallback | None, message: str) -> None:
    if not progress:
        return
    stamp = datetime.now(CN_TZ).strftime("%H:%M:%S")
    progress(f"[A股筛选 {stamp}] {message}")


def is_main_board_common_a(code: Any, name: Any = "") -> bool:
    """Return True for ordinary Shanghai/Shenzhen main-board A-shares."""
    normalized = _normalize_code(code)
    if not normalized.startswith(MAIN_BOARD_PREFIXES):
        return False
    upper_name = str(name or "").upper()
    return not any(marker in upper_name for marker in RISK_NAME_MARKERS)


def is_after_1430_cn(now: datetime | None = None) -> bool:
    """Return whether the timestamp is at/after 14:30 China time."""
    current = now or datetime.now(CN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=CN_TZ)
    current = current.astimezone(CN_TZ)
    return current.time() >= dt_time(14, 30)


def priority_signal(turnover_pct: float, vol_ratio: float) -> tuple[int, str, str]:
    """Classify the turnover/volume-ratio combination into user-defined priority buckets."""
    turnover = _safe_float(turnover_pct)
    ratio = _safe_float(vol_ratio)
    if turnover > 5 and 2 <= ratio <= 3:
        return 1, "启动信号", "换手率>5%、量比2-3，按规则属于启动信号。"
    if 5 <= turnover <= 10 and 3 < ratio <= 5:
        return 2, "资金加速主升浪", "换手率5%-10%、量比3-5，按规则属于资金加速主升浪。"
    if turnover > 10 and ratio > 5:
        return 3, "高换手高量比", "换手率>10%、量比>5，需结合位置判断低位吸筹或高位出货。"
    if turnover > 5 and ratio < 2:
        return 4, "撤退风险", "换手率>5%、量比<2，按规则偏风险，优先安全。"
    return 99, "未命中优先级", "换手率/量比组合未命中四条优先级规则。"


def quote_filter_failures(quote: Mapping[str, Any], config: AStockMainBoardScreenerConfig) -> list[str]:
    """Return failed quote-level conditions for one quote row."""
    failures: list[str] = []
    code = _normalize_code(quote.get("code"))
    name = quote.get("name", "")
    price = _safe_float(quote.get("price"))
    one_lot_amount = price * config.lot_size
    change_pct = _safe_float(quote.get("change_pct"))
    vol_ratio = _safe_float(quote.get("vol_ratio"))
    turnover_pct = _safe_float(quote.get("turnover_pct"))
    float_mcap_yi = _safe_float(quote.get("float_mcap_yi"))

    if not is_main_board_common_a(code, name):
        failures.append("not_main_board_common_a")
    if not (config.min_lot_amount <= one_lot_amount <= config.max_lot_amount):
        failures.append("lot_amount_out_of_range")
    if not (config.min_change_pct <= change_pct <= config.max_change_pct):
        failures.append("change_pct_out_of_range")
    if not (vol_ratio > config.min_vol_ratio):
        failures.append("vol_ratio_too_low")
    if not (turnover_pct >= config.min_turnover_pct):
        failures.append("turnover_too_low")
    if config.max_turnover_pct is not None and turnover_pct > config.max_turnover_pct:
        failures.append("turnover_too_high")
    if not (config.min_float_mcap_yi <= float_mcap_yi <= config.max_float_mcap_yi):
        failures.append("float_mcap_out_of_range")
    return failures


def passes_quote_filters(quote: Mapping[str, Any], config: AStockMainBoardScreenerConfig) -> bool:
    return not quote_filter_failures(quote, config)


def _records_frame(records: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(records or [])
    if df.empty:
        return df
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["Date"]).sort_values("Date")
    for col in ("Open", "High", "Low", "Close", "Volume", "Amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def _with_price_mas(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "Close" not in df.columns:
        return df
    result = df.copy()
    for window in (5, 10, 20):
        key = f"ma{window}avgprice"
        if key not in result.columns:
            result[key] = result["Close"].rolling(window, min_periods=window).mean()
        else:
            result[key] = pd.to_numeric(result[key], errors="coerce")
            missing = result[key].isna()
            if missing.any():
                result.loc[missing, key] = result["Close"].rolling(window, min_periods=window).mean().loc[missing]
    return result


def _recent_positive_values(series: pd.Series, count: int) -> list[float]:
    values = [float(v) for v in pd.to_numeric(series, errors="coerce").dropna().tolist() if float(v) > 0]
    return values[-count:]


def volume_curve_expanding(records: list[dict], days: int = 3) -> tuple[bool, list[float], str]:
    """Check whether recent daily volume is gradually expanding."""
    if days < 2:
        days = 2
    df = _records_frame(records)
    if df.empty or "Volume" not in df.columns:
        return False, [], "no_volume_data"
    values = _recent_positive_values(df["Volume"], days)
    if len(values) < days:
        return False, values, "insufficient_volume_points"
    expanding = all(values[idx] > values[idx - 1] for idx in range(1, len(values)))
    reason = "recent_volume_strictly_expanding" if expanding else "recent_volume_not_expanding"
    return expanding, values, reason


def moving_averages_upward(records: list[dict], slope_days: int = 3) -> tuple[bool, dict[str, list[float]], str]:
    """Check MA5/MA10/MA20 slope using recent daily records."""
    if slope_days < 2:
        slope_days = 2
    df = _with_price_mas(_records_frame(records))
    if df.empty or len(df) < 20:
        return False, {}, "insufficient_ma_records"

    details: dict[str, list[float]] = {}
    failed: list[str] = []
    for window in (5, 10, 20):
        key = f"ma{window}avgprice"
        if key not in df.columns:
            failed.append(key)
            continue
        values = _recent_positive_values(df[key], slope_days)
        details[f"ma{window}"] = [round(v, 4) for v in values]
        if len(values) < slope_days:
            failed.append(key)
            continue
        if not (values[-1] > values[0] and all(values[idx] >= values[idx - 1] for idx in range(1, len(values)))):
            failed.append(key)
    if failed:
        return False, details, "ma_not_upward:" + ",".join(failed)
    return True, details, "ma5_ma10_ma20_upward"


def recent_price_position(records: list[dict], days: int = 20) -> dict[str, Any]:
    """Describe current price location inside the recent trading range."""
    df = _records_frame(records)
    if df.empty or "Close" not in df.columns:
        return {
            "recent_position_days": days,
            "recent_position_pct": None,
            "position_label": "未知",
            "position_reason": "no_price_data",
        }
    window = df.tail(max(days, 2))
    high_col = "High" if "High" in window.columns else "Close"
    low_col = "Low" if "Low" in window.columns else "Close"
    recent_high = _safe_float(pd.to_numeric(window[high_col], errors="coerce").max())
    recent_low = _safe_float(pd.to_numeric(window[low_col], errors="coerce").min())
    latest_close = _safe_float(window.iloc[-1].get("Close"))
    if recent_high <= recent_low:
        position_pct = 50.0
    else:
        position_pct = (latest_close - recent_low) / (recent_high - recent_low) * 100
    if position_pct <= 35:
        label = "低位"
    elif position_pct >= 70:
        label = "高位"
    else:
        label = "中位"
    return {
        "recent_position_days": min(len(window), max(days, 2)),
        "recent_low": round(recent_low, 4),
        "recent_high": round(recent_high, 4),
        "latest_close": round(latest_close, 4),
        "recent_position_pct": round(position_pct, 2),
        "position_label": label,
        "position_reason": "close_location_in_recent_range",
    }


def evaluate_kline_requirements(records: list[dict], config: AStockMainBoardScreenerConfig) -> tuple[bool, dict[str, Any]]:
    """Evaluate volume expansion and MA slope requirements."""
    df = _records_frame(records)
    if len(df) < config.min_kline_records:
        return False, {
            "kline_records": len(df),
            "volume_curve_expanding": False,
            "ma_upward": False,
            "kline_reason": "insufficient_kline_records",
        }

    volume_ok, recent_volumes, volume_reason = volume_curve_expanding(records, config.volume_growth_days)
    ma_ok, ma_details, ma_reason = moving_averages_upward(records, config.ma_slope_days)
    latest = _with_price_mas(df).iloc[-1].to_dict() if not df.empty else {}
    detail = {
        "kline_records": len(df),
        "volume_curve_expanding": volume_ok,
        "volume_reason": volume_reason,
        "recent_volumes": [round(v, 2) for v in recent_volumes],
        "ma_upward": ma_ok,
        "ma_reason": ma_reason,
        "ma_trend": ma_details,
        "ma5": round(_safe_float(latest.get("ma5avgprice")), 4),
        "ma10": round(_safe_float(latest.get("ma10avgprice")), 4),
        "ma20": round(_safe_float(latest.get("ma20avgprice")), 4),
        **recent_price_position(records, config.recent_position_days),
    }
    return volume_ok and ma_ok, detail


def candidate_from_quote(
    quote: Mapping[str, Any],
    records: list[dict],
    config: AStockMainBoardScreenerConfig,
) -> dict[str, Any] | None:
    """Build a candidate row when quote and K-line rules all pass."""
    if not passes_quote_filters(quote, config):
        return None
    kline_ok, kline_detail = evaluate_kline_requirements(records, config)
    if not kline_ok:
        return None

    code = _normalize_code(quote.get("code"))
    price = _safe_float(quote.get("price"))
    turnover_pct = _safe_float(quote.get("turnover_pct"))
    vol_ratio = _safe_float(quote.get("vol_ratio"))
    priority, label, hint = priority_signal(turnover_pct, vol_ratio)
    return {
        "priority": priority,
        "priority_label": label,
        "action_hint": hint,
        "code": code,
        "symbol": symbol_for_code(code),
        "name": quote.get("name", ""),
        "price": round(price, 4),
        "one_lot_amount": round(price * config.lot_size, 2),
        "change_pct": round(_safe_float(quote.get("change_pct")), 4),
        "vol_ratio": round(vol_ratio, 4),
        "turnover_pct": round(turnover_pct, 4),
        "float_mcap_yi": round(_safe_float(quote.get("float_mcap_yi")), 4),
        "mcap_yi": round(_safe_float(quote.get("mcap_yi")), 4),
        "amount_wan": round(_safe_float(quote.get("amount_wan")), 4),
        **kline_detail,
    }


def base_quote_row(quote: Mapping[str, Any], config: AStockMainBoardScreenerConfig) -> dict[str, Any]:
    """Build CSV-facing fields from a quote row before K-line checks."""
    code = _normalize_code(quote.get("code"))
    price = _safe_float(quote.get("price"))
    turnover_pct = _safe_float(quote.get("turnover_pct"))
    vol_ratio = _safe_float(quote.get("vol_ratio"))
    priority, label, hint = priority_signal(turnover_pct, vol_ratio)
    return {
        "selected": False,
        "reject_reason": "",
        "kline_source": "",
        "kline_errors": "",
        "priority": priority,
        "priority_label": label,
        "action_hint": hint,
        "code": code,
        "symbol": symbol_for_code(code),
        "name": quote.get("name", ""),
        "price": round(price, 4),
        "one_lot_amount": round(price * config.lot_size, 2),
        "change_pct": round(_safe_float(quote.get("change_pct")), 4),
        "vol_ratio": round(vol_ratio, 4),
        "turnover_pct": round(turnover_pct, 4),
        "float_mcap_yi": round(_safe_float(quote.get("float_mcap_yi")), 4),
        "mcap_yi": round(_safe_float(quote.get("mcap_yi")), 4),
        "amount_wan": round(_safe_float(quote.get("amount_wan")), 4),
    }


def reject_reason_from_kline(kline_detail: Mapping[str, Any], errors: list[str]) -> str:
    """Explain why a quote-passed stock did not become a selected candidate."""
    if not kline_detail:
        return "数据未读取：K线数据源均未返回有效数据；" + "；".join(errors)
    if kline_detail.get("kline_reason") == "insufficient_kline_records":
        return f"数据不足：K线仅 {kline_detail.get('kline_records', 0)} 条，无法稳定判断MA20。"

    reasons: list[str] = []
    if not kline_detail.get("volume_curve_expanding"):
        reasons.append(f"成交量条件不满足：{kline_detail.get('volume_reason', 'unknown')}")
    if not kline_detail.get("ma_upward"):
        reasons.append(f"均线条件不满足：{kline_detail.get('ma_reason', 'unknown')}")
    return "；".join(reasons) or "未选中：K线/量能/均线条件未完全满足。"


def screened_row_from_quote(
    quote: Mapping[str, Any],
    records: list[dict],
    config: AStockMainBoardScreenerConfig,
    *,
    kline_source: str,
    errors: list[str],
) -> dict[str, Any]:
    """Return a CSV-facing row for every quote-passed stock."""
    row = base_quote_row(quote, config)
    row["kline_source"] = kline_source
    row["kline_errors"] = "；".join(errors)
    kline_ok, kline_detail = evaluate_kline_requirements(records, config) if records else (False, {})
    row.update(kline_detail)
    if kline_ok:
        row["selected"] = True
        row["reject_reason"] = ""
    else:
        row["reject_reason"] = reject_reason_from_kline(kline_detail, errors)
    return row


def _filter_recent_records(records: list[dict], start_date: str, end_date: str) -> list[dict]:
    df = _records_frame(records)
    if df.empty or "Date" not in df.columns:
        return records or []
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    df = df[(df["Date"] >= start) & (df["Date"] <= end)]
    result = df.to_dict(orient="records")
    for row in result:
        if hasattr(row.get("Date"), "strftime"):
            row["Date"] = row["Date"].strftime("%Y-%m-%d")
    return result


def fetch_recent_kline_records(
    provider: MainBoardScreenerProvider,
    code: str,
    config: AStockMainBoardScreenerConfig,
    now: datetime | None = None,
) -> tuple[list[dict], list[str], str]:
    """Fetch recent daily K-line records through existing provider methods."""
    current = now or datetime.now(CN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=CN_TZ)
    current = current.astimezone(CN_TZ)
    end_date = current.strftime("%Y-%m-%d")
    start_date = (current - timedelta(days=config.kline_lookback_days)).strftime("%Y-%m-%d")
    errors: list[str] = []

    for source, fetcher in (
        ("baidu_kline_with_ma", lambda: provider._baidu_kline_records(code)),
        ("sina_kline", lambda: provider._sina_kline_records(code)),
        ("eastmoney_kline", lambda: provider._eastmoney_kline_records(code, start_date, end_date)),
    ):
        try:
            records = _filter_recent_records(fetcher(), start_date, end_date)
            if records:
                return records, errors, source
            errors.append(f"{source}: no records")
        except Exception as exc:
            errors.append(f"{source}: {exc}")
    return [], errors, "unavailable"


def _fetch_quotes(
    provider: MainBoardScreenerProvider,
    codes: list[str],
    config: AStockMainBoardScreenerConfig,
    progress: ProgressCallback | None = None,
) -> tuple[dict[str, dict], list[str]]:
    quotes: dict[str, dict] = {}
    errors: list[str] = []
    batches = chunked(codes, config.batch_size)
    _emit_progress(
        progress,
        f"阶段1/4：开始获取实时行情，候选代码 {len(codes)} 个，批次 {len(batches)} 个，每批最多 {config.batch_size} 个。",
    )
    for batch_idx, batch in enumerate(batches):
        last_exc: Exception | None = None
        _emit_progress(
            progress,
            f"阶段1/4：请求行情批次 {batch_idx + 1}/{len(batches)}，代码范围 {batch[0]}-{batch[-1]}。",
        )
        for attempt in range(max(config.max_quote_retries, 1)):
            try:
                batch_quotes = provider.tencent_quote(batch)
                quotes.update(batch_quotes)
                _emit_progress(
                    progress,
                    f"阶段1/4：行情批次 {batch_idx + 1}/{len(batches)} 完成，本批有效 {len(batch_quotes)} 个，累计有效 {len(quotes)} 个。",
                )
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < max(config.max_quote_retries, 1):
                    _emit_progress(
                        progress,
                        f"阶段1/4：行情批次 {batch_idx + 1}/{len(batches)} 第 {attempt + 1} 次失败，准备重试：{exc}",
                    )
                    time.sleep(0.3 * (attempt + 1))
        if last_exc:
            errors.append(f"quote batch {batch_idx + 1}/{len(batches)} failed: {last_exc}")
            _emit_progress(progress, f"阶段1/4：行情批次 {batch_idx + 1}/{len(batches)} 失败，已跳过：{last_exc}")
        if config.quote_batch_interval > 0 and batch_idx + 1 < len(batches):
            time.sleep(config.quote_batch_interval)
    _emit_progress(progress, f"阶段1/4：实时行情获取完成，共拿到有效行情 {len(quotes)} 条。")
    return quotes, errors


def screen_main_board_candidates(
    provider: MainBoardScreenerProvider,
    config: AStockMainBoardScreenerConfig | None = None,
    now: datetime | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Run the full main-board screener and return structured results."""
    cfg = config or AStockMainBoardScreenerConfig()
    current = now or datetime.now(CN_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=CN_TZ)
    current = current.astimezone(CN_TZ)

    codes = list(cfg.codes) if cfg.codes else generate_main_board_codes()
    _emit_progress(
        progress,
        "阶段0/4：初始化完成，"
        f"一手金额 {cfg.min_lot_amount:.0f}-{cfg.max_lot_amount:.0f} 元，"
        f"涨幅 {cfg.min_change_pct:.1f}%-{cfg.max_change_pct:.1f}%，"
        f"换手 {cfg.min_turnover_pct:.1f}%-{cfg.max_turnover_pct if cfg.max_turnover_pct is not None else '不限'}%，"
        f"当前{'已到' if is_after_1430_cn(current) else '未到'} 14:30 策略观察窗口。",
    )
    quotes, quote_errors = _fetch_quotes(provider, codes, cfg, progress=progress)
    quote_rows = list(quotes.values())
    quote_pass_rows = [quote for quote in quote_rows if passes_quote_filters(quote, cfg)]
    _emit_progress(
        progress,
        f"阶段2/4：报价条件过滤完成，实时行情 {len(quote_rows)} 条，进入K线校验 {len(quote_pass_rows)} 条。",
    )

    records: list[dict[str, Any]] = []
    screened_records: list[dict[str, Any]] = []
    kline_errors: list[str] = []
    kline_sources: dict[str, int] = {}
    total_quote_pass = len(quote_pass_rows)
    if not quote_pass_rows:
        _emit_progress(progress, "阶段3/4：没有股票通过报价条件，跳过K线/均线校验。")
    for idx, quote in enumerate(quote_pass_rows, start=1):
        code = _normalize_code(quote.get("code"))
        name = quote.get("name", "")
        if idx == 1 or idx % 5 == 0 or idx == total_quote_pass:
            _emit_progress(progress, f"阶段3/4：校验K线/量能/均线 {idx}/{total_quote_pass}，当前 {code} {name}。")
        if idx > 1 and cfg.kline_request_interval > 0:
            time.sleep(cfg.kline_request_interval)
        kline_records, errors, source = fetch_recent_kline_records(provider, code, cfg, now=current)
        for error in errors:
            kline_errors.append(f"{code} {error}")
        kline_sources[source] = kline_sources.get(source, 0) + 1
        screened = screened_row_from_quote(quote, kline_records, cfg, kline_source=source, errors=errors)
        screened_records.append(screened)
        if screened["selected"]:
            records.append(screened)
            _emit_progress(
                progress,
                f"阶段3/4：命中候选 {code} {screened['name']}，P{screened['priority']} {screened['priority_label']}，"
                f"当前候选 {len(records)} 个。",
            )
        elif idx == 1 or idx % 10 == 0 or idx == total_quote_pass:
            _emit_progress(progress, f"阶段3/4：{code} 未选中，原因：{screened['reject_reason']}")

    records = sorted(
        records,
        key=lambda row: (
            row.get("priority", 99),
            -_safe_float(row.get("vol_ratio")),
            -_safe_float(row.get("turnover_pct")),
            row.get("code", ""),
        ),
    )
    limited = records[: max(cfg.limit, 0)]
    screened_records = sorted(
        screened_records,
        key=lambda row: (
            not bool(row.get("selected")),
            row.get("priority", 99),
            -_safe_float(row.get("vol_ratio")),
            -_safe_float(row.get("turnover_pct")),
            row.get("code", ""),
        ),
    )
    _emit_progress(progress, f"阶段4/4：排序完成，总候选 {len(records)} 个，返回前 {len(limited)} 个。")

    return {
        "records": limited,
        "screened_records": screened_records,
        "summary": {
            "as_of": current.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "after_1430_cn": is_after_1430_cn(current),
            "universe_size": len(codes),
            "quote_count": len(quote_rows),
            "quote_filter_count": len(quote_pass_rows),
            "candidate_count": len(records),
            "rejected_count": max(len(screened_records) - len(records), 0),
            "returned_count": len(limited),
            "kline_sources": kline_sources,
            "short_term_windows": {
                "volume_growth_days": cfg.volume_growth_days,
                "ma_slope_days": cfg.ma_slope_days,
                "kline_lookback_days": cfg.kline_lookback_days,
                "recent_position_days": cfg.recent_position_days,
                "kline_request_interval": cfg.kline_request_interval,
                "eastmoney_min_interval": cfg.eastmoney_min_interval,
            },
            "note": "Screening is intended for A-share sessions at/after 14:30 China time; volume/MA checks use recent trading-day windows for short-term trading.",
        },
        "config": asdict(cfg),
        "errors": quote_errors + kline_errors[:50],
    }
