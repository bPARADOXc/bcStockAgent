#!/usr/bin/env python3
"""Run the A-share main-board momentum screener and save candidate files."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.a_stock_data_provider import AStockDataProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screen A-share main-board momentum candidates.")
    parser.add_argument("--min-lot-amount", type=float, default=2000.0, help="Minimum one-lot amount in CNY.")
    parser.add_argument("--max-lot-amount", type=float, default=3000.0, help="Maximum one-lot amount in CNY.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum candidates to save.")
    parser.add_argument(
        "--max-turnover-pct",
        type=float,
        default=10.0,
        help="Maximum turnover percent. Use 0 to disable the upper cap and include high-turnover priority-3 cases.",
    )
    parser.add_argument("--batch-size", type=int, default=80, help="Tencent quote batch size.")
    parser.add_argument("--quote-batch-interval", type=float, default=1.0, help="Seconds to wait between quote batches.")
    parser.add_argument("--volume-growth-days", type=int, default=3, help="Recent trading days for expanding volume check.")
    parser.add_argument("--ma-slope-days", type=int, default=3, help="Recent trading days for MA upward slope check.")
    parser.add_argument("--kline-lookback-days", type=int, default=45, help="Recent calendar days to fetch for K-line context.")
    parser.add_argument("--recent-position-days", type=int, default=20, help="Recent trading days for low/mid/high price-position label.")
    parser.add_argument("--kline-request-interval", type=float, default=1.8, help="Seconds to sleep between per-stock K-line checks.")
    parser.add_argument("--eastmoney-min-interval", type=float, default=1.8, help="Minimum seconds between Eastmoney requests during screening.")
    parser.add_argument("--output-dir", default="reports", help="Directory for CSV/TXT output files.")
    parser.add_argument(
        "--codes",
        default="",
        help="Optional comma-separated six-digit code subset for debugging, e.g. 600000,000001.",
    )
    parser.add_argument("--quiet", action="store_true", help="Do not print stage progress while screening.")
    return parser.parse_args()


def print_progress(message: str) -> None:
    print(message, flush=True)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    turnover_cap = None if args.max_turnover_pct <= 0 else args.max_turnover_pct
    codes = [code.strip() for code in args.codes.split(",") if code.strip()] or None
    progress = None if args.quiet else print_progress
    if progress:
        progress(
            "[A股筛选] 启动脚本："
            f"输出目录={output_dir}，一手金额={args.min_lot_amount:.0f}-{args.max_lot_amount:.0f}，"
            f"成交量窗口={args.volume_growth_days}日，均线窗口={args.ma_slope_days}日，"
            f"K线回看={args.kline_lookback_days}日，单股K线间隔={args.kline_request_interval:.1f}s，"
            f"东财最小间隔={args.eastmoney_min_interval:.1f}s。"
        )
    provider = AStockDataProvider()
    env = provider.screen_main_board_candidates(
        min_lot_amount=args.min_lot_amount,
        max_lot_amount=args.max_lot_amount,
        max_turnover_pct=turnover_cap,
        limit=args.limit,
        codes=codes,
        batch_size=args.batch_size,
        quote_batch_interval=args.quote_batch_interval,
        volume_growth_days=args.volume_growth_days,
        ma_slope_days=args.ma_slope_days,
        kline_lookback_days=args.kline_lookback_days,
        recent_position_days=args.recent_position_days,
        kline_request_interval=args.kline_request_interval,
        eastmoney_min_interval=args.eastmoney_min_interval,
        progress=progress,
    )

    payload = env.data or {}
    records = payload.get("records", [])
    screened_records = payload.get("screened_records", records)
    summary = payload.get("summary", {})
    min_amount = int(args.min_lot_amount)
    max_amount = int(args.max_lot_amount)
    stem = f"ashare_main_board_{min_amount}_{max_amount}"
    csv_path = output_dir / f"{stem}_candidates.csv"
    txt_path = output_dir / f"{stem}_codes.txt"

    if progress:
        progress(f"[A股筛选] 开始保存结果：实时行情通过 {len(screened_records)} 条，最终入选 {len(records)} 条。")
    pd.DataFrame(screened_records).to_csv(csv_path, index=False, encoding="utf-8-sig")
    with txt_path.open("w", encoding="utf-8") as handle:
        handle.write("A股主板候选股票代码:\n")
        handle.write(",".join(row.get("code", "") for row in records))
        handle.write("\n\n按优先级分组:\n")
        for priority in sorted({row.get("priority") for row in records}):
            group = [row.get("code", "") for row in records if row.get("priority") == priority]
            label = next((row.get("priority_label", "") for row in records if row.get("priority") == priority), "")
            handle.write(f"P{priority} {label}: {','.join(group)}\n")

    if progress:
        progress("[A股筛选] 结果保存完成。")
    print(f"status={env.status}")
    print(f"summary={summary}")
    if env.errors:
        print("errors=" + "; ".join(env.errors[:10]))
    print(f"saved_csv={csv_path}")
    print(f"saved_codes={txt_path}")


if __name__ == "__main__":
    main()
