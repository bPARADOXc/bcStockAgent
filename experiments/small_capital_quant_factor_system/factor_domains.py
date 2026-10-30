#!/usr/bin/env python3
"""Multi-domain factor extensions for the short-term A-share strategy.

The base strategy started from tail-session technical factors.  This module
adds two things:

1. Built-in factor domains that can be derived from the data we already have.
2. A generic, leakage-aware CSV join path for sentiment, sector/concept,
   limit-up ecology, order-flow, event and capital-flow factors.

The functions are intentionally conservative.  If an auxiliary CSV provides an
``available_at`` timestamp, rows later than the strategy cutoff are ignored.
If no timestamp is provided, the file is treated as already available by the
cutoff and the caller is responsible for using the correct data source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd


OVERNIGHT_CUTOFF_TIME = "14:55:00"
OHLCV_CUTOFF_TIME = "23:59:59"

KEY_COLUMNS = {
    "date",
    "signal_date",
    "trade_date",
    "datetime",
    "available_at",
    "code",
    "symbol",
    "ts_code",
    "name",
    "sector",
    "industry",
    "concept",
    "factor_domain",
    "source",
}

LEAKY_FACTOR_COLUMNS = {
    "target_return_pct",
    "gross_return_pct",
    "net_return_pct",
    "exit_price",
    "exit_date",
    "next_trade_date",
    # Existing diagnostic column derived from future returns.  It is kept in
    # the dataset for reporting compatibility but must never be used as a
    # predictive factor.
    "market_regime_return",
}


@dataclass(frozen=True)
class FactorAugmentationResult:
    frame: pd.DataFrame
    metadata: pd.DataFrame


def sanitize_identifier(value: str) -> str:
    text = re.sub(r"[^0-9a-zA-Z_]+", "_", str(value).strip())
    text = re.sub(r"_+", "_", text).strip("_").lower()
    if not text:
        text = "factor"
    if text[0].isdigit():
        text = "f_" + text
    return text


def _as_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return np.divide(
        numerator.to_numpy(dtype=float),
        denominator.to_numpy(dtype=float),
        out=np.full(len(numerator), np.nan, dtype=float),
        where=denominator.to_numpy(dtype=float) != 0,
    )


def _pct_std(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    available = [column for column in columns if column in frame.columns]
    if len(available) < 2:
        return pd.Series(np.nan, index=frame.index)
    values = frame[available].to_numpy(dtype=float)
    changes = np.diff(values, axis=1) / values[:, :-1] * 100
    return pd.Series(np.nanstd(changes, axis=1), index=frame.index)


def _add_cross_sectional_regime_factors(data: pd.DataFrame) -> list[dict[str, str]]:
    metadata: list[dict[str, str]] = []
    if "signal_date" not in data.columns:
        return metadata
    group = data.groupby("signal_date", group_keys=False)

    if "late_price_return" in data.columns:
        data["market_late_return_median"] = group["late_price_return"].transform("median")
        data["market_late_positive_ratio"] = group["late_price_return"].transform(lambda s: float((s > 0).mean()))
        data["market_breadth_score"] = data["market_late_positive_ratio"] * 2 - 1
        data["stock_vs_market_late_return"] = data["late_price_return"] - data["market_late_return_median"]
        data["regime_adjusted_late_return"] = data["late_price_return"] * data["market_breadth_score"]
        metadata.extend(
            [
                _meta("market_regime", "market_late_return_median", "全市场尾盘涨跌中位数；用于报告/交互。"),
                _meta("market_regime", "market_late_positive_ratio", "尾盘上涨股票占比；市场情绪宽度。"),
                _meta("market_regime", "stock_vs_market_late_return", "个股尾盘涨跌相对市场中位数。"),
                _meta("market_regime", "regime_adjusted_late_return", "市场强弱调节后的个股尾盘强度。"),
            ]
        )

    if "ma5_slope" in data.columns:
        if "market_breadth_score" not in data.columns:
            data["market_breadth_score"] = 0.0
        data["market_ma5_slope_median"] = group["ma5_slope"].transform("median")
        data["ma5_slope_vs_market"] = data["ma5_slope"] - data["market_ma5_slope_median"]
        data["regime_adjusted_ma5_slope"] = data["ma5_slope"] * data["market_breadth_score"]
        metadata.extend(
            [
                _meta("market_regime", "ma5_slope_vs_market", "个股MA5尾盘斜率相对市场中位数。"),
                _meta("market_regime", "regime_adjusted_ma5_slope", "市场强弱调节后的MA5尾盘斜率。"),
            ]
        )

    if "volume_gap_change" in data.columns:
        if "market_breadth_score" not in data.columns:
            data["market_breadth_score"] = 0.0
        data["market_volume_gap_change_median"] = group["volume_gap_change"].transform("median")
        data["volume_gap_change_vs_market"] = data["volume_gap_change"] - data["market_volume_gap_change_median"]
        data["regime_adjusted_volume_flow"] = data["volume_gap_change"] * data["market_breadth_score"]
        metadata.extend(
            [
                _meta("market_regime", "volume_gap_change_vs_market", "个股尾盘量能扩张相对市场中位数。"),
                _meta("market_regime", "regime_adjusted_volume_flow", "市场强弱调节后的尾盘量能扩张。"),
            ]
        )

    return metadata


def _add_overnight_builtin_factors(data: pd.DataFrame) -> list[dict[str, str]]:
    metadata = _add_cross_sectional_regime_factors(data)
    close_cols = [f"afternoon_{time}_close" for time in ("1430", "1435", "1440", "1445", "1450", "1455")]
    volume_ma5 = "afternoon_1455_volume_ma5"
    volume_ma10 = "afternoon_1455_volume_ma10"
    _as_numeric(data, [*close_cols, volume_ma5, volume_ma10, "previous_close", "prev_close"])

    data["tail_close_volatility"] = _pct_std(data, close_cols)
    available_close = [column for column in close_cols if column in data.columns]
    if available_close:
        data["tail_intraday_drawdown_proxy"] = (data[available_close[-1]] / data[available_close].max(axis=1) - 1) * 100
    if volume_ma5 in data.columns:
        data["liquidity_tail_volume_ma5_log"] = np.log1p(data[volume_ma5].clip(lower=0))
    if volume_ma10 in data.columns:
        data["liquidity_tail_volume_ma10_log"] = np.log1p(data[volume_ma10].clip(lower=0))
    if volume_ma5 in data.columns and volume_ma10 in data.columns:
        data["liquidity_tail_volume_spike"] = _safe_divide(data[volume_ma5], data[volume_ma10])

    metadata.extend(
        [
            _meta("liquidity_microstructure", "tail_close_volatility", "14:30-14:55尾盘价格波动率代理。"),
            _meta("liquidity_microstructure", "tail_intraday_drawdown_proxy", "尾盘相对短窗口最高价回撤代理。"),
            _meta("liquidity_microstructure", "liquidity_tail_volume_ma5_log", "14:55成交量MA5的对数流动性代理。"),
            _meta("liquidity_microstructure", "liquidity_tail_volume_spike", "尾盘短量相对长量的放大代理。"),
        ]
    )
    metadata.extend(_add_limit_price_proxy(data, close_column="afternoon_1455_close", return_column=None))
    return metadata


def _add_ohlcv_builtin_factors(data: pd.DataFrame) -> list[dict[str, str]]:
    metadata = _add_cross_sectional_regime_factors(data)
    if "date" in data.columns and "signal_date" not in data.columns:
        data["signal_date"] = data["date"]
    if {"code", "close"}.issubset(data.columns):
        data = data.sort_values(["code", "signal_date"]).copy()
        data["prev_close"] = data.groupby("code")["close"].shift(1)
    if "ret_1d" in data.columns:
        group = data.groupby("signal_date", group_keys=False)
        data["daily_return_pct"] = data["ret_1d"] * 100
        data["market_daily_return_median"] = group["daily_return_pct"].transform("median")
        data["market_daily_positive_ratio"] = group["daily_return_pct"].transform(lambda s: float((s > 0).mean()))
        data["daily_return_vs_market"] = data["daily_return_pct"] - data["market_daily_return_median"]
        metadata.extend(
            [
                _meta("market_regime", "market_daily_positive_ratio", "日线模式下全市场上涨占比。"),
                _meta("market_regime", "daily_return_vs_market", "个股当日收益相对市场中位数。"),
            ]
        )
    if {"momentum_3d", "market_daily_positive_ratio"}.issubset(data.columns):
        data["daily_market_breadth_score"] = data["market_daily_positive_ratio"] * 2 - 1
        data["regime_adjusted_momentum_3d"] = data["momentum_3d"] * data["daily_market_breadth_score"]
        metadata.append(_meta("market_regime", "regime_adjusted_momentum_3d", "市场强弱调节后的3日动量。"))
    if "amount_ma5_score" in data.columns:
        data["amount_score_vs_market"] = data["amount_ma5_score"] - data.groupby("signal_date")["amount_ma5_score"].transform("median")
        metadata.append(_meta("liquidity_microstructure", "amount_score_vs_market", "成交额活跃度相对市场中位数。"))
    if "volatility_5d" in data.columns:
        data["volatility_5d_vs_market"] = data["volatility_5d"] - data.groupby("signal_date")["volatility_5d"].transform("median")
        metadata.append(_meta("liquidity_microstructure", "volatility_5d_vs_market", "5日波动率相对市场中位数。"))
    metadata.extend(_add_limit_price_proxy(data, close_column="close", return_column="daily_return_pct"))
    return metadata


def _add_limit_price_proxy(data: pd.DataFrame, *, close_column: str, return_column: str | None) -> list[dict[str, str]]:
    metadata: list[dict[str, str]] = []
    if return_column and return_column in data.columns:
        daily_return_pct = data[return_column]
    elif close_column in data.columns and "prev_close" in data.columns:
        daily_return_pct = (data[close_column] / data["prev_close"] - 1) * 100
    elif close_column in data.columns and "previous_close" in data.columns:
        daily_return_pct = (data[close_column] / data["previous_close"] - 1) * 100
    else:
        return metadata

    data["limit_up_distance_pct"] = 10.0 - daily_return_pct
    data["limit_down_distance_pct"] = daily_return_pct + 10.0
    data["near_limit_up_proxy"] = (daily_return_pct >= 8.0).astype(float)
    data["near_limit_down_proxy"] = (daily_return_pct <= -8.0).astype(float)
    metadata.extend(
        [
            _meta("limit_up_ecology", "limit_up_distance_pct", "距10%涨停空间的近似值；主板非ST口径。"),
            _meta("limit_up_ecology", "near_limit_up_proxy", "接近涨停的二元代理。"),
            _meta("limit_up_ecology", "near_limit_down_proxy", "接近跌停的二元代理。"),
        ]
    )
    return metadata


def _meta(domain: str, factor: str, description: str, source: str = "builtin") -> dict[str, str]:
    return {"domain": domain, "factor": factor, "source": source, "description": description}


def cutoff_for_input_kind(input_kind: str) -> str:
    return OVERNIGHT_CUTOFF_TIME if input_kind.startswith("overnight") else OHLCV_CUTOFF_TIME


def augment_factor_domains(
    frame: pd.DataFrame,
    *,
    input_kind: str,
    aux_factor_csvs: Sequence[Path] | None = None,
    cutoff_time: str | None = None,
) -> FactorAugmentationResult:
    data = frame.copy()
    data["signal_date"] = pd.to_datetime(data["signal_date"], errors="coerce")
    metadata: list[dict[str, str]] = []
    if input_kind.startswith("overnight"):
        metadata.extend(_add_overnight_builtin_factors(data))
    else:
        metadata.extend(_add_ohlcv_builtin_factors(data))

    for path in aux_factor_csvs or []:
        data, aux_meta = merge_auxiliary_factor_csv(
            data,
            Path(path),
            cutoff_time=cutoff_time or cutoff_for_input_kind(input_kind),
        )
        metadata.extend(aux_meta)

    meta_frame = pd.DataFrame(metadata).drop_duplicates(subset=["domain", "factor", "source"])
    return FactorAugmentationResult(data, meta_frame)


def merge_auxiliary_factor_csv(
    frame: pd.DataFrame,
    path: Path,
    *,
    cutoff_time: str,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"辅助因子CSV不存在：{path}")
    raw = pd.read_csv(path, dtype={"code": "string", "symbol": "string", "ts_code": "string"}, low_memory=False)
    if raw.empty:
        return frame.copy(), []
    raw = raw.rename(columns={column: sanitize_identifier(column) for column in raw.columns})
    namespace = sanitize_identifier(path.stem)

    if "signal_date" not in raw.columns:
        for candidate in ("date", "trade_date", "datetime"):
            if candidate in raw.columns:
                raw["signal_date"] = raw[candidate]
                break
    if "signal_date" in raw.columns:
        raw["signal_date"] = pd.to_datetime(raw["signal_date"], errors="coerce").dt.normalize()

    if "code" not in raw.columns:
        for candidate in ("symbol", "ts_code"):
            if candidate in raw.columns:
                raw["code"] = raw[candidate]
                break
    if "code" in raw.columns:
        raw["code"] = raw["code"].astype("string").str.extract(r"(\d{6})", expand=False).str.zfill(6)

    if "available_at" in raw.columns and "signal_date" in raw.columns:
        raw["available_at"] = pd.to_datetime(raw["available_at"], errors="coerce")
        cutoff_delta = pd.to_timedelta(cutoff_time)
        cutoff = raw["signal_date"] + cutoff_delta
        raw = raw.loc[raw["available_at"].isna() | (raw["available_at"] <= cutoff)].copy()

    join_keys: list[str] = []
    target = frame.copy()
    target["signal_date"] = pd.to_datetime(target["signal_date"], errors="coerce").dt.normalize()
    if "signal_date" in raw.columns:
        join_keys.append("signal_date")
    for key in ("code", "sector", "industry", "concept"):
        if key in raw.columns and key in target.columns:
            join_keys.append(key)
            if key == "code":
                target["code"] = target["code"].astype("string").str.extract(r"(\d{6})", expand=False).str.zfill(6)
    if not join_keys:
        raise ValueError(f"{path} 至少需要 date/signal_date 或 code/sector/industry/concept 中的可连接字段")

    numeric_columns: list[str] = []
    for column in raw.columns:
        if column in KEY_COLUMNS or column in join_keys:
            continue
        numeric = pd.to_numeric(raw[column], errors="coerce")
        if numeric.notna().any():
            raw[column] = numeric
            numeric_columns.append(column)
    if not numeric_columns:
        return target, []

    rename_map = {
        column: column if column.startswith(namespace + "_") else f"{namespace}_{column}"
        for column in numeric_columns
    }
    keep_columns = [*join_keys, *numeric_columns]
    if "available_at" in raw.columns:
        raw = raw.sort_values([*join_keys, "available_at"])
    aux = raw[keep_columns].dropna(subset=join_keys).drop_duplicates(subset=join_keys, keep="last").rename(columns=rename_map)
    merged = target.merge(aux, on=join_keys, how="left")
    for factor in rename_map.values():
        if factor in merged.columns:
            merged[factor] = pd.to_numeric(merged[factor], errors="coerce").fillna(0.0)
    metadata = [
        _meta("external_auxiliary", factor, f"来自辅助因子文件 {path.name}，按 {','.join(join_keys)} 合并。", source=namespace)
        for factor in rename_map.values()
    ]
    return merged, metadata


def available_factor_names(frame: pd.DataFrame, weights: dict[str, float]) -> list[str]:
    leaky = sorted(column for column in weights if column in LEAKY_FACTOR_COLUMNS)
    if leaky:
        raise ValueError("配置中包含未来信息/泄漏字段，已拒绝：" + ",".join(leaky))
    return [factor for factor in weights if factor in frame.columns]


def combine_factor_weights(config: object, input_kind: str) -> dict[str, float]:
    if input_kind.startswith("overnight"):
        weights = dict(getattr(config, "factor_weights_overnight", {}))
    else:
        weights = dict(getattr(config, "factor_weights_ohlcv", {}))
    weights.update(getattr(config, "factor_weights_external", {}) or {})
    return {key: float(value) for key, value in weights.items()}
