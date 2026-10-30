#!/usr/bin/env python3
"""Factor-driven strategy system for small-capital, single-stock short-term trading.

The system is deliberately interpretable:

1. Build factors from either the existing overnight 5-minute experiment SQLite
   or a generic daily OHLCV CSV.
2. Clean obviously wrong rows into an audit file.
3. Convert factors into date-wise percentile scores.
4. Pick at most one full-position candidate per signal date.
5. Backtest using the provided realized target return and write a report.

It does not place orders and does not mutate the input data.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from experiments.ashare_overnight_5m.fetch_dataset import SOURCE_POLICY_VERSION
except Exception:
    SOURCE_POLICY_VERSION = "mootdx_sina_eastmoney_raw_v2"

from experiments.small_capital_quant_factor_system.factor_domains import (  # noqa: E402
    augment_factor_domains,
    available_factor_names,
    combine_factor_weights,
)


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "default_factor_config.json"
DEFAULT_INPUT = REPO_ROOT / "experiments" / "ashare_overnight_5m" / "data" / "ashare_overnight_5m.sqlite3"
DEFAULT_OUTPUT = BASE_DIR / "results"
AFTERNOON_TIMES = ("1430", "1435", "1440", "1445", "1450", "1455")
NEXT_MORNING_TIMES = ("0955", "1000", "1005")


@dataclass(frozen=True)
class StrategyConfig:
    strategy_name: str
    score_threshold: float
    min_cross_section_size: int
    min_amount: float
    transaction_cost_bps: float
    slippage_bps: float
    stop_loss_pct: float
    take_profit_pct: float
    max_trades_per_day: int
    allow_risk_names: bool
    factor_weights_overnight: dict[str, float]
    factor_weights_ohlcv: dict[str, float]
    factor_weights_external: dict[str, float] = field(default_factory=dict)
    factor_groups: dict[str, list[str]] = field(default_factory=dict)

    @property
    def total_cost_pct(self) -> float:
        return (self.transaction_cost_bps + self.slippage_bps) / 100.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="小资金全仓单股票短线量化因子策略系统。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--input-kind", choices=("overnight_sqlite", "overnight_csv", "ohlcv_csv"), default="overnight_sqlite")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--score-threshold", type=float, default=None)
    parser.add_argument("--min-amount", type=float, default=None)
    parser.add_argument("--include-risk-names", action="store_true")
    parser.add_argument("--weight-mode", choices=("adaptive_ic", "config"), default="adaptive_ic")
    parser.add_argument("--adaptive-lookback-days", type=int, default=12)
    parser.add_argument("--min-ic-history-days", type=int, default=5)
    parser.add_argument("--hold-days", type=int, default=1, help="ohlcv_csv模式下的持有天数；买入日后至少T+1卖出。")
    parser.add_argument("--initial-cash", type=float, default=100000.0)
    parser.add_argument("--top-candidates", type=int, default=20)
    parser.add_argument(
        "--aux-factor-csv",
        type=Path,
        action="append",
        default=[],
        help="可重复传入的外部因子CSV；支持date/signal_date、code、sector/industry/concept、available_at。",
    )
    return parser.parse_args()


def load_config(path: Path, args: argparse.Namespace) -> StrategyConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if args.score_threshold is not None:
        payload["score_threshold"] = args.score_threshold
    if args.min_amount is not None:
        payload["min_amount"] = args.min_amount
    if args.include_risk_names:
        payload["allow_risk_names"] = True
    return StrategyConfig(
        strategy_name=payload.get("strategy_name", "small_capital_single_stock_short_term"),
        score_threshold=float(payload.get("score_threshold", 0.62)),
        min_cross_section_size=int(payload.get("min_cross_section_size", 80)),
        min_amount=float(payload.get("min_amount", 20_000_000)),
        transaction_cost_bps=float(payload.get("transaction_cost_bps", 20)),
        slippage_bps=float(payload.get("slippage_bps", 10)),
        stop_loss_pct=float(payload.get("stop_loss_pct", 3.0)),
        take_profit_pct=float(payload.get("take_profit_pct", 6.0)),
        max_trades_per_day=int(payload.get("max_trades_per_day", 1)),
        allow_risk_names=bool(payload.get("allow_risk_names", False)),
        factor_weights_overnight={k: float(v) for k, v in payload.get("factor_weights_overnight", {}).items()},
        factor_weights_ohlcv={k: float(v) for k, v in payload.get("factor_weights_ohlcv", {}).items()},
        factor_weights_external={k: float(v) for k, v in payload.get("factor_weights_external", {}).items()},
        factor_groups={k: list(v) for k, v in payload.get("factor_groups", {}).items()},
    )


def load_overnight(path: Path, input_kind: str) -> pd.DataFrame:
    if input_kind == "overnight_sqlite":
        connection = sqlite3.connect(path)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(experiment_records)")}
            if not columns:
                raise ValueError(f"{path} 没有 experiment_records 表")
            if "source_policy" in columns:
                query = "SELECT * FROM experiment_records WHERE source_policy=?"
                return pd.read_sql_query(query, connection, params=(SOURCE_POLICY_VERSION,))
            return pd.read_sql_query("SELECT * FROM experiment_records", connection)
        finally:
            connection.close()
    return pd.read_csv(path, dtype={"code": "string"}, low_memory=False)


def load_ohlcv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"code": "string"}, low_memory=False)
    rename = {column: column.lower() for column in frame.columns}
    frame = frame.rename(columns=rename)
    if "datetime" in frame.columns and "date" not in frame.columns:
        frame = frame.rename(columns={"datetime": "date"})
    required = {"code", "date", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError("OHLCV CSV缺少字段：" + ",".join(sorted(missing)))
    return frame


def _append_reason(reasons: pd.Series, mask: pd.Series, reason: str) -> None:
    selected = mask.fillna(True)
    reasons.loc[selected] = reasons.loc[selected].map(lambda old: f"{old};{reason}" if old else reason)


def _series_slope_pct(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    values = frame[list(columns)].to_numpy(dtype=float)
    x = np.arange(values.shape[1], dtype=float)
    x -= x.mean()
    slope = np.sum(values * x, axis=1) / np.sum(x * x)
    base = np.nanmean(np.abs(values), axis=1)
    return pd.Series(np.divide(slope, base, out=np.full_like(slope, np.nan), where=base > 0) * 100, index=frame.index)


def _series_acceleration_pct(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    values = frame[list(columns)].to_numpy(dtype=float)
    diffs = np.diff(values, axis=1)
    acceleration = diffs[:, -2:].mean(axis=1) - diffs[:, :2].mean(axis=1)
    base = np.nanmean(np.abs(values), axis=1)
    return pd.Series(np.divide(acceleration, base, out=np.full_like(acceleration, np.nan), where=base > 0) * 100, index=frame.index)


def _series_volatility_pct(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    values = frame[list(columns)].to_numpy(dtype=float)
    changes = np.diff(values, axis=1) / values[:, :-1] * 100
    return pd.Series(np.nanstd(changes, axis=1), index=frame.index)


def prepare_overnight(raw: pd.DataFrame, config: StrategyConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = raw.copy()
    frame["code"] = frame["code"].astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(6)
    frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="coerce")
    frame["next_trade_date"] = pd.to_datetime(frame["next_trade_date"], errors="coerce")
    reasons = pd.Series("", index=frame.index, dtype="string")

    numeric_columns = [
        "quality_ok",
        "is_risk_name",
        "signal_close",
        "afternoon_1455_close",
        "afternoon_1500_close",
        *(f"next_{t}_close" for t in NEXT_MORNING_TIMES),
    ]
    for t in AFTERNOON_TIMES:
        numeric_columns.extend(
            [
                f"afternoon_{t}_close",
                f"afternoon_{t}_price_ma5",
                f"afternoon_{t}_price_ma10",
                f"afternoon_{t}_price_ma60",
                f"afternoon_{t}_volume_ma5",
                f"afternoon_{t}_volume_ma10",
            ]
        )
    missing = [column for column in numeric_columns if column not in frame.columns]
    if missing:
        raise ValueError("隔夜数据缺少字段：" + ",".join(missing))
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    _append_reason(reasons, frame["signal_date"].isna(), "invalid_signal_date")
    _append_reason(reasons, frame["quality_ok"].ne(1), "crawler_quality_not_ok")
    _append_reason(reasons, frame["afternoon_1455_close"].le(0) | frame["signal_close"].le(0), "nonpositive_entry_price")
    if "adjustment" in frame.columns:
        _append_reason(reasons, frame["adjustment"].fillna("").ne("none"), "non_raw_adjustment")
    if "source_policy" in frame.columns:
        _append_reason(reasons, frame["source_policy"].fillna("").ne(SOURCE_POLICY_VERSION), "stale_source_policy")
    if not config.allow_risk_names:
        _append_reason(reasons, frame["is_risk_name"].fillna(0).ne(0), "risk_name_excluded")

    price_cols = ["afternoon_1455_close", "afternoon_1500_close", *(f"next_{t}_close" for t in NEXT_MORNING_TIMES)]
    _append_reason(reasons, frame[price_cols].isna().any(axis=1), "missing_price")
    _append_reason(reasons, frame[price_cols].le(0).any(axis=1), "nonpositive_price")

    ma5_cols = [f"afternoon_{t}_price_ma5" for t in AFTERNOON_TIMES]
    ma10_cols = [f"afternoon_{t}_price_ma10" for t in AFTERNOON_TIMES]
    ma60_cols = [f"afternoon_{t}_price_ma60" for t in AFTERNOON_TIMES]
    vma5_cols = [f"afternoon_{t}_volume_ma5" for t in AFTERNOON_TIMES]
    vma10_cols = [f"afternoon_{t}_volume_ma10" for t in AFTERNOON_TIMES]
    factor_input_cols = ma5_cols + ma10_cols + ma60_cols + vma5_cols + vma10_cols
    _append_reason(reasons, frame[factor_input_cols].isna().any(axis=1), "missing_factor_input")
    _append_reason(reasons, frame[factor_input_cols].le(0).any(axis=1), "nonpositive_factor_input")

    rejected = frame.loc[reasons.ne("")].copy()
    rejected["reject_reason"] = reasons.loc[reasons.ne("")]
    data = frame.loc[reasons.eq("")].copy()

    data["entry_date"] = data["signal_date"]
    data["exit_date"] = data["next_trade_date"]
    data["entry_price"] = data["afternoon_1455_close"]
    data["exit_price"] = data[[f"next_{t}_close" for t in NEXT_MORNING_TIMES]].mean(axis=1)
    data["target_return_pct"] = (data["exit_price"] / data["entry_price"] - 1) * 100
    data["amount_proxy"] = np.nan

    data["ma5_gap_ma10_1430"] = (data[ma5_cols[0]] / data[ma10_cols[0]] - 1) * 100
    data["ma5_gap_ma10_1455"] = (data[ma5_cols[-1]] / data[ma10_cols[-1]] - 1) * 100
    data["ma5_gap_change"] = data["ma5_gap_ma10_1455"] - data["ma5_gap_ma10_1430"]
    data["ma5_slope"] = _series_slope_pct(data, ma5_cols)
    data["ma10_slope"] = _series_slope_pct(data, ma10_cols)
    data["ma5_acceleration"] = _series_acceleration_pct(data, ma5_cols)
    data["ma5_volatility"] = _series_volatility_pct(data, ma5_cols)
    data["price_gap_ma60_1455"] = (data["afternoon_1455_close"] / data[ma60_cols[-1]] - 1) * 100
    data["volume_gap_ma5_ma10_1430"] = (data[vma5_cols[0]] / data[vma10_cols[0]] - 1) * 100
    data["volume_gap_ma5_ma10_1455"] = (data[vma5_cols[-1]] / data[vma10_cols[-1]] - 1) * 100
    data["volume_gap_change"] = data["volume_gap_ma5_ma10_1455"] - data["volume_gap_ma5_ma10_1430"]
    data["volume_ma5_slope"] = _series_slope_pct(data, vma5_cols)
    data["late_price_return"] = (data["afternoon_1455_close"] / data["afternoon_1430_close"] - 1) * 100
    data["market_regime_return"] = data.groupby("signal_date")["target_return_pct"].transform("median")
    return data, rejected


def prepare_ohlcv(raw: pd.DataFrame, config: StrategyConfig, hold_days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = raw.copy()
    frame["code"] = frame["code"].astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(6)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume", "amount", "is_risk_name"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "amount" not in frame.columns:
        frame["amount"] = frame["close"] * frame["volume"]
    if "is_risk_name" not in frame.columns:
        frame["is_risk_name"] = 0
    if "name" not in frame.columns:
        frame["name"] = ""

    frame = frame.sort_values(["code", "date"]).reset_index(drop=True)
    group = frame.groupby("code", group_keys=False)
    frame["ret_1d"] = group["close"].pct_change()
    frame["momentum_3d"] = group["close"].pct_change(3) * 100
    frame["momentum_5d"] = group["close"].pct_change(5) * 100
    frame["reversal_1d"] = -frame["ret_1d"] * 100
    frame["ma5"] = group["close"].transform(lambda s: s.rolling(5, min_periods=5).mean())
    frame["ma10"] = group["close"].transform(lambda s: s.rolling(10, min_periods=10).mean())
    frame["ma20"] = group["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    frame["ma5_gap_ma10"] = (frame["ma5"] / frame["ma10"] - 1) * 100
    frame["ma10_gap_ma20"] = (frame["ma10"] / frame["ma20"] - 1) * 100
    frame["ma5_slope_3d"] = group["ma5"].pct_change(3) * 100 / 3
    volume_ma5 = group["volume"].transform(lambda s: s.rolling(5, min_periods=5).mean())
    volume_ma20 = group["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    frame["volume_ratio_5_20"] = volume_ma5 / volume_ma20
    amount_ma5 = group["amount"].transform(lambda s: s.rolling(5, min_periods=5).mean())
    frame["amount_ma5"] = amount_ma5
    frame["amount_ma5_score"] = np.log1p(amount_ma5)
    frame["volatility_5d"] = group["ret_1d"].transform(lambda s: s.rolling(5, min_periods=5).std()) * 100
    low20 = group["low"].transform(lambda s: s.rolling(20, min_periods=20).min())
    high20 = group["high"].transform(lambda s: s.rolling(20, min_periods=20).max())
    frame["range_position_20d"] = (frame["close"] - low20) / (high20 - low20)
    prev_high20 = high20.groupby(frame["code"]).shift(1)
    frame["breakout_20d"] = (frame["close"] / prev_high20 - 1) * 100
    frame["amihud_illiquidity"] = frame["ret_1d"].abs() / (frame["amount"] / 100_000_000)

    hold_days = max(1, int(hold_days))
    frame["entry_date"] = group["date"].shift(-1)
    frame["exit_date"] = group["date"].shift(-(hold_days + 1))
    frame["entry_price"] = group["open"].shift(-1)
    frame["exit_price"] = group["open"].shift(-(hold_days + 1))
    frame["target_return_pct"] = (frame["exit_price"] / frame["entry_price"] - 1) * 100
    frame["signal_date"] = frame["date"]
    frame["amount_proxy"] = frame["amount_ma5"]
    frame["market_regime_return"] = frame.groupby("date")["ret_1d"].transform("median") * 100

    reasons = pd.Series("", index=frame.index, dtype="string")
    _append_reason(reasons, frame["date"].isna(), "invalid_date")
    _append_reason(reasons, frame[["open", "high", "low", "close", "volume", "amount"]].isna().any(axis=1), "missing_ohlcv")
    _append_reason(reasons, frame[["open", "high", "low", "close", "volume"]].le(0).any(axis=1), "nonpositive_ohlcv")
    _append_reason(reasons, frame["entry_price"].isna() | frame["exit_price"].isna(), "missing_future_execution_price")
    if not config.allow_risk_names:
        _append_reason(reasons, frame["is_risk_name"].fillna(0).ne(0), "risk_name_excluded")
    rejected = frame.loc[reasons.ne("")].copy()
    rejected["reject_reason"] = reasons.loc[reasons.ne("")]
    return frame.loc[reasons.eq("")].copy(), rejected


def reject_modeling_outliers(data: pd.DataFrame, rejected: pd.DataFrame, factor_names: Sequence[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    finite_columns = ["target_return_pct", "entry_price", "exit_price", *factor_names]
    finite = np.isfinite(data[finite_columns].to_numpy(dtype=float)).all(axis=1)
    plausible_return = data["target_return_pct"].abs() <= 25
    keep = pd.Series(finite, index=data.index) & plausible_return
    extra = data.loc[~keep, ["code", "name", "signal_date", "entry_date", "exit_date", "target_return_pct"]].copy()
    extra["reject_reason"] = np.where(~pd.Series(finite, index=data.index).loc[~keep], "nonfinite_factor_or_target", "implausible_return")
    rejected = pd.concat([rejected, extra], ignore_index=True, sort=False)
    return data.loc[keep].copy(), rejected


def datewise_percentile_score(frame: pd.DataFrame, factor_names: Sequence[str], weights: dict[str, float]) -> pd.DataFrame:
    data = frame.copy()
    score = pd.Series(0.0, index=data.index)
    contribution_columns: list[str] = []
    for factor in factor_names:
        weight = weights.get(factor, 0.0)
        if weight == 0:
            continue
        percentile = data.groupby("signal_date")[factor].rank(pct=True, method="average")
        if weight < 0:
            percentile = 1 - percentile
        contribution = percentile * abs(weight)
        column = f"score_contrib_{factor}"
        data[column] = contribution
        contribution_columns.append(column)
        score += contribution
    normalizer = sum(abs(weights.get(factor, 0.0)) for factor in factor_names) or 1.0
    data["raw_score"] = score / normalizer
    data["cross_section_size"] = data.groupby("signal_date")["code"].transform("count")
    data["score_rank"] = data.groupby("signal_date")["raw_score"].rank(ascending=False, method="first")
    data["top_factor_1"] = data[contribution_columns].idxmax(axis=1).str.replace("score_contrib_", "", regex=False) if contribution_columns else ""
    sorted_contrib = np.argsort(-data[contribution_columns].to_numpy(dtype=float), axis=1) if contribution_columns else np.empty((len(data), 0))
    if contribution_columns:
        data["top_factor_2"] = [contribution_columns[indexes[1]].replace("score_contrib_", "") if len(indexes) > 1 else "" for indexes in sorted_contrib]
        data["top_factor_3"] = [contribution_columns[indexes[2]].replace("score_contrib_", "") if len(indexes) > 2 else "" for indexes in sorted_contrib]
    else:
        data["top_factor_2"] = ""
        data["top_factor_3"] = ""
    return data


def _rank_ic_for_frame(frame: pd.DataFrame, factor_names: Sequence[str]) -> dict[str, float]:
    values: dict[str, list[float]] = {factor: [] for factor in factor_names}
    for _, group in frame.groupby("signal_date"):
        if len(group) < 30 or group["target_return_pct"].nunique() < 3:
            continue
        target_rank = group["target_return_pct"].rank(method="average")
        for factor in factor_names:
            if group[factor].nunique() < 3:
                continue
            ic = group[factor].rank(method="average").corr(target_rank)
            if pd.notna(ic):
                values[factor].append(float(ic))
    return {factor: float(np.mean(items)) for factor, items in values.items() if items}


def adaptive_ic_percentile_score(
    frame: pd.DataFrame,
    factor_names: Sequence[str],
    base_weights: dict[str, float],
    *,
    lookback_days: int,
    min_history_days: int,
) -> pd.DataFrame:
    """Score each date using only prior-date factor IC.

    Config weights define importance caps; historical IC decides whether high
    or low factor values should be rewarded on that signal date.
    """
    rows: list[pd.DataFrame] = []
    data = frame.sort_values("signal_date").copy()
    dates = sorted(data["signal_date"].dropna().unique())
    for date_value in dates:
        current = data.loc[data["signal_date"].eq(date_value)].copy()
        history_dates = [value for value in dates if value < date_value][-max(int(lookback_days), 1):]
        history = data.loc[data["signal_date"].isin(history_dates)]
        if len(history_dates) >= min_history_days:
            ic = _rank_ic_for_frame(history, factor_names)
            weights: dict[str, float] = {}
            for factor in factor_names:
                importance = abs(base_weights.get(factor, 0.0))
                if importance == 0:
                    continue
                weights[factor] = importance * ic.get(factor, 0.0)
            if sum(abs(value) for value in weights.values()) <= 1e-12:
                weights = dict(base_weights)
            weight_source = "adaptive_ic"
        else:
            weights = dict(base_weights)
            weight_source = "config_warmup"
        scored = datewise_percentile_score(current, factor_names, weights)
        scored["weight_source"] = weight_source
        for factor in factor_names:
            scored[f"effective_weight_{factor}"] = weights.get(factor, 0.0)
        rows.append(scored)
    return pd.concat(rows, ignore_index=True) if rows else data.assign(raw_score=np.nan)


def select_single_stock_signals(scored: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    candidates = scored.loc[
        (scored["cross_section_size"] >= config.min_cross_section_size)
        & (scored["raw_score"] >= config.score_threshold)
    ].copy()
    if "amount_proxy" in candidates.columns and candidates["amount_proxy"].notna().any():
        candidates = candidates.loc[candidates["amount_proxy"].fillna(float("inf")) >= config.min_amount]
    if candidates.empty:
        return candidates.reset_index(drop=True)
    candidates["_selection_amount_proxy"] = candidates.get("amount_proxy", pd.Series(np.nan, index=candidates.index)).fillna(-np.inf)
    candidates["_selection_code"] = candidates["code"].astype("string").fillna("") if "code" in candidates else ""
    signals = candidates.sort_values(
        ["signal_date", "raw_score", "_selection_amount_proxy", "_selection_code"],
        ascending=[True, False, False, True],
    )
    signals = signals.groupby("signal_date", as_index=False, group_keys=False).head(config.max_trades_per_day)
    return signals.drop(columns=["_selection_amount_proxy", "_selection_code"], errors="ignore").reset_index(drop=True)


def backtest(signals: pd.DataFrame, config: StrategyConfig, initial_cash: float) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    trades = signals.sort_values("signal_date").copy()
    if trades.empty:
        return trades, pd.DataFrame(), {"trade_count": 0, "final_equity": initial_cash}
    trades["gross_return_pct"] = trades["target_return_pct"]
    trades["net_return_pct"] = trades["gross_return_pct"] - config.total_cost_pct
    equity = float(initial_cash)
    equity_rows: list[dict[str, Any]] = []
    equities = []
    for _, row in trades.iterrows():
        start_equity = equity
        equity *= 1 + row["net_return_pct"] / 100.0
        equities.append(equity)
        equity_rows.append(
            {
                "signal_date": row["signal_date"],
                "code": row["code"],
                "name": row.get("name", ""),
                "start_equity": start_equity,
                "end_equity": equity,
                "net_return_pct": row["net_return_pct"],
            }
        )
    equity_curve = pd.DataFrame(equity_rows)
    equity_series = pd.Series(equities)
    running_peak = equity_series.cummax()
    drawdown = equity_series / running_peak - 1
    summary = {
        "trade_count": int(len(trades)),
        "first_signal_date": str(trades["signal_date"].min().date()),
        "last_signal_date": str(trades["signal_date"].max().date()),
        "coverage_days": int(trades["signal_date"].nunique()),
        "win_rate": float((trades["net_return_pct"] > 0).mean()),
        "mean_net_return_pct": float(trades["net_return_pct"].mean()),
        "median_net_return_pct": float(trades["net_return_pct"].median()),
        "final_equity": float(equity),
        "total_return_pct": float((equity / initial_cash - 1) * 100),
        "max_drawdown_pct": float(drawdown.min() * 100),
        "best_trade_pct": float(trades["net_return_pct"].max()),
        "worst_trade_pct": float(trades["net_return_pct"].min()),
    }
    return trades, equity_curve, summary


def factor_ic(frame: pd.DataFrame, factor_names: Sequence[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for date_value, group in frame.groupby("signal_date"):
        if len(group) < 30:
            continue
        target_rank = group["target_return_pct"].rank(method="average")
        for factor in factor_names:
            ic = group[factor].rank(method="average").corr(target_rank)
            rows.append({"signal_date": date_value, "factor": factor, "rank_ic": ic})
    return pd.DataFrame(rows)


def factor_bins(frame: pd.DataFrame, factor_names: Sequence[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for factor in factor_names:
        values = frame[factor].replace([np.inf, -np.inf], np.nan).dropna()
        if values.nunique() < 10:
            continue
        try:
            bins = pd.qcut(frame[factor], q=5, labels=[f"Q{i}" for i in range(1, 6)], duplicates="drop")
        except ValueError:
            continue
        tmp = frame.assign(_bin=bins)
        for bin_name, group in tmp.groupby("_bin", observed=True):
            rows.append(
                {
                    "factor": factor,
                    "bin": str(bin_name),
                    "count": int(len(group)),
                    "mean_target_return_pct": float(group["target_return_pct"].mean()),
                    "median_target_return_pct": float(group["target_return_pct"].median()),
                    "win_rate": float((group["target_return_pct"] > 0).mean()),
                    "avg_score": float(group["raw_score"].mean()) if "raw_score" in group else math.nan,
                }
            )
    return pd.DataFrame(rows)


def latest_strategy(
    scored: pd.DataFrame,
    signals: pd.DataFrame,
    config: StrategyConfig,
    top_n: int,
    backtest_summary: dict[str, Any] | None = None,
) -> pd.DataFrame:
    latest_date = scored["signal_date"].max()
    latest = scored.loc[scored["signal_date"] == latest_date].sort_values("raw_score", ascending=False).head(top_n).copy()
    summary = backtest_summary or {}
    risk_gate_closed = (
        summary.get("trade_count", 0) > 0
        and (
            summary.get("mean_net_return_pct", 0.0) <= 0
            or summary.get("total_return_pct", 0.0) <= 0
            or summary.get("max_drawdown_pct", 0.0) <= -15
        )
    )
    if risk_gate_closed:
        latest["strategy_action"] = "风险总闸关闭：当前因子组合历史边际为负或回撤过深，默认空仓，仅观察"
    else:
        latest["strategy_action"] = np.where(
            latest["raw_score"] >= config.score_threshold,
            "候选：若流动性/涨跌停/盘口允许，可按全仓策略进入",
            "观察：分数不足，默认空仓",
        )
    latest["risk_plan"] = (
        f"全仓单票风险高；建议硬止损{config.stop_loss_pct:.1f}%，"
        f"止盈/移动止盈参考{config.take_profit_pct:.1f}%，若开盘流动性异常则跳过。"
    )
    if not signals.empty and latest_date in set(signals["signal_date"]):
        selected_codes = set(signals.loc[signals["signal_date"] == latest_date, "code"])
        latest["selected_by_system"] = latest["code"].isin(selected_codes).astype(int)
    else:
        latest["selected_by_system"] = 0
    latest["would_select_without_risk_gate"] = latest["selected_by_system"]
    if risk_gate_closed:
        latest["selected_by_system"] = 0
    return latest


def write_report(
    path: Path,
    *,
    input_kind: str,
    data: pd.DataFrame,
    rejected: pd.DataFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    backtest_summary: dict[str, Any],
    ic: pd.DataFrame,
    bins: pd.DataFrame,
    config: StrategyConfig,
    latest: pd.DataFrame,
) -> None:
    lines = [
        "# 小资金单股票短线量化因子策略报告",
        "",
        "## 口径",
        "",
        f"- 输入模式：`{input_kind}`。",
        "- 每个信号日最多选择一只股票；分数不足时空仓。",
        "- 因子按当日横截面分位数标准化，正权重偏向高分位，负权重偏向低分位。",
        f"- 成本：交易成本 {config.transaction_cost_bps:.1f}bp + 滑点 {config.slippage_bps:.1f}bp。",
        f"- 默认止损/止盈提示：{config.stop_loss_pct:.1f}% / {config.take_profit_pct:.1f}%。",
        "",
        "## 策略状态",
        "",
        (
            "- 风险总闸：关闭。当前因子组合历史边际为负或回撤过深，最新候选只作观察，不建议进入。"
            if backtest_summary.get("trade_count", 0) > 0
            and (
                backtest_summary.get("mean_net_return_pct", 0.0) <= 0
                or backtest_summary.get("total_return_pct", 0.0) <= 0
                or backtest_summary.get("max_drawdown_pct", 0.0) <= -15
            )
            else "- 风险总闸：打开。仍需人工检查流动性、涨跌停和盘口。"
        ),
        "",
        "## 数据清洗",
        "",
        f"- 建模行数：{len(data):,}",
        f"- 拒绝行数：{len(rejected):,}",
        f"- 信号日期：{data['signal_date'].min().date()} 至 {data['signal_date'].max().date()}，共 {data['signal_date'].nunique()} 天。",
        "",
        "## 回测摘要",
        "",
    ]
    if backtest_summary.get("trade_count", 0) == 0:
        lines.append("- 没有生成交易；请检查分数阈值或输入数据。")
    else:
        lines.extend(
            [
                f"- 交易次数：{backtest_summary['trade_count']}",
                f"- 胜率：{backtest_summary['win_rate'] * 100:.2f}%",
                f"- 单笔平均净收益：{backtest_summary['mean_net_return_pct']:.3f}%",
                f"- 总收益：{backtest_summary['total_return_pct']:.2f}%",
                f"- 最大回撤：{backtest_summary['max_drawdown_pct']:.2f}%",
                f"- 最好/最差单笔：{backtest_summary['best_trade_pct']:.2f}% / {backtest_summary['worst_trade_pct']:.2f}%",
            ]
        )
    lines.extend(["", "## 最新信号", ""])
    if latest.empty:
        lines.append("- 无可用最新候选。")
    else:
        for rank, (_, row) in enumerate(latest.head(5).iterrows(), start=1):
            lines.append(
                f"{rank}. `{row['code']}` {row.get('name', '')}：score={row['raw_score']:.3f}，"
                f"系统选择={int(row['selected_by_system'])}，主因子={row.get('top_factor_1', '')}/"
                f"{row.get('top_factor_2', '')}/{row.get('top_factor_3', '')}。"
            )
    lines.extend(["", "## 因子IC概览", ""])
    if not ic.empty:
        ic_summary = ic.groupby("factor")["rank_ic"].agg(["mean", "median", "count"]).sort_values("mean", ascending=False)
        for factor, row in ic_summary.head(10).iterrows():
            lines.append(f"- {factor}: mean IC={row['mean']:.4f}, median={row['median']:.4f}, days={int(row['count'])}")
    lines.extend(
        [
            "",
            "## 风险提示",
            "",
            "- 小资金全仓单票的主要风险不是选股模型，而是隔夜跳空、流动性、涨跌停无法退出和样本外失效。",
            "- 本系统输出的是可审计的因子研究结果，不是实盘保证。",
            "- 若要实盘，应先用未来未见数据固定参数跑至少数月，并加入真实盘口、委托失败和滑点模拟。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    config = load_config(args.config, args)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    if args.input_kind.startswith("overnight"):
        raw = load_overnight(args.input, args.input_kind)
        data, rejected = prepare_overnight(raw, config)
    else:
        raw = load_ohlcv(args.input)
        data, rejected = prepare_ohlcv(raw, config, args.hold_days)
    augmentation = augment_factor_domains(data, input_kind=args.input_kind, aux_factor_csvs=args.aux_factor_csv)
    data = augmentation.frame
    weights = combine_factor_weights(config, args.input_kind)
    factor_names = available_factor_names(data, weights)
    if not factor_names:
        raise ValueError("没有可用因子，请检查输入字段、辅助因子CSV和配置。")
    data, rejected = reject_modeling_outliers(data, rejected, factor_names)
    if args.weight_mode == "adaptive_ic":
        scored = adaptive_ic_percentile_score(
            data,
            factor_names,
            weights,
            lookback_days=args.adaptive_lookback_days,
            min_history_days=args.min_ic_history_days,
        )
    else:
        scored = datewise_percentile_score(data, factor_names, weights)
        scored["weight_source"] = "config"
    signals = select_single_stock_signals(scored, config)
    trades, equity_curve, summary = backtest(signals, config, args.initial_cash)
    ic = factor_ic(scored, factor_names)
    bins = factor_bins(scored, factor_names)
    latest = latest_strategy(scored, signals, config, args.top_candidates, summary)

    scored.to_csv(args.output_dir / "scored_universe.csv.gz", index=False, compression="gzip", encoding="utf-8-sig")
    rejected.to_csv(args.output_dir / "rejected_rows.csv", index=False, encoding="utf-8-sig")
    signals.to_csv(args.output_dir / "signals.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(args.output_dir / "trades.csv", index=False, encoding="utf-8-sig")
    equity_curve.to_csv(args.output_dir / "equity_curve.csv", index=False, encoding="utf-8-sig")
    ic.to_csv(args.output_dir / "factor_ic.csv", index=False, encoding="utf-8-sig")
    bins.to_csv(args.output_dir / "factor_bins.csv", index=False, encoding="utf-8-sig")
    latest.to_csv(args.output_dir / "latest_strategy.csv", index=False, encoding="utf-8-sig")
    augmentation.metadata.to_csv(args.output_dir / "factor_domain_metadata.csv", index=False, encoding="utf-8-sig")
    (args.output_dir / "backtest_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (args.output_dir / "run_config.json").write_text(
        json.dumps(
            {
                "input": str(args.input),
                "input_kind": args.input_kind,
                "config": str(args.config),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "strategy": config.__dict__,
                "weight_mode": args.weight_mode,
                "adaptive_lookback_days": args.adaptive_lookback_days,
                "min_ic_history_days": args.min_ic_history_days,
                "aux_factor_csv": [str(path) for path in args.aux_factor_csv],
                "factor_names": factor_names,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    write_report(
        args.output_dir / "report.md",
        input_kind=args.input_kind,
        data=data,
        rejected=rejected,
        signals=signals,
        trades=trades,
        backtest_summary=summary,
        ic=ic,
        bins=bins,
        config=config,
        latest=latest,
    )
    print(f"建模样本={len(data):,}，信号={len(signals):,}，交易={len(trades):,}")
    print(f"报告={args.output_dir / 'report.md'}")
    if not latest.empty:
        chosen = latest.loc[latest["selected_by_system"].eq(1)]
        if not chosen.empty:
            row = chosen.iloc[0]
            print(f"最新候选={row['code']} {row.get('name', '')} score={row['raw_score']:.3f} action={row.get('strategy_action', '')}")


if __name__ == "__main__":
    main()

