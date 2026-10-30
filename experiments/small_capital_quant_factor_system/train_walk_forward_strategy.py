#!/usr/bin/env python3
"""Train a factor strategy on three months and backtest the following month.

The implementation follows the same discipline recommended by authoritative
time-series model-evaluation material: keep chronological splits, fit model
parameters on the training slice only, and evaluate the untouched later slice.
It intentionally depends only on pandas/numpy because the ``bcstock``
environment used by this project does not ship with scikit-learn.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.small_capital_quant_factor_system.fetch_training_data_4m import shift_months  # noqa: E402
from experiments.small_capital_quant_factor_system.factor_domains import (  # noqa: E402
    augment_factor_domains,
    available_factor_names,
    combine_factor_weights,
)
from experiments.small_capital_quant_factor_system.quant_strategy_system import (  # noqa: E402
    DEFAULT_CONFIG,
    StrategyConfig,
    backtest,
    datewise_percentile_score,
    factor_bins,
    factor_ic,
    latest_strategy,
    load_config,
    load_ohlcv,
    load_overnight,
    prepare_ohlcv,
    prepare_overnight,
    reject_modeling_outliers,
    select_single_stock_signals,
)


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "data_4m" / "ashare_overnight_5m.sqlite3"
DEFAULT_WINDOW_CONFIG = BASE_DIR / "data_4m" / "training_window.json"
DEFAULT_OUTPUT = BASE_DIR / "results_4m_walk_forward"
DEFAULT_THRESHOLDS = "0.50,0.55,0.60,0.62,0.65,0.70,0.75,0.80,0.85,0.90"


def parse_thresholds(raw: str) -> list[float]:
    values = sorted({float(item.strip()) for item in raw.split(",") if item.strip()})
    if not values or min(values) < 0 or max(values) > 1:
        raise argparse.ArgumentTypeError("score-threshold-grid 必须是 0 到 1 之间的逗号分隔数字")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="三个月训练、一个月样本外回测的小资金单股票因子策略。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--input-kind",
        choices=("overnight_sqlite", "overnight_csv", "ohlcv_csv"),
        default="overnight_sqlite",
    )
    parser.add_argument("--window-config", type=Path, default=DEFAULT_WINDOW_CONFIG)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--train-months", type=int, default=3, help="没有 training_window.json 时使用。")
    parser.add_argument("--backtest-months", type=int, default=1, help="没有 training_window.json 时使用。")
    parser.add_argument("--score-threshold-grid", type=parse_thresholds, default=parse_thresholds(DEFAULT_THRESHOLDS))
    parser.add_argument("--min-train-trades", type=int, default=10)
    parser.add_argument("--min-ic-days", type=int, default=8)
    parser.add_argument("--min-abs-ic", type=float, default=0.003)
    parser.add_argument("--score-threshold", type=float, default=None, help="只作为配置覆盖；最终阈值仍由训练期网格选择。")
    parser.add_argument("--min-amount", type=float, default=None)
    parser.add_argument("--include-risk-names", action="store_true")
    parser.add_argument("--hold-days", type=int, default=1, help="ohlcv_csv 模式持有天数。")
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


def _date_from_text(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def derive_window_from_data(
    data: pd.DataFrame,
    *,
    train_months: int,
    backtest_months: int,
) -> dict[str, str]:
    if data.empty:
        raise ValueError("数据为空，无法推导训练/回测窗口")
    end_date = pd.to_datetime(data["signal_date"]).max().date()
    start_date = shift_months(end_date, -(train_months + backtest_months)) + timedelta(days=1)
    backtest_start = shift_months(end_date, -backtest_months) + timedelta(days=1)
    return {
        "start_date": start_date.isoformat(),
        "train_start": start_date.isoformat(),
        "train_end": (backtest_start - timedelta(days=1)).isoformat(),
        "backtest_start": backtest_start.isoformat(),
        "backtest_end": end_date.isoformat(),
        "end_date": end_date.isoformat(),
        "train_months": str(train_months),
        "backtest_months": str(backtest_months),
        "source": "derived_from_data",
    }


def load_or_derive_window(args: argparse.Namespace, data: pd.DataFrame) -> dict[str, str]:
    if args.window_config.exists():
        payload = json.loads(args.window_config.read_text(encoding="utf-8"))
        required = {"train_start", "train_end", "backtest_start", "backtest_end"}
        missing = required - set(payload)
        if missing:
            raise ValueError(f"{args.window_config} 缺少字段：{','.join(sorted(missing))}")
        return {key: str(value) for key, value in payload.items()}
    return derive_window_from_data(data, train_months=args.train_months, backtest_months=args.backtest_months)


def load_and_prepare(
    args: argparse.Namespace,
    config: StrategyConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, float], pd.DataFrame]:
    if args.input_kind.startswith("overnight"):
        raw = load_overnight(args.input, args.input_kind)
        data, rejected = prepare_overnight(raw, config)
    else:
        raw = load_ohlcv(args.input)
        data, rejected = prepare_ohlcv(raw, config, args.hold_days)
    augmentation = augment_factor_domains(data, input_kind=args.input_kind, aux_factor_csvs=args.aux_factor_csv)
    data = augmentation.frame
    base_weights = combine_factor_weights(config, args.input_kind)
    factor_names = available_factor_names(data, base_weights)
    if not factor_names:
        raise ValueError("没有可用因子，请检查输入字段、辅助因子CSV和配置。")
    data, rejected = reject_modeling_outliers(data, rejected, factor_names)
    data["signal_date"] = pd.to_datetime(data["signal_date"], errors="coerce")
    return data.sort_values(["signal_date", "code"]).reset_index(drop=True), rejected, factor_names, base_weights, augmentation.metadata


def split_train_backtest(data: pd.DataFrame, window: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_start = pd.Timestamp(_date_from_text(window["train_start"]))
    train_end = pd.Timestamp(_date_from_text(window["train_end"]))
    backtest_start = pd.Timestamp(_date_from_text(window["backtest_start"]))
    backtest_end = pd.Timestamp(_date_from_text(window["backtest_end"]))
    in_window = data.loc[data["signal_date"].between(train_start, backtest_end)].copy()
    train = in_window.loc[in_window["signal_date"].between(train_start, train_end)].copy()
    backtest_slice = in_window.loc[in_window["signal_date"].between(backtest_start, backtest_end)].copy()
    if train.empty:
        raise ValueError(f"训练集为空：{train_start.date()} 至 {train_end.date()}")
    if backtest_slice.empty:
        raise ValueError(f"回测集为空：{backtest_start.date()} 至 {backtest_end.date()}")
    return in_window, train, backtest_slice


def train_factor_weights(
    train: pd.DataFrame,
    factor_names: Sequence[str],
    base_weights: dict[str, float],
    *,
    min_ic_days: int,
    min_abs_ic: float,
) -> tuple[dict[str, float], pd.DataFrame, str]:
    """Learn factor direction from training Rank IC only.

    Base config weights are treated as factor importance caps.  The sign and
    relative strength come from training-period mean Rank IC; if the sample is
    too thin, the function falls back to the hand-written config weights.
    """
    ic = factor_ic(train, factor_names)
    if ic.empty:
        return dict(base_weights), pd.DataFrame(), "fallback_config_no_ic"

    summary = (
        ic.dropna(subset=["rank_ic"])
        .groupby("factor")["rank_ic"]
        .agg(["mean", "median", "std", "count"])
        .rename(columns={"mean": "train_mean_rank_ic", "median": "train_median_rank_ic", "std": "train_std_rank_ic", "count": "train_ic_days"})
        .reset_index()
    )
    summary_map = summary.set_index("factor").to_dict(orient="index")
    raw_weights: dict[str, float] = {}
    for factor in factor_names:
        item = summary_map.get(factor, {})
        ic_days = int(item.get("train_ic_days", 0) or 0)
        mean_ic = float(item.get("train_mean_rank_ic", 0.0) or 0.0)
        importance = abs(base_weights.get(factor, 0.0))
        if ic_days < min_ic_days or abs(mean_ic) < min_abs_ic:
            raw_weights[factor] = 0.0
        else:
            raw_weights[factor] = importance * mean_ic

    raw_sum = sum(abs(value) for value in raw_weights.values())
    base_sum = sum(abs(base_weights.get(factor, 0.0)) for factor in factor_names) or 1.0
    if raw_sum <= 1e-12:
        weights = dict(base_weights)
        model_status = "fallback_config_weak_ic"
    else:
        scale = base_sum / raw_sum
        weights = {factor: raw_weights.get(factor, 0.0) * scale for factor in factor_names}
        model_status = "trained_rank_ic"

    rows: list[dict[str, Any]] = []
    for factor in factor_names:
        item = summary_map.get(factor, {})
        rows.append(
            {
                "factor": factor,
                "base_weight": base_weights.get(factor, 0.0),
                "trained_weight": weights.get(factor, 0.0),
                "train_mean_rank_ic": item.get("train_mean_rank_ic", np.nan),
                "train_median_rank_ic": item.get("train_median_rank_ic", np.nan),
                "train_std_rank_ic": item.get("train_std_rank_ic", np.nan),
                "train_ic_days": item.get("train_ic_days", 0),
                "kept_by_ic_filter": bool(abs(raw_weights.get(factor, 0.0)) > 0),
            }
        )
    return weights, pd.DataFrame(rows), model_status


def score_with_weights(data: pd.DataFrame, factor_names: Sequence[str], weights: dict[str, float], label: str) -> pd.DataFrame:
    scored = datewise_percentile_score(data, factor_names, weights)
    scored["weight_source"] = label
    for factor in factor_names:
        scored[f"effective_weight_{factor}"] = weights.get(factor, 0.0)
    return scored


def evaluate_threshold(
    scored: pd.DataFrame,
    config: StrategyConfig,
    threshold: float,
    initial_cash: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    tuned_config = replace(config, score_threshold=float(threshold))
    signals = select_single_stock_signals(scored, tuned_config)
    trades, equity, summary = backtest(signals, tuned_config, initial_cash)
    summary = dict(summary)
    summary["score_threshold"] = float(threshold)
    if summary.get("trade_count", 0) == 0:
        summary.update(
            {
                "win_rate": 0.0,
                "mean_net_return_pct": 0.0,
                "total_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "objective": -1_000_000.0,
            }
        )
    return signals, equity, summary


def choose_threshold(
    train_scored: pd.DataFrame,
    config: StrategyConfig,
    thresholds: Sequence[float],
    *,
    min_train_trades: int,
    initial_cash: float,
) -> tuple[float, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    artifacts: dict[float, tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]] = {}
    for threshold in thresholds:
        signals, equity, summary = evaluate_threshold(train_scored, config, threshold, initial_cash)
        trade_count = int(summary.get("trade_count", 0))
        total_return = float(summary.get("total_return_pct", 0.0))
        mean_return = float(summary.get("mean_net_return_pct", 0.0))
        drawdown = abs(float(summary.get("max_drawdown_pct", 0.0)))
        win_rate = float(summary.get("win_rate", 0.0))
        trade_penalty = max(min_train_trades - trade_count, 0) * 1.0
        loss_penalty = 3.0 if mean_return <= 0 else 0.0
        objective = total_return - 0.50 * drawdown + 2.0 * win_rate - trade_penalty - loss_penalty
        summary["objective"] = float(objective)
        rows.append(summary)
        artifacts[float(threshold)] = (signals, equity, summary)

    search = pd.DataFrame(rows).sort_values(["objective", "trade_count"], ascending=[False, False]).reset_index(drop=True)
    best_threshold = float(search.iloc[0]["score_threshold"])
    best_signals, best_equity, best_summary = artifacts[best_threshold]
    return best_threshold, search, best_signals, best_equity, best_summary


def risk_gate_status(train_summary: dict[str, Any], backtest_summary: dict[str, Any]) -> tuple[bool, str]:
    if int(train_summary.get("trade_count", 0)) == 0:
        return False, "训练期没有交易，风险总闸关闭"
    if float(train_summary.get("mean_net_return_pct", 0.0)) <= 0 or float(train_summary.get("total_return_pct", 0.0)) <= 0:
        return False, "训练期收益为负或单笔均值为负，风险总闸关闭"
    if int(backtest_summary.get("trade_count", 0)) == 0:
        return False, "回测期没有交易，风险总闸关闭"
    if float(backtest_summary.get("mean_net_return_pct", 0.0)) <= 0 or float(backtest_summary.get("total_return_pct", 0.0)) <= 0:
        return False, "样本外回测收益为负或单笔均值为负，风险总闸关闭"
    if float(backtest_summary.get("max_drawdown_pct", 0.0)) <= -15:
        return False, "样本外最大回撤超过15%，风险总闸关闭"
    return True, "训练期和样本外回测均为正，风险总闸打开；仍需人工检查流动性/盘口/涨跌停"


def write_report(
    path: Path,
    *,
    args: argparse.Namespace,
    window: dict[str, str],
    factor_names: Sequence[str],
    model_status: str,
    threshold: float,
    threshold_search: pd.DataFrame,
    weights_table: pd.DataFrame,
    train: pd.DataFrame,
    backtest_slice: pd.DataFrame,
    train_summary: dict[str, Any],
    backtest_summary: dict[str, Any],
    risk_open: bool,
    risk_reason: str,
    backtest_latest: pd.DataFrame,
) -> None:
    lines = [
        "# 三个月训练、一个月回测报告",
        "",
        "## 方法纪律",
        "",
        "- 时间切分：前三个月只训练，最后一个月只回测，不随机打散。",
        "- 因子方向：只使用训练期每日 Rank IC 学习；回测期不参与拟合。",
        "- 阈值选择：只在训练期网格搜索；回测期固定使用训练得到的阈值。",
        "- 标准化：使用当日横截面分位数，避免用未来日期的分布参数。",
        "- 数据清洗：只使用固定质控规则清除明显错误数据，不根据回测收益挑样本。",
        "",
        "## 数据窗口",
        "",
        f"- 输入：`{args.input}` (`{args.input_kind}`)",
        f"- 训练：{window['train_start']} 至 {window['train_end']}，行数 {len(train):,}，交易日 {train['signal_date'].nunique()}",
        f"- 回测：{window['backtest_start']} 至 {window['backtest_end']}，行数 {len(backtest_slice):,}，交易日 {backtest_slice['signal_date'].nunique()}",
        "",
        "## 训练结果",
        "",
        f"- 模型状态：`{model_status}`",
        f"- 选中阈值：{threshold:.3f}",
        f"- 风险总闸：{'打开' if risk_open else '关闭'}。{risk_reason}",
        "",
        "## 训练期回测摘要",
        "",
        _summary_line(train_summary),
        "",
        "## 样本外回测摘要",
        "",
        _summary_line(backtest_summary),
        "",
        "## 训练期阈值搜索 Top 5",
        "",
    ]
    if threshold_search.empty:
        lines.append("- 无阈值搜索结果。")
    else:
        for _, row in threshold_search.head(5).iterrows():
            lines.append(
                "- threshold={:.3f}, objective={:.3f}, trades={}, total={:.2f}%, mean={:.3f}%, mdd={:.2f}%".format(
                    row["score_threshold"],
                    row["objective"],
                    int(row.get("trade_count", 0)),
                    row.get("total_return_pct", 0.0),
                    row.get("mean_net_return_pct", 0.0),
                    row.get("max_drawdown_pct", 0.0),
                )
            )

    lines.extend(["", "## 训练得到的因子方向", ""])
    if weights_table.empty:
        lines.append("- 因子 IC 不足，使用配置权重。")
    else:
        top_weights = weights_table.reindex(weights_table["trained_weight"].abs().sort_values(ascending=False).index)
        for _, row in top_weights.head(12).iterrows():
            direction = "高值偏多" if row["trained_weight"] > 0 else "低值偏多" if row["trained_weight"] < 0 else "未启用"
            lines.append(
                f"- {row['factor']}: {direction}，weight={row['trained_weight']:.4f}，"
                f"train_mean_IC={row['train_mean_rank_ic']:.4f}，days={int(row['train_ic_days'])}"
            )

    lines.extend(["", "## 回测期最新候选", ""])
    if backtest_latest.empty:
        lines.append("- 无候选。")
    else:
        for rank, (_, row) in enumerate(backtest_latest.head(5).iterrows(), start=1):
            lines.append(
                f"{rank}. `{row['code']}` {row.get('name', '')}: score={row['raw_score']:.3f}, "
                f"selected={int(row.get('selected_by_system', 0))}, top={row.get('top_factor_1', '')}/"
                f"{row.get('top_factor_2', '')}/{row.get('top_factor_3', '')}"
            )

    lines.extend(
        [
            "",
            "## 参考原则来源",
            "",
            "- scikit-learn 官方交叉验证文档：时间序列评估应避免用未来训练过去。",
            "- scikit-learn 官方 Common pitfalls：数据泄漏通常来自在切分前拟合预处理或参数。",
            "- scikit-learn Pipeline 文档：正式工程里应把拟合步骤限定在训练数据上；本项目因 bcstock 未安装 sklearn，用 pandas/numpy 实现同等切分纪律。",
            "",
            "## 风险提示",
            "",
            "- 小资金全仓单票策略的主要风险是跳空、涨跌停无法成交、盘口流动性与样本外失效。",
            "- 该脚本只给研究和回测结果，不自动下单，也不构成投资建议。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _summary_line(summary: dict[str, Any]) -> str:
    if int(summary.get("trade_count", 0)) == 0:
        return "- 没有生成交易。"
    return (
        f"- 交易 {int(summary['trade_count'])} 次，胜率 {summary['win_rate'] * 100:.2f}%，"
        f"单笔均值 {summary['mean_net_return_pct']:.3f}%，总收益 {summary['total_return_pct']:.2f}%，"
        f"最大回撤 {summary['max_drawdown_pct']:.2f}%。"
    )


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = load_config(args.config, args)

    data, rejected, factor_names, base_weights, factor_metadata = load_and_prepare(args, config)
    window = load_or_derive_window(args, data)
    in_window, train, backtest_slice = split_train_backtest(data, window)
    weights, weights_table, model_status = train_factor_weights(
        train,
        factor_names,
        base_weights,
        min_ic_days=args.min_ic_days,
        min_abs_ic=args.min_abs_ic,
    )
    train_scored = score_with_weights(train, factor_names, weights, model_status)
    backtest_scored = score_with_weights(backtest_slice, factor_names, weights, model_status)
    threshold, threshold_search, train_signals, train_equity, train_summary = choose_threshold(
        train_scored,
        config,
        args.score_threshold_grid,
        min_train_trades=args.min_train_trades,
        initial_cash=args.initial_cash,
    )
    trained_config = replace(config, score_threshold=threshold)
    backtest_signals = select_single_stock_signals(backtest_scored, trained_config)
    backtest_trades, backtest_equity, backtest_summary = backtest(backtest_signals, trained_config, args.initial_cash)
    risk_open, risk_reason = risk_gate_status(train_summary, backtest_summary)
    backtest_latest = latest_strategy(backtest_scored, backtest_signals, trained_config, args.top_candidates, backtest_summary)
    if not risk_open and not backtest_latest.empty:
        backtest_latest["strategy_action"] = "风险总闸关闭：仅观察，不建议进入"
        backtest_latest["selected_by_system"] = 0

    train_scored.to_csv(args.output_dir / "train_scored_universe.csv.gz", index=False, compression="gzip", encoding="utf-8-sig")
    backtest_scored.to_csv(args.output_dir / "backtest_scored_universe.csv.gz", index=False, compression="gzip", encoding="utf-8-sig")
    rejected.to_csv(args.output_dir / "rejected_rows.csv", index=False, encoding="utf-8-sig")
    in_window.to_csv(args.output_dir / "modeling_window_rows.csv.gz", index=False, compression="gzip", encoding="utf-8-sig")
    weights_table.to_csv(args.output_dir / "trained_factor_weights.csv", index=False, encoding="utf-8-sig")
    threshold_search.to_csv(args.output_dir / "threshold_search_train.csv", index=False, encoding="utf-8-sig")
    train_signals.to_csv(args.output_dir / "train_signals.csv", index=False, encoding="utf-8-sig")
    backtest_signals.to_csv(args.output_dir / "backtest_signals.csv", index=False, encoding="utf-8-sig")
    train_equity.to_csv(args.output_dir / "train_equity_curve.csv", index=False, encoding="utf-8-sig")
    backtest_trades.to_csv(args.output_dir / "backtest_trades.csv", index=False, encoding="utf-8-sig")
    backtest_equity.to_csv(args.output_dir / "backtest_equity_curve.csv", index=False, encoding="utf-8-sig")
    factor_ic(train_scored, factor_names).to_csv(args.output_dir / "train_factor_ic.csv", index=False, encoding="utf-8-sig")
    factor_ic(backtest_scored, factor_names).to_csv(args.output_dir / "backtest_factor_ic.csv", index=False, encoding="utf-8-sig")
    factor_bins(train_scored, factor_names).to_csv(args.output_dir / "train_factor_bins.csv", index=False, encoding="utf-8-sig")
    factor_bins(backtest_scored, factor_names).to_csv(args.output_dir / "backtest_factor_bins.csv", index=False, encoding="utf-8-sig")
    backtest_latest.to_csv(args.output_dir / "latest_backtest_candidates.csv", index=False, encoding="utf-8-sig")
    factor_metadata.to_csv(args.output_dir / "factor_domain_metadata.csv", index=False, encoding="utf-8-sig")

    model_card = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(args.input),
        "input_kind": args.input_kind,
        "aux_factor_csv": [str(path) for path in args.aux_factor_csv],
        "window": window,
        "factor_names": list(factor_names),
        "model_status": model_status,
        "trained_weights": weights,
        "chosen_score_threshold": threshold,
        "train_summary": train_summary,
        "backtest_summary": backtest_summary,
        "risk_gate_open": risk_open,
        "risk_gate_reason": risk_reason,
        "method": "train Rank IC weights and threshold on first 3 months; apply fixed model to following 1 month",
    }
    (args.output_dir / "trained_factor_model.json").write_text(
        json.dumps(model_card, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    write_report(
        args.output_dir / "report.md",
        args=args,
        window=window,
        factor_names=factor_names,
        model_status=model_status,
        threshold=threshold,
        threshold_search=threshold_search,
        weights_table=weights_table,
        train=train,
        backtest_slice=backtest_slice,
        train_summary=train_summary,
        backtest_summary=backtest_summary,
        risk_open=risk_open,
        risk_reason=risk_reason,
        backtest_latest=backtest_latest,
    )
    print(f"训练行数={len(train):,}，回测行数={len(backtest_slice):,}")
    print(f"模型状态={model_status}，阈值={threshold:.3f}，风险总闸={'打开' if risk_open else '关闭'}")
    print(f"报告={args.output_dir / 'report.md'}")


if __name__ == "__main__":
    main()
