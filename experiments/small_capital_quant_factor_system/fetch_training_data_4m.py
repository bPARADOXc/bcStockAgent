#!/usr/bin/env python3
"""Fetch a continuous four-month dataset for the factor training pipeline.

This is a thin, backward-compatible wrapper around
``experiments.ashare_overnight_5m.fetch_dataset``.  The original crawler keeps
all of its flags and behavior; this script only computes a 4-month window,
passes the safer defaults through, and writes split metadata for the training
script.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.ashare_overnight_5m import fetch_dataset  # noqa: E402


CN_TZ = ZoneInfo("Asia/Shanghai")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = BASE_DIR / "data_4m"


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须是 YYYY-MM-DD") from exc


def shift_months(value: date, months: int) -> date:
    """Move by calendar months, clamping the day to the target month length."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return date(year, month, min(value.day, last_day))


def build_window(end_date: date, train_months: int, backtest_months: int) -> dict[str, str]:
    if train_months <= 0 or backtest_months <= 0:
        raise ValueError("train-months 和 backtest-months 必须为正数")
    total_months = train_months + backtest_months
    start_date = shift_months(end_date, -total_months) + timedelta(days=1)
    backtest_start = shift_months(end_date, -backtest_months) + timedelta(days=1)
    train_end = backtest_start - timedelta(days=1)
    if not (start_date <= train_end < backtest_start <= end_date):
        raise ValueError("训练/回测窗口计算异常")
    return {
        "start_date": start_date.isoformat(),
        "train_start": start_date.isoformat(),
        "train_end": train_end.isoformat(),
        "backtest_start": backtest_start.isoformat(),
        "backtest_end": end_date.isoformat(),
        "end_date": end_date.isoformat(),
        "train_months": str(train_months),
        "backtest_months": str(backtest_months),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="拉取训练量化系统所需的连续四个月隔夜5分钟数据，并写入训练/回测切分元数据。"
    )
    parser.add_argument("--codes", default="", help="逗号分隔的小样本代码；与 --full-market 二选一。")
    parser.add_argument("--full-market", action="store_true", help="显式确认拉取当前A股主板全市场。")
    parser.add_argument("--end-date", type=parse_iso_date, help="窗口终点，默认中国时区今天。")
    parser.add_argument("--train-months", type=int, default=3)
    parser.add_argument("--backtest-months", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--request-interval", type=float, default=1.8)
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
    parser.add_argument("--exclude-risk-names", action="store_true")
    parser.add_argument("--allow-partial-universe", action="store_true")
    parser.add_argument("--allow-market-hours", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def crawler_args(args: argparse.Namespace, window: dict[str, str]) -> argparse.Namespace:
    parser = fetch_dataset.build_parser()
    argv: list[str] = []
    if args.full_market:
        argv.append("--full-market")
    if args.codes:
        argv.extend(["--codes", args.codes])
    argv.extend(["--start-date", window["start_date"]])
    argv.extend(["--end-date", window["end_date"]])
    argv.extend(["--output-dir", str(args.output_dir)])
    argv.extend(["--request-interval", str(args.request_interval)])
    argv.extend(["--tdx-request-interval", str(args.tdx_request_interval)])
    argv.extend(["--sina-request-interval", str(args.sina_request_interval)])
    argv.extend(["--source-retries", str(args.source_retries)])
    argv.extend(["--eastmoney-retries", str(args.eastmoney_retries)])
    argv.extend(["--quote-batch-interval", str(args.quote_batch_interval)])
    argv.extend(["--quote-batch-size", str(args.quote_batch_size)])
    argv.extend(["--cooldown-every", str(args.cooldown_every)])
    argv.extend(["--cooldown-seconds", str(args.cooldown_seconds)])
    argv.extend(["--max-consecutive-failures", str(args.max_consecutive_failures)])
    argv.extend(["--max-infrastructure-failure-rate", str(args.max_infrastructure_failure_rate)])
    if args.max_stocks:
        argv.extend(["--max-stocks", str(args.max_stocks)])
    for flag in (
        "exclude_risk_names",
        "allow_partial_universe",
        "allow_market_hours",
        "force",
        "dry_run",
    ):
        if getattr(args, flag):
            argv.append("--" + flag.replace("_", "-"))
    return parser.parse_args(argv)


def write_window_config(output_dir: Path, window: dict[str, str], crawler_status: int) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        **window,
        "created_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "crawler_status": int(crawler_status),
        "sqlite_path": str(output_dir / "ashare_overnight_5m.sqlite3"),
        "csv_path": str(output_dir / "ashare_overnight_5m.csv"),
        "source": "experiments.ashare_overnight_5m.fetch_dataset",
        "source_policy": fetch_dataset.SOURCE_POLICY_VERSION,
        "note": "前三个月仅用于拟合因子方向/阈值，最后一个月只做样本外回测。",
    }
    path = output_dir / "training_window.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> None:
    args = parse_args()
    end_date = args.end_date or datetime.now(CN_TZ).date()
    window = build_window(end_date, args.train_months, args.backtest_months)
    status = fetch_dataset.run(crawler_args(args, window))
    metadata_path = write_window_config(args.output_dir, window, status)
    print(f"训练数据窗口：{window['start_date']} 至 {window['end_date']}")
    print(f"训练区间：{window['train_start']} 至 {window['train_end']}")
    print(f"回测区间：{window['backtest_start']} 至 {window['backtest_end']}")
    print(f"窗口元数据：{metadata_path}")
    raise SystemExit(status)


if __name__ == "__main__":
    main()
