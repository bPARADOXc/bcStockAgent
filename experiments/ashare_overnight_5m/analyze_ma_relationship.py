#!/usr/bin/env python3
"""Explore late-session MA/volume patterns versus next-morning returns.

This is an interpretable, date-split experiment. It never mutates the crawler
database: invalid rows are filtered into an auditable rejected-row file.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.ashare_overnight_5m.fetch_dataset import SOURCE_POLICY_VERSION


FEATURE_TIMES = ("1430", "1435", "1440", "1445", "1450", "1455")
TARGET_TIMES = ("0955", "1000", "1005")
PRICE_MA_WINDOWS = (5, 10, 60)
VOLUME_MA_WINDOWS = (5, 10)


FEATURE_LABELS = {
    "late_price_return_pct": "14:30到14:55价格涨跌幅",
    "ma5_gap_ma10_1430_pct": "14:30 MA5高于MA10幅度",
    "ma5_gap_ma10_1455_pct": "14:55 MA5高于MA10幅度",
    "ma5_gap_change_pp": "MA5-MA10差值扩张",
    "ma5_slope_pct_per_bar": "MA5尾盘斜率",
    "ma10_slope_pct_per_bar": "MA10尾盘斜率",
    "ma60_slope_pct_per_bar": "MA60尾盘斜率",
    "ma5_slope_minus_ma10_slope": "MA5斜率减MA10斜率",
    "ma5_acceleration_pct": "MA5尾盘加速度",
    "ma10_acceleration_pct": "MA10尾盘加速度",
    "ma5_up_fraction": "MA5逐段上涨比例",
    "ma10_up_fraction": "MA10逐段上涨比例",
    "ma5_volatility_pct": "MA5尾盘波动",
    "ma10_volatility_pct": "MA10尾盘波动",
    "price_gap_ma5_1455_pct": "14:55价格高于MA5幅度",
    "price_gap_ma10_1455_pct": "14:55价格高于MA10幅度",
    "price_gap_ma60_1455_pct": "14:55价格高于MA60幅度",
    "volume_ma5_gap_ma10_1430_pct": "14:30量MA5高于量MA10幅度",
    "volume_ma5_gap_ma10_1455_pct": "14:55量MA5高于量MA10幅度",
    "volume_gap_change_pp": "量MA5-MA10差值扩张",
    "volume_ma5_slope_pct_per_bar": "量MA5尾盘斜率",
    "volume_ma10_slope_pct_per_bar": "量MA10尾盘斜率",
    "volume_ma5_up_fraction": "量MA5逐段上涨比例",
    "ma5_above_ma10_1455": "14:55 MA5在MA10之上",
    "ma5_cross_up": "14:30后MA5上穿MA10",
    "ma5_cross_down": "14:30后MA5下穿MA10",
    "bullish_alignment_1455": "14:55价格>MA5>MA10>MA60",
    "price_volume_same_direction": "尾盘价量斜率同向",
}


BINARY_FEATURES = {
    "ma5_above_ma10_1455",
    "ma5_cross_up",
    "ma5_cross_down",
    "bullish_alignment_1455",
    "price_volume_same_direction",
}


@dataclass(frozen=True)
class Condition:
    feature: str
    operator: str
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        return {"feature": self.feature, "operator": self.operator, "threshold": self.threshold}


def parse_args() -> argparse.Namespace:
    base = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="研究尾盘MA5/MA10/成交量均线与次日上午收益的关系。")
    parser.add_argument(
        "--input",
        type=Path,
        default=base / "data" / "ashare_overnight_5m.sqlite3",
        help="爬虫生成的 SQLite 或 CSV 文件。",
    )
    parser.add_argument("--output-dir", type=Path, default=base / "analysis_results")
    parser.add_argument("--validation-days", type=int, default=6, help="最后N个交易日作为时间外验证集。")
    parser.add_argument("--min-rule-samples", type=int, default=300)
    parser.add_argument("--min-rule-days", type=int, default=10)
    parser.add_argument("--max-rule-size", type=int, choices=(1, 2), default=2)
    parser.add_argument("--top-rules", type=int, default=30)
    parser.add_argument("--big-rise-pct", type=float, default=1.0)
    parser.add_argument("--max-absolute-return-pct", type=float, default=22.0)
    parser.add_argument("--round-trip-cost-bps", type=float, default=20.0)
    parser.add_argument("--include-risk-names", action="store_true", help="纳入ST/*ST/退市整理名称。")
    return parser.parse_args()


def load_records(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在：{path}")
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        connection = sqlite3.connect(path)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(experiment_records)")}
            if not columns:
                raise ValueError("SQLite中不存在 experiment_records 表")
            if "source_policy" in columns:
                query = "SELECT * FROM experiment_records WHERE source_policy=?"
                frame = pd.read_sql_query(query, connection, params=(SOURCE_POLICY_VERSION,))
            else:
                frame = pd.read_sql_query("SELECT * FROM experiment_records", connection)
        finally:
            connection.close()
        return frame
    return pd.read_csv(path, dtype={"code": "string"}, low_memory=False)


def _append_reason(reasons: pd.Series, mask: pd.Series, reason: str) -> None:
    selected = mask.fillna(True)
    reasons.loc[selected] = reasons.loc[selected].map(lambda old: f"{old};{reason}" if old else reason)


def clean_records(
    raw: pd.DataFrame,
    *,
    include_risk_names: bool,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    frame = raw.copy()
    if "code" not in frame:
        raise ValueError("输入缺少 code 字段")
    frame["code"] = frame["code"].astype("string").str.replace(r"\.0$", "", regex=True).str.zfill(6)
    reasons = pd.Series("", index=frame.index, dtype="string")

    required = [
        "signal_date",
        "next_trade_date",
        "signal_close",
        "quality_ok",
        "is_risk_name",
        "afternoon_1455_close",
        "afternoon_1500_close",
        *(f"next_{bar_time}_close" for bar_time in TARGET_TIMES),
    ]
    for bar_time in FEATURE_TIMES:
        required.append(f"afternoon_{bar_time}_close")
        required.extend(f"afternoon_{bar_time}_price_ma{window}" for window in PRICE_MA_WINDOWS)
        required.extend(f"afternoon_{bar_time}_volume_ma{window}" for window in VOLUME_MA_WINDOWS)
    missing_columns = [column for column in required if column not in frame.columns]
    if missing_columns:
        raise ValueError("输入缺少实验字段：" + ", ".join(missing_columns))

    numeric_columns = [column for column in required if column not in {"signal_date", "next_trade_date"}]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="coerce")
    frame["next_trade_date"] = pd.to_datetime(frame["next_trade_date"], errors="coerce")

    _append_reason(reasons, frame["code"].str.fullmatch(r"\d{6}").ne(True), "invalid_code")
    _append_reason(reasons, frame["signal_date"].isna() | frame["next_trade_date"].isna(), "invalid_date")
    _append_reason(reasons, frame["next_trade_date"] <= frame["signal_date"], "next_date_not_after_signal")
    _append_reason(reasons, frame["quality_ok"].ne(1), "crawler_quality_not_ok")
    if "adjustment" in frame:
        _append_reason(reasons, frame["adjustment"].fillna("").ne("none"), "non_raw_adjustment")
    if "source_policy" in frame:
        _append_reason(
            reasons,
            frame["source_policy"].fillna("").ne(SOURCE_POLICY_VERSION),
            "stale_source_policy",
        )
    if not include_risk_names:
        _append_reason(reasons, frame["is_risk_name"].fillna(0).ne(0), "risk_name_excluded")

    price_columns = ["signal_close", "afternoon_1455_close", "afternoon_1500_close"]
    price_columns.extend(f"next_{bar_time}_close" for bar_time in TARGET_TIMES)
    price_columns.extend(f"afternoon_{bar_time}_close" for bar_time in FEATURE_TIMES)
    ma_columns: list[str] = []
    volume_columns: list[str] = []
    for bar_time in FEATURE_TIMES:
        ma_columns.extend(f"afternoon_{bar_time}_price_ma{window}" for window in PRICE_MA_WINDOWS)
        volume_columns.extend(f"afternoon_{bar_time}_volume_ma{window}" for window in VOLUME_MA_WINDOWS)

    _append_reason(reasons, frame[price_columns].isna().any(axis=1), "missing_price")
    _append_reason(reasons, frame[price_columns].le(0).any(axis=1), "nonpositive_price")
    _append_reason(reasons, frame[ma_columns].isna().any(axis=1), "missing_price_ma")
    _append_reason(reasons, frame[ma_columns].le(0).any(axis=1), "nonpositive_price_ma")
    _append_reason(reasons, frame[volume_columns].isna().any(axis=1), "missing_volume_ma")
    _append_reason(reasons, frame[volume_columns].le(0).any(axis=1), "nonpositive_volume_ma")

    close_1500_gap = (frame["signal_close"] / frame["afternoon_1500_close"] - 1).abs()
    _append_reason(reasons, close_1500_gap > 0.001, "signal_close_mismatch")
    for column in ma_columns:
        bar_time = column.split("_")[1]
        reference = frame[f"afternoon_{bar_time}_close"]
        _append_reason(reasons, (frame[column] / reference - 1).abs() > 0.30, "implausible_ma_distance")

    duplicate_mask = frame.duplicated(subset=["code", "signal_date"], keep="last")
    _append_reason(reasons, duplicate_mask, "duplicate_code_date")
    rejected = frame.loc[reasons.ne("")].copy()
    rejected["reject_reason"] = reasons.loc[reasons.ne("")]
    clean = frame.loc[reasons.eq("")].copy()

    summary: dict[str, int] = {"input_rows": int(len(frame)), "accepted_basic_rows": int(len(clean))}
    for reason in sorted({item for value in reasons if value for item in str(value).split(";")}):
        summary[f"rejected_{reason}"] = int(reasons.str.contains(fr"(?:^|;){reason}(?:;|$)", regex=True).sum())
    return clean, rejected, summary


def _slope_pct(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    values = frame[list(columns)].to_numpy(dtype=float)
    x = np.arange(values.shape[1], dtype=float)
    x = x - x.mean()
    slope = np.sum(values * x, axis=1) / np.sum(x * x)
    scale = np.mean(np.abs(values), axis=1)
    return pd.Series(np.divide(slope, scale, out=np.full_like(slope, np.nan), where=scale > 0) * 100, index=frame.index)


def _change_pct(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    first = frame[columns[0]].astype(float)
    last = frame[columns[-1]].astype(float)
    return (last / first - 1) * 100


def _up_fraction(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    values = frame[list(columns)].to_numpy(dtype=float)
    return pd.Series((np.diff(values, axis=1) > 0).mean(axis=1), index=frame.index)


def _volatility_pct(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    values = frame[list(columns)].to_numpy(dtype=float)
    changes = np.diff(values, axis=1) / values[:, :-1] * 100
    return pd.Series(np.std(changes, axis=1), index=frame.index)


def _acceleration_pct(frame: pd.DataFrame, columns: Sequence[str]) -> pd.Series:
    values = frame[list(columns)].to_numpy(dtype=float)
    diffs = np.diff(values, axis=1)
    acceleration = diffs[:, -2:].mean(axis=1) - diffs[:, :2].mean(axis=1)
    scale = np.mean(np.abs(values), axis=1)
    return pd.Series(np.divide(acceleration, scale, out=np.full_like(acceleration, np.nan), where=scale > 0) * 100, index=frame.index)


def engineer_features(frame: pd.DataFrame, big_rise_pct: float, cost_bps: float) -> tuple[pd.DataFrame, list[str]]:
    data = frame.copy()
    close_columns = [f"afternoon_{bar_time}_close" for bar_time in FEATURE_TIMES]
    ma5_columns = [f"afternoon_{bar_time}_price_ma5" for bar_time in FEATURE_TIMES]
    ma10_columns = [f"afternoon_{bar_time}_price_ma10" for bar_time in FEATURE_TIMES]
    ma60_columns = [f"afternoon_{bar_time}_price_ma60" for bar_time in FEATURE_TIMES]
    vma5_columns = [f"afternoon_{bar_time}_volume_ma5" for bar_time in FEATURE_TIMES]
    vma10_columns = [f"afternoon_{bar_time}_volume_ma10" for bar_time in FEATURE_TIMES]

    close_1455 = data["afternoon_1455_close"]
    next_around_1000 = data[[f"next_{bar_time}_close" for bar_time in TARGET_TIMES]].mean(axis=1)
    data["target_around_1000_price"] = next_around_1000
    data["target_return_pct"] = (next_around_1000 / close_1455 - 1) * 100
    data["target_1000_return_pct"] = (data["next_1000_close"] / close_1455 - 1) * 100
    data["target_from_close_pct"] = (next_around_1000 / data["signal_close"] - 1) * 100
    data["target_net_return_pct"] = data["target_return_pct"] - cost_bps / 100
    data["target_win"] = (data["target_return_pct"] > 0).astype(int)
    data["target_big_rise"] = (data["target_return_pct"] >= big_rise_pct).astype(int)

    data["late_price_return_pct"] = _change_pct(data, close_columns)
    data["ma5_gap_ma10_1430_pct"] = (data[ma5_columns[0]] / data[ma10_columns[0]] - 1) * 100
    data["ma5_gap_ma10_1455_pct"] = (data[ma5_columns[-1]] / data[ma10_columns[-1]] - 1) * 100
    data["ma5_gap_change_pp"] = data["ma5_gap_ma10_1455_pct"] - data["ma5_gap_ma10_1430_pct"]
    data["ma5_slope_pct_per_bar"] = _slope_pct(data, ma5_columns)
    data["ma10_slope_pct_per_bar"] = _slope_pct(data, ma10_columns)
    data["ma60_slope_pct_per_bar"] = _slope_pct(data, ma60_columns)
    data["ma5_slope_minus_ma10_slope"] = data["ma5_slope_pct_per_bar"] - data["ma10_slope_pct_per_bar"]
    data["ma5_acceleration_pct"] = _acceleration_pct(data, ma5_columns)
    data["ma10_acceleration_pct"] = _acceleration_pct(data, ma10_columns)
    data["ma5_up_fraction"] = _up_fraction(data, ma5_columns)
    data["ma10_up_fraction"] = _up_fraction(data, ma10_columns)
    data["ma5_volatility_pct"] = _volatility_pct(data, ma5_columns)
    data["ma10_volatility_pct"] = _volatility_pct(data, ma10_columns)
    data["price_gap_ma5_1455_pct"] = (close_1455 / data[ma5_columns[-1]] - 1) * 100
    data["price_gap_ma10_1455_pct"] = (close_1455 / data[ma10_columns[-1]] - 1) * 100
    data["price_gap_ma60_1455_pct"] = (close_1455 / data[ma60_columns[-1]] - 1) * 100

    data["volume_ma5_gap_ma10_1430_pct"] = (data[vma5_columns[0]] / data[vma10_columns[0]] - 1) * 100
    data["volume_ma5_gap_ma10_1455_pct"] = (data[vma5_columns[-1]] / data[vma10_columns[-1]] - 1) * 100
    data["volume_gap_change_pp"] = data["volume_ma5_gap_ma10_1455_pct"] - data["volume_ma5_gap_ma10_1430_pct"]
    data["volume_ma5_slope_pct_per_bar"] = _slope_pct(data, vma5_columns)
    data["volume_ma10_slope_pct_per_bar"] = _slope_pct(data, vma10_columns)
    data["volume_ma5_up_fraction"] = _up_fraction(data, vma5_columns)

    gap_start = data[ma5_columns[0]] - data[ma10_columns[0]]
    gap_end = data[ma5_columns[-1]] - data[ma10_columns[-1]]
    data["ma5_above_ma10_1455"] = (gap_end > 0).astype(int)
    data["ma5_cross_up"] = ((gap_start <= 0) & (gap_end > 0)).astype(int)
    data["ma5_cross_down"] = ((gap_start >= 0) & (gap_end < 0)).astype(int)
    data["bullish_alignment_1455"] = (
        (close_1455 > data[ma5_columns[-1]])
        & (data[ma5_columns[-1]] > data[ma10_columns[-1]])
        & (data[ma10_columns[-1]] > data[ma60_columns[-1]])
    ).astype(int)
    data["price_volume_same_direction"] = (
        np.sign(data["ma5_slope_pct_per_bar"]) == np.sign(data["volume_ma5_slope_pct_per_bar"])
    ).astype(int)

    feature_columns = list(FEATURE_LABELS)
    data["target_date_median_pct"] = data.groupby("signal_date")["target_return_pct"].transform("median")
    data["target_excess_return_pct"] = data["target_return_pct"] - data["target_date_median_pct"]
    data["target_outperform_day"] = (data["target_excess_return_pct"] > 0).astype(int)
    return data, feature_columns


def reject_return_outliers(
    data: pd.DataFrame,
    rejected: pd.DataFrame,
    summary: dict[str, int],
    max_absolute_return_pct: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    finite_columns = ["target_return_pct", "target_1000_return_pct", *FEATURE_LABELS.keys()]
    finite_mask = np.isfinite(data[finite_columns].to_numpy(dtype=float)).all(axis=1)
    return_mask = data["target_return_pct"].abs() <= max_absolute_return_pct
    keep = pd.Series(finite_mask, index=data.index) & return_mask
    extra = data.loc[~keep, ["code", "name", "signal_date", "next_trade_date", "target_return_pct"]].copy()
    extra["reject_reason"] = np.where(~pd.Series(finite_mask, index=data.index).loc[~keep], "nonfinite_feature", "implausible_return")
    rejected = pd.concat([rejected, extra], ignore_index=True, sort=False)
    summary["rejected_nonfinite_or_return_outlier"] = int((~keep).sum())
    summary["final_modeling_rows"] = int(keep.sum())
    return data.loc[keep].copy(), rejected


def split_by_date(data: pd.DataFrame, validation_days: int) -> tuple[pd.DataFrame, pd.DataFrame, list[pd.Timestamp]]:
    dates = sorted(data["signal_date"].dropna().unique())
    if len(dates) < 10:
        raise ValueError(f"只有{len(dates)}个交易日，至少需要10天")
    validation_days = max(3, min(int(validation_days), len(dates) - 5))
    validation_dates = dates[-validation_days:]
    train = data.loc[~data["signal_date"].isin(validation_dates)].copy()
    validation = data.loc[data["signal_date"].isin(validation_dates)].copy()
    return train, validation, validation_dates


def wilson_lower_bound(wins: int, count: int, z: float = 1.0) -> float:
    if count <= 0:
        return math.nan
    p = wins / count
    denominator = 1 + z * z / count
    centre = p + z * z / (2 * count)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * count)) / count)
    return (centre - margin) / denominator


def subset_metrics(frame: pd.DataFrame, mask: pd.Series, big_rise_pct: float) -> dict[str, float]:
    subset = frame.loc[mask]
    count = len(subset)
    if not count:
        return {
            "count": 0,
            "date_count": 0,
            "mean_return_pct": math.nan,
            "median_return_pct": math.nan,
            "daily_return_lcb_pct": math.nan,
            "win_rate": math.nan,
            "win_wilson_lower": math.nan,
            "big_rise_rate": math.nan,
            "mean_excess_return_pct": math.nan,
            "outperform_rate": math.nan,
            "positive_mean_day_rate": math.nan,
            "positive_excess_day_rate": math.nan,
        }
    returns = subset["target_return_pct"]
    daily = subset.groupby("signal_date", observed=True)["target_return_pct"].mean()
    daily_excess = subset.groupby("signal_date", observed=True)["target_excess_return_pct"].mean()
    daily_sem = daily.std(ddof=1) / math.sqrt(len(daily)) if len(daily) > 1 else 0.0
    wins = int((returns > 0).sum())
    return {
        "count": int(count),
        "date_count": int(subset["signal_date"].nunique()),
        "mean_return_pct": float(returns.mean()),
        "median_return_pct": float(returns.median()),
        "daily_return_lcb_pct": float(daily.mean() - daily_sem),
        "win_rate": float(wins / count),
        "win_wilson_lower": float(wilson_lower_bound(wins, count)),
        "big_rise_rate": float((returns >= big_rise_pct).mean()),
        "mean_excess_return_pct": float(subset["target_excess_return_pct"].mean()),
        "outperform_rate": float((subset["target_excess_return_pct"] > 0).mean()),
        "positive_mean_day_rate": float((daily > 0).mean()),
        "positive_excess_day_rate": float((daily_excess > 0).mean()),
    }


def _condition_mask(frame: pd.DataFrame, condition: Condition) -> pd.Series:
    values = frame[condition.feature]
    if condition.operator == ">=":
        return values >= condition.threshold
    if condition.operator == "<=":
        return values <= condition.threshold
    if condition.operator == "==":
        return values == condition.threshold
    raise ValueError(f"未知操作符：{condition.operator}")


def condition_text(condition: Condition) -> str:
    label = FEATURE_LABELS.get(condition.feature, condition.feature)
    if condition.operator == "==":
        return label if condition.threshold == 1 else f"非({label})"
    return f"{label} {condition.operator} {condition.threshold:.4g}"


def make_conditions(train: pd.DataFrame, feature_columns: Sequence[str]) -> list[Condition]:
    conditions: list[Condition] = []
    for feature in feature_columns:
        if feature in BINARY_FEATURES:
            if train[feature].nunique() > 1:
                conditions.append(Condition(feature, "==", 1.0))
            continue
        values = train[feature].replace([np.inf, -np.inf], np.nan).dropna()
        if values.nunique() < 10:
            continue
        low, high = values.quantile([0.20, 0.80]).tolist()
        if low < high:
            conditions.append(Condition(feature, "<=", float(low)))
            conditions.append(Condition(feature, ">=", float(high)))
    return conditions


def discover_rules(
    train: pd.DataFrame,
    conditions: Sequence[Condition],
    *,
    max_rule_size: int,
    min_samples: int,
    min_days: int,
    big_rise_pct: float,
) -> tuple[pd.DataFrame, dict[str, float]]:
    baseline = subset_metrics(train, pd.Series(True, index=train.index), big_rise_pct)
    cached_masks = {index: _condition_mask(train, condition) for index, condition in enumerate(conditions)}
    candidate_specs: list[tuple[int, ...]] = [(index,) for index in range(len(conditions))]
    if max_rule_size >= 2:
        candidate_specs.extend(
            pair
            for pair in combinations(range(len(conditions)), 2)
            if conditions[pair[0]].feature != conditions[pair[1]].feature
        )

    rows: list[dict[str, Any]] = []
    for spec in candidate_specs:
        mask = cached_masks[spec[0]].copy()
        for index in spec[1:]:
            mask &= cached_masks[index]
        metrics = subset_metrics(train, mask, big_rise_pct)
        if metrics["count"] < min_samples or metrics["date_count"] < min_days:
            continue
        selected_conditions = [conditions[index] for index in spec]
        row: dict[str, Any] = {
            "conditions_json": json.dumps([condition.to_dict() for condition in selected_conditions], ensure_ascii=False),
            "rule": " 且 ".join(condition_text(condition) for condition in selected_conditions),
            "rule_size": len(selected_conditions),
            **metrics,
        }
        row["win_uplift_pp"] = (row["win_rate"] - baseline["win_rate"]) * 100
        row["return_uplift_pct"] = row["mean_return_pct"] - baseline["mean_return_pct"]
        row["big_rise_uplift_pp"] = (row["big_rise_rate"] - baseline["big_rise_rate"]) * 100
        row["win_discovery_score"] = row["win_wilson_lower"] - baseline["win_rate"]
        row["return_discovery_score"] = row["daily_return_lcb_pct"] - baseline["mean_return_pct"]
        rows.append(row)

    rules = pd.DataFrame(rows)
    if rules.empty:
        return rules, baseline
    win_top = rules.nlargest(100, "win_discovery_score")
    return_top = rules.nlargest(100, "return_discovery_score")
    big_top = rules.nlargest(100, "big_rise_uplift_pp")
    selected = pd.concat([win_top, return_top, big_top]).drop_duplicates(subset=["conditions_json"]).copy()
    selected = selected.sort_values(["return_discovery_score", "win_discovery_score"], ascending=False).reset_index(drop=True)
    selected.insert(0, "rule_id", [f"R{index:04d}" for index in range(1, len(selected) + 1)])
    return selected, baseline


def evaluate_rules(
    validation: pd.DataFrame,
    rules: pd.DataFrame,
    big_rise_pct: float,
) -> tuple[pd.DataFrame, dict[str, float]]:
    baseline = subset_metrics(validation, pd.Series(True, index=validation.index), big_rise_pct)
    rows: list[dict[str, Any]] = []
    for _, rule_row in rules.iterrows():
        specs = json.loads(rule_row["conditions_json"])
        conditions = [Condition(item["feature"], item["operator"], float(item["threshold"])) for item in specs]
        mask = pd.Series(True, index=validation.index)
        for condition in conditions:
            mask &= _condition_mask(validation, condition)
        metrics = subset_metrics(validation, mask, big_rise_pct)
        row = {"rule_id": rule_row["rule_id"], "rule": rule_row["rule"], **metrics}
        row["win_uplift_pp"] = (row["win_rate"] - baseline["win_rate"]) * 100
        row["return_uplift_pct"] = row["mean_return_pct"] - baseline["mean_return_pct"]
        row["big_rise_uplift_pp"] = (row["big_rise_rate"] - baseline["big_rise_rate"]) * 100
        rows.append(row)
    return pd.DataFrame(rows), baseline


def univariate_analysis(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    feature_columns: Sequence[str],
    big_rise_pct: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    bin_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    for feature in feature_columns:
        if feature in BINARY_FEATURES:
            edges = [-0.5, 0.5, 1.5]
            labels = ["0", "1"]
        else:
            quantiles = train[feature].quantile([0, 0.2, 0.4, 0.6, 0.8, 1]).to_numpy(dtype=float)
            edges = np.unique(quantiles)
            if len(edges) < 3:
                continue
            edges[0], edges[-1] = -np.inf, np.inf
            labels = [f"Q{index}" for index in range(1, len(edges))]

        feature_summary: dict[str, Any] = {"feature": feature, "feature_label": FEATURE_LABELS[feature]}
        for split_name, split in (("train", train), ("validation", validation)):
            bins = pd.cut(split[feature], bins=edges, labels=labels, include_lowest=True, duplicates="drop")
            split_copy = split.assign(_bin=bins)
            for bin_name, group in split_copy.groupby("_bin", observed=True):
                metrics = subset_metrics(group, pd.Series(True, index=group.index), big_rise_pct)
                bin_rows.append(
                    {
                        "feature": feature,
                        "feature_label": FEATURE_LABELS[feature],
                        "split": split_name,
                        "bin": str(bin_name),
                        "value_min": float(group[feature].min()),
                        "value_max": float(group[feature].max()),
                        **metrics,
                    }
                )
            feature_summary[f"{split_name}_spearman"] = float(
                split[feature].rank(method="average").corr(split["target_return_pct"].rank(method="average"))
            )
        summary_rows.append(feature_summary)
    return pd.DataFrame(bin_rows), pd.DataFrame(summary_rows)


def build_recommendations(
    train_rules: pd.DataFrame,
    validation_rules: pd.DataFrame,
    *,
    top_rules: int,
    min_validation_samples: int,
) -> pd.DataFrame:
    if train_rules.empty or validation_rules.empty:
        return pd.DataFrame()
    train_columns = [
        "rule_id",
        "conditions_json",
        "win_rate",
        "mean_return_pct",
        "big_rise_rate",
        "win_uplift_pp",
        "return_uplift_pct",
        "big_rise_uplift_pp",
        "daily_return_lcb_pct",
        "positive_excess_day_rate",
    ]
    combined = validation_rules.merge(
        train_rules[train_columns], on="rule_id", suffixes=("_validation", "_train"), how="inner"
    )
    eligible = combined.loc[
        (combined["count"] >= min_validation_samples)
        & (combined["date_count"] >= 3)
        & (combined["win_uplift_pp_train"] > 0)
        & (combined["return_uplift_pct_train"] > 0)
        & (combined["win_uplift_pp_validation"] > 0)
        & (combined["return_uplift_pct_validation"] > 0)
        & (combined["daily_return_lcb_pct_validation"] > 0)
        & (combined["positive_excess_day_rate_validation"] >= 0.50)
    ].copy()
    if eligible.empty:
        return eligible
    eligible["robust_win_uplift_pp"] = eligible[["win_uplift_pp_train", "win_uplift_pp_validation"]].min(axis=1)
    eligible["robust_return_uplift_pct"] = eligible[
        ["return_uplift_pct_train", "return_uplift_pct_validation"]
    ].min(axis=1)
    eligible["robust_big_rise_uplift_pp"] = eligible[
        ["big_rise_uplift_pp_train", "big_rise_uplift_pp_validation"]
    ].min(axis=1)
    win = eligible.nlargest(top_rules, ["robust_win_uplift_pp", "win_rate_validation"]).copy()
    win.insert(0, "objective", "最可能上涨")
    high = eligible.nlargest(top_rules, ["robust_return_uplift_pct", "mean_return_pct_validation"]).copy()
    high.insert(0, "objective", "最可能涨得多")
    return pd.concat([win, high], ignore_index=True)


def _fmt_pct(value: float, digits: int = 3) -> str:
    return "NA" if pd.isna(value) else f"{value:.{digits}f}%"


def write_report(
    path: Path,
    *,
    summary: dict[str, int],
    train: pd.DataFrame,
    validation: pd.DataFrame,
    train_baseline: dict[str, float],
    validation_baseline: dict[str, float],
    recommendations: pd.DataFrame,
    feature_summary: pd.DataFrame,
    args: argparse.Namespace,
) -> None:
    lines = [
        "# 尾盘均线与次日上午收益实验",
        "",
        "## 实验口径",
        "",
        "- 决策信息只使用14:30至14:55，避免把15:00收盘后才能确认的信息作为可交易特征。",
        "- 主标签：次日09:55、10:00、10:05三根5分钟收盘价的均值，相对信号日14:55价格的涨跌幅。",
        "- MA5/MA10是主特征；MA60只用于趋势位置和多头排列辅助。",
        f"- 大涨阈值：{args.big_rise_pct:.2f}%；成本敏感列按{args.round_trip_cost_bps:.1f}bp往返成本计算。",
        "- 规则只在训练日期发现，最后几个日期仅做时间外验证；没有随机拆分。",
        "",
        "## 数据与清洗",
        "",
        f"- 原始行数：{summary.get('input_rows', 0):,}",
        f"- 最终建模行数：{summary.get('final_modeling_rows', 0):,}",
        f"- 训练：{len(train):,}行，{train['signal_date'].nunique()}个交易日，"
        f"{train['signal_date'].min().date()}至{train['signal_date'].max().date()}",
        f"- 验证：{len(validation):,}行，{validation['signal_date'].nunique()}个交易日，"
        f"{validation['signal_date'].min().date()}至{validation['signal_date'].max().date()}",
        "- 原始SQLite未修改；被拒绝样本另存并带原因。",
        "",
        "## 全市场基线",
        "",
        f"- 训练：上涨概率 {_fmt_pct(train_baseline['win_rate'] * 100)}，"
        f"平均收益 {_fmt_pct(train_baseline['mean_return_pct'])}，"
        f"大涨概率 {_fmt_pct(train_baseline['big_rise_rate'] * 100)}。",
        f"- 验证：上涨概率 {_fmt_pct(validation_baseline['win_rate'] * 100)}，"
        f"平均收益 {_fmt_pct(validation_baseline['mean_return_pct'])}，"
        f"大涨概率 {_fmt_pct(validation_baseline['big_rise_rate'] * 100)}。",
        "",
        "## 时间外仍为正向的规则",
        "",
    ]
    if recommendations.empty:
        lines.append("没有规则同时满足训练和验证均优于基线的严格条件。不要放宽条件硬凑结论，应增加更多月份。")
    else:
        for objective in ("最可能上涨", "最可能涨得多"):
            lines.extend([f"### {objective}", ""])
            subset = recommendations.loc[recommendations["objective"] == objective].head(10)
            for rank, (_, row) in enumerate(subset.iterrows(), start=1):
                lines.append(
                    f"{rank}. **{row['rule']}** — 验证样本{int(row['count'])}，"
                    f"上涨概率{_fmt_pct(row['win_rate_validation'] * 100)}，"
                    f"平均收益{_fmt_pct(row['mean_return_pct_validation'])}，"
                    f"验证期相对收益为正的交易日占比{_fmt_pct(row['positive_excess_day_rate_validation'] * 100, 1)}，"
                    f"相对验证基线上涨概率提升{_fmt_pct(row['win_uplift_pp_validation'])}，"
                    f"平均收益提升{_fmt_pct(row['return_uplift_pct_validation'])}。"
                )
            lines.append("")

    lines.extend(["## 单变量方向", ""])
    stable = feature_summary.dropna().copy()
    if not stable.empty:
        stable["stable_abs_correlation"] = stable[["train_spearman", "validation_spearman"]].abs().min(axis=1)
        same_sign = np.sign(stable["train_spearman"]) == np.sign(stable["validation_spearman"])
        for _, row in stable.loc[same_sign].nlargest(10, "stable_abs_correlation").iterrows():
            direction = "越大越有利" if row["validation_spearman"] > 0 else "越小越有利"
            lines.append(
                f"- {row['feature_label']}：{direction}；训练/验证Spearman="
                f"{row['train_spearman']:.3f}/{row['validation_spearman']:.3f}。"
            )

    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- 只有约一个月、22个交易日，规则仍属于探索性证据，不是因果结论。",
            "- 最终应保留这些阈值，用未来完整月份做真正未见样本测试；不要根据未来结果反复调阈值。",
            "- 报告没有模拟涨停买不到、停牌、冲击成本和个股容量，实盘收益会低于毛收益。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = load_records(args.input)
    clean, rejected, summary = clean_records(raw, include_risk_names=args.include_risk_names)
    featured, feature_columns = engineer_features(clean, args.big_rise_pct, args.round_trip_cost_bps)
    featured, rejected = reject_return_outliers(featured, rejected, summary, args.max_absolute_return_pct)
    train, validation, validation_dates = split_by_date(featured, args.validation_days)

    bins, feature_summary = univariate_analysis(train, validation, feature_columns, args.big_rise_pct)
    conditions = make_conditions(train, feature_columns)
    rules_train, train_baseline = discover_rules(
        train,
        conditions,
        max_rule_size=args.max_rule_size,
        min_samples=args.min_rule_samples,
        min_days=args.min_rule_days,
        big_rise_pct=args.big_rise_pct,
    )
    rules_validation, validation_baseline = evaluate_rules(validation, rules_train, args.big_rise_pct)
    min_validation_samples = max(80, int(args.min_rule_samples * len(validation) / max(len(train), 1) * 0.7))
    recommendations = build_recommendations(
        rules_train,
        rules_validation,
        top_rules=args.top_rules,
        min_validation_samples=min_validation_samples,
    )

    featured.to_csv(args.output_dir / "modeling_dataset.csv.gz", index=False, compression="gzip", encoding="utf-8-sig")
    rejected.to_csv(args.output_dir / "rejected_rows.csv.gz", index=False, compression="gzip", encoding="utf-8-sig")
    bins.to_csv(args.output_dir / "univariate_bins.csv", index=False, encoding="utf-8-sig")
    feature_summary.to_csv(args.output_dir / "feature_correlations.csv", index=False, encoding="utf-8-sig")
    rules_train.to_csv(args.output_dir / "rules_discovered_train.csv", index=False, encoding="utf-8-sig")
    rules_validation.to_csv(args.output_dir / "rules_time_validation.csv", index=False, encoding="utf-8-sig")
    recommendations.to_csv(args.output_dir / "recommendations.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [
            {"split": "train", **train_baseline},
            {"split": "validation", **validation_baseline},
        ]
    ).to_csv(args.output_dir / "baselines.csv", index=False, encoding="utf-8-sig")
    summary.update(
        {
            "train_rows": int(len(train)),
            "validation_rows": int(len(validation)),
            "train_dates": int(train["signal_date"].nunique()),
            "validation_dates": int(validation["signal_date"].nunique()),
            "candidate_conditions": int(len(conditions)),
            "selected_rules": int(len(rules_train)),
            "confirmed_recommendations": int(len(recommendations)),
        }
    )
    (args.output_dir / "cleaning_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output_dir / "experiment_config.json").write_text(
        json.dumps(
            {
                **vars(args),
                "input": str(args.input),
                "output_dir": str(args.output_dir),
                "source_policy": SOURCE_POLICY_VERSION,
                "validation_date_values": [pd.Timestamp(value).strftime("%Y-%m-%d") for value in validation_dates],
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    write_report(
        args.output_dir / "report.md",
        summary=summary,
        train=train,
        validation=validation,
        train_baseline=train_baseline,
        validation_baseline=validation_baseline,
        recommendations=recommendations,
        feature_summary=feature_summary,
        args=args,
    )
    print(f"建模样本={len(featured):,}，训练={len(train):,}，验证={len(validation):,}")
    print(f"候选条件={len(conditions)}，训练选中规则={len(rules_train)}，稳健推荐={len(recommendations)}")
    print(f"报告={args.output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
