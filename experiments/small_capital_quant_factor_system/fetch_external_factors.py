#!/usr/bin/env python3
"""Fetch external short-term factors and write CSVs for the strategy system.

The script first reuses ``tradingagents.dataflows.a_stock_data_provider``.
Only sources that were verified with small probes are wired in by default:

* THS hot-reason history -> lagged limit-up/theme ecology.
* Eastmoney 120-day stock fund flow -> lagged capital-flow factors.
* Eastmoney stock news + CNInfo announcements -> conservative attention/event
  factors, filtered by stock name/code to reduce false positives.

For the 14:55 overnight strategy, all generated rows use information available
before the signal cutoff.  Same-day full-session data is lagged to the next
signal date unless the source itself has precise intraday timestamps.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sqlite3
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiments.ashare_overnight_5m.fetch_dataset import SOURCE_POLICY_VERSION  # noqa: E402
from tradingagents.dataflows.a_stock_data_provider import AStockDataProvider, normalize_to_code  # noqa: E402


CN_TZ = ZoneInfo("Asia/Shanghai")
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = BASE_DIR / "data_4m" / "ashare_overnight_5m.sqlite3"
DEFAULT_WINDOW_CONFIG = BASE_DIR / "data_4m" / "training_window.json"
DEFAULT_OUTPUT = BASE_DIR / "my_factors"
DEFAULT_DOMAINS = "limit_ecology,sector_concept,capital_flow,sentiment_attention,event_disclosure"
POSITIVE_WORDS = (
    "利好",
    "预增",
    "增长",
    "大增",
    "扭亏",
    "中标",
    "合同",
    "合作",
    "回购",
    "增持",
    "获批",
    "突破",
    "涨停",
    "龙头",
    "订单",
    "扩产",
    "创新高",
)
NEGATIVE_WORDS = (
    "利空",
    "减持",
    "亏损",
    "预亏",
    "下滑",
    "问询",
    "处罚",
    "立案",
    "退市",
    "诉讼",
    "终止",
    "风险",
    "暴雷",
    "跌停",
    "被罚",
)


@dataclass
class FetchStats:
    source: str
    attempted: int = 0
    ok: int = 0
    empty: int = 0
    failed: int = 0
    errors: list[dict[str, str]] | None = None

    def add_error(self, key: str, error: Exception | str) -> None:
        self.failed += 1
        if self.errors is None:
            self.errors = []
        self.errors.append({"key": str(key), "error": str(error)[:1000]})


class RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = max(float(interval), 0.2)
        self.last_call = 0.0

    def wait(self) -> None:
        delay = self.interval - (time.monotonic() - self.last_call)
        if delay > 0:
            time.sleep(delay)
        self.last_call = time.monotonic()


def parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("日期必须是 YYYY-MM-DD") from exc


def parse_domains(raw: str) -> set[str]:
    domains = {item.strip() for item in raw.split(",") if item.strip()}
    if "all" in domains:
        domains = set(DEFAULT_DOMAINS.split(","))
    allowed = set(DEFAULT_DOMAINS.split(",")) | {"current_board_proxy"}
    unknown = domains - allowed
    if unknown:
        raise argparse.ArgumentTypeError("未知外部因子域：" + ",".join(sorted(unknown)))
    return domains


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自动生成小资金超短线策略所需的外部因子CSV。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--input-kind", choices=("overnight_sqlite", "overnight_csv"), default="overnight_sqlite")
    parser.add_argument("--window-config", type=Path, default=DEFAULT_WINDOW_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--domains", type=parse_domains, default=parse_domains(DEFAULT_DOMAINS))
    parser.add_argument("--codes", default="", help="逗号分隔代码；默认使用输入数据里的全部股票。")
    parser.add_argument("--start-date", type=parse_iso_date)
    parser.add_argument("--end-date", type=parse_iso_date)
    parser.add_argument("--max-stocks", type=int, default=0, help="调试限量；0表示不限制。")
    parser.add_argument("--request-interval", type=float, default=1.3)
    parser.add_argument("--capital-flow-interval", type=float, default=1.2)
    parser.add_argument("--news-request-interval", type=float, default=1.8)
    parser.add_argument("--source-retries", type=int, default=3)
    parser.add_argument("--cooldown-every", type=int, default=100)
    parser.add_argument("--cooldown-seconds", type=float, default=20.0)
    parser.add_argument("--news-mode", choices=("none", "hot", "all"), default="hot")
    parser.add_argument("--news-max-stocks", type=int, default=300)
    parser.add_argument("--news-page-size", type=int, default=20)
    parser.add_argument("--announcement-page-size", type=int, default=20)
    parser.add_argument("--sentiment-lookback-days", type=int, default=3)
    parser.add_argument("--confirm-heavy-news", action="store_true")
    parser.add_argument("--allow-market-hours", action="store_true")
    return parser.parse_args()


def configure_logging(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(output_dir / "fetch_external_factors.log", encoding="utf-8")],
        force=True,
    )


def in_continuous_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.timetz().replace(tzinfo=None)
    return dt_time(9, 15) <= current <= dt_time(15, 15)


def normalize_code_series(series: pd.Series) -> pd.Series:
    return series.astype("string").str.extract(r"(\d{6})", expand=False).str.zfill(6)


def parse_codes(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return sorted({normalize_to_code(item.strip()) for item in raw.split(",") if item.strip()})


def load_window(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {key: str(value) for key, value in json.loads(path.read_text(encoding="utf-8")).items()}


def load_base_records(args: argparse.Namespace) -> pd.DataFrame:
    if args.input_kind == "overnight_sqlite":
        connection = sqlite3.connect(args.input)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(experiment_records)")}
            if not columns:
                raise ValueError(f"{args.input} 没有 experiment_records 表")
            where = "WHERE source_policy=?" if "source_policy" in columns else ""
            params: tuple[Any, ...] = (SOURCE_POLICY_VERSION,) if where else ()
            frame = pd.read_sql_query(f"SELECT code,name,signal_date FROM experiment_records {where}", connection, params=params)
        finally:
            connection.close()
    else:
        frame = pd.read_csv(args.input, dtype={"code": "string"}, low_memory=False)
        keep = [column for column in ("code", "name", "signal_date") if column in frame.columns]
        frame = frame[keep].copy()
    if "name" not in frame.columns:
        frame["name"] = ""
    frame["code"] = normalize_code_series(frame["code"])
    frame["signal_date"] = pd.to_datetime(frame["signal_date"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["code", "signal_date"]).drop_duplicates(["signal_date", "code"])

    window = load_window(args.window_config)
    start_text = args.start_date or (date.fromisoformat(window["start_date"]) if "start_date" in window else None)
    end_text = args.end_date or (date.fromisoformat(window["end_date"]) if "end_date" in window else None)
    if start_text:
        frame = frame.loc[frame["signal_date"] >= pd.Timestamp(start_text)]
    if end_text:
        frame = frame.loc[frame["signal_date"] <= pd.Timestamp(end_text)]

    explicit_codes = parse_codes(args.codes)
    if explicit_codes:
        frame = frame.loc[frame["code"].isin(explicit_codes)]
    if args.max_stocks > 0:
        selected = sorted(frame["code"].dropna().unique())[: args.max_stocks]
        frame = frame.loc[frame["code"].isin(selected)]
    if frame.empty:
        raise RuntimeError("基础股票/日期矩阵为空，请检查 input/window/codes")
    return frame.sort_values(["signal_date", "code"]).reset_index(drop=True)


def available_at_morning(signal_date: pd.Timestamp) -> str:
    return f"{signal_date.date().isoformat()} 09:00:00"


def empty_factor_frame(base: pd.DataFrame, columns: Sequence[str], *, default_rank: float | None = None) -> pd.DataFrame:
    frame = base[["signal_date", "code"]].copy()
    frame["available_at"] = frame["signal_date"].map(available_at_morning)
    for column in columns:
        frame[column] = float(default_rank) if default_rank is not None and "rank" in column else 0.0
    return frame


def call_with_retries(
    label: str,
    func: Callable[[], Any],
    *,
    limiter: RateLimiter,
    retries: int,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(max(retries, 1)):
        limiter.wait()
        try:
            return func()
        except Exception as exc:
            last_error = exc
            if attempt + 1 < max(retries, 1):
                delay = min(1.0 * (2**attempt), 20.0)
                logging.warning("%s 第%s次失败：%s，%.1fs后重试", label, attempt + 1, exc, delay)
                time.sleep(delay)
    raise RuntimeError(f"{label} 重试耗尽：{last_error}")


def theme_tokens(raw: str) -> list[str]:
    tokens = []
    for token in re.split(r"[+、,/，；;|\s]+", str(raw or "")):
        token = token.strip()
        if token:
            tokens.append(token)
    return tokens


def previous_signal_dates(dates: Sequence[pd.Timestamp]) -> dict[pd.Timestamp, pd.Timestamp]:
    ordered = sorted(pd.Timestamp(value).normalize() for value in set(dates))
    return {ordered[index]: ordered[index - 1] for index in range(1, len(ordered))}


def fetch_hot_reason_history(
    provider: AStockDataProvider,
    signal_dates: Sequence[pd.Timestamp],
    *,
    limiter: RateLimiter,
    retries: int,
) -> tuple[dict[pd.Timestamp, list[dict]], FetchStats]:
    stats = FetchStats("ths_hot_reason")
    prev_map = previous_signal_dates(signal_dates)
    required_dates = sorted(set(prev_map.values()))
    history: dict[pd.Timestamp, list[dict]] = {}
    for index, value in enumerate(required_dates, start=1):
        stats.attempted += 1
        key = value.date().isoformat()
        try:
            rows = call_with_retries(
                f"ths_hot_reason {key}",
                lambda key=key: provider.ths_hot_reason(key),
                limiter=limiter,
                retries=retries,
            )
            history[value] = rows
            if rows:
                stats.ok += 1
            else:
                stats.empty += 1
            logging.info("热点题材 %s：%s 行 (%s/%s)", key, len(rows), index, len(required_dates))
        except Exception as exc:
            history[value] = []
            stats.add_error(key, exc)
            logging.warning("热点题材 %s 失败：%s", key, exc)
    return history, stats


def build_limit_and_sector_frames(base: pd.DataFrame, hot_history: dict[pd.Timestamp, list[dict]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    limit_columns = [
        "limit_up_count_in_sector",
        "broken_limit_rate",
        "limit_up_hit",
        "limit_up_change_pct",
        "limit_up_turnover_pct",
        "limit_up_amount_wan",
        "limit_up_big_order_net",
        "market_limit_up_count",
    ]
    sector_columns = [
        "sector_strength",
        "concept_heat",
        "stock_rank_in_sector",
        "stock_hot_hit",
        "theme_heat",
    ]
    limit_frame = empty_factor_frame(base, limit_columns)
    sector_frame = empty_factor_frame(base, sector_columns, default_rank=999.0)
    prev_map = previous_signal_dates(base["signal_date"].unique())
    index_map = {(row.signal_date, row.code): idx for idx, row in base[["signal_date", "code"]].iterrows()}

    for signal_date, prev_date in prev_map.items():
        rows = hot_history.get(prev_date, [])
        if not rows:
            continue
        token_counts = Counter(token for row in rows for token in theme_tokens(row.get("题材归因", "")))
        sorted_rows = sorted(
            rows,
            key=lambda row: (safe_float(row.get("涨幅%")), safe_float(row.get("成交额"))),
            reverse=True,
        )
        code_rank = {normalize_to_code(str(row.get("代码", ""))): rank for rank, row in enumerate(sorted_rows, start=1)}
        date_mask = limit_frame["signal_date"].eq(signal_date)
        limit_frame.loc[date_mask, "market_limit_up_count"] = float(len(rows))
        sector_frame.loc[date_mask, "stock_rank_in_sector"] = 999.0
        for row in rows:
            code = normalize_to_code(str(row.get("代码", "")))
            key = (signal_date, code)
            if key not in index_map:
                continue
            idx = index_map[key]
            tokens = theme_tokens(row.get("题材归因", ""))
            heat = max((token_counts[token] for token in tokens), default=0)
            limit_frame.loc[idx, "limit_up_count_in_sector"] = float(heat)
            limit_frame.loc[idx, "limit_up_hit"] = 1.0
            limit_frame.loc[idx, "limit_up_change_pct"] = safe_float(row.get("涨幅%"))
            limit_frame.loc[idx, "limit_up_turnover_pct"] = safe_float(row.get("换手率%"))
            limit_frame.loc[idx, "limit_up_amount_wan"] = safe_float(row.get("成交额"))
            limit_frame.loc[idx, "limit_up_big_order_net"] = safe_float(row.get("大单净量"))

            sector_frame.loc[idx, "sector_strength"] = safe_float(row.get("涨幅%"))
            sector_frame.loc[idx, "concept_heat"] = float(heat) / max(len(rows), 1)
            sector_frame.loc[idx, "stock_rank_in_sector"] = float(code_rank.get(code, 999))
            sector_frame.loc[idx, "stock_hot_hit"] = 1.0
            sector_frame.loc[idx, "theme_heat"] = float(heat)
    return limit_frame, sector_frame


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def fetch_capital_flows(
    provider: AStockDataProvider,
    codes: Sequence[str],
    *,
    limiter: RateLimiter,
    retries: int,
    cooldown_every: int,
    cooldown_seconds: float,
) -> tuple[dict[str, list[dict]], FetchStats]:
    stats = FetchStats("eastmoney_stock_fund_flow_120d")
    flows: dict[str, list[dict]] = {}
    for index, code in enumerate(codes, start=1):
        stats.attempted += 1
        try:
            rows = call_with_retries(
                f"stock_fund_flow_120d {code}",
                lambda code=code: provider.stock_fund_flow_120d(code),
                limiter=limiter,
                retries=retries,
            )
            flows[code] = rows
            if rows:
                stats.ok += 1
            else:
                stats.empty += 1
            logging.info("资金流 [%s/%s] %s：%s 行", index, len(codes), code, len(rows))
        except Exception as exc:
            flows[code] = []
            stats.add_error(code, exc)
            logging.warning("资金流 %s 失败：%s", code, exc)
        if cooldown_every > 0 and index % cooldown_every == 0 and index < len(codes):
            logging.info("资金流完成 %s 只，冷却 %.1f 秒", index, cooldown_seconds)
            time.sleep(max(cooldown_seconds, 0.0))
    return flows, stats


def build_capital_flow_frame(base: pd.DataFrame, flows: dict[str, list[dict]]) -> pd.DataFrame:
    columns = [
        "main_net_inflow_ratio",
        "large_order_net_inflow_ratio",
        "main_net_inflow_yi",
        "large_order_net_inflow_yi",
        "main_net_3d_yi",
        "large_order_3d_yi",
        "capital_flow_data_coverage",
    ]
    frame = empty_factor_frame(base, columns)
    for code, group in base.groupby("code"):
        records = flows.get(str(code), [])
        if not records:
            continue
        flow = pd.DataFrame(records)
        flow["date"] = pd.to_datetime(flow["date"], errors="coerce").dt.normalize()
        for column in ("main_net", "small_net", "mid_net", "large_net", "super_net"):
            flow[column] = pd.to_numeric(flow[column], errors="coerce").fillna(0.0)
        flow = flow.dropna(subset=["date"]).sort_values("date")
        if flow.empty:
            continue
        for idx, row in group.iterrows():
            hist = flow.loc[flow["date"] < row["signal_date"]]
            if hist.empty:
                continue
            latest = hist.iloc[-1]
            recent3 = hist.tail(3)
            denominator = sum(abs(float(latest.get(column, 0.0))) for column in ("main_net", "small_net", "mid_net", "large_net", "super_net")) or np.nan
            large_total = float(latest.get("large_net", 0.0)) + float(latest.get("super_net", 0.0))
            frame.loc[idx, "main_net_inflow_ratio"] = float(latest.get("main_net", 0.0)) / denominator if denominator else 0.0
            frame.loc[idx, "large_order_net_inflow_ratio"] = large_total / denominator if denominator else 0.0
            frame.loc[idx, "main_net_inflow_yi"] = float(latest.get("main_net", 0.0)) / 1e8
            frame.loc[idx, "large_order_net_inflow_yi"] = large_total / 1e8
            frame.loc[idx, "main_net_3d_yi"] = float(recent3["main_net"].sum()) / 1e8
            frame.loc[idx, "large_order_3d_yi"] = float((recent3["large_net"] + recent3["super_net"]).sum()) / 1e8
            frame.loc[idx, "capital_flow_data_coverage"] = 1.0
    return frame


def text_sentiment_score(texts: Iterable[str]) -> float:
    score = 0
    total_hits = 0
    combined = "\n".join(str(text or "") for text in texts)
    for word in POSITIVE_WORDS:
        hits = combined.count(word)
        score += hits
        total_hits += hits
    for word in NEGATIVE_WORDS:
        hits = combined.count(word)
        score -= hits
        total_hits += hits
    return float(score / total_hits) if total_hits else 0.0


def relevant_news_items(items: list[dict], code: str, name: str) -> list[dict]:
    relevant = []
    for item in items:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        if name and name in text:
            relevant.append(item)
        elif code in text and (name and name[:2] in text):
            relevant.append(item)
    return relevant


def fetch_news_and_events(
    provider: AStockDataProvider,
    base: pd.DataFrame,
    hot_history: dict[pd.Timestamp, list[dict]],
    *,
    mode: str,
    max_stocks: int,
    page_size: int,
    ann_page_size: int,
    limiter: RateLimiter,
    retries: int,
    confirm_heavy_news: bool,
) -> tuple[dict[str, list[dict]], dict[str, list[dict]], FetchStats]:
    stats = FetchStats("eastmoney_news_cninfo_announcements")
    if mode == "none":
        return {}, {}, stats
    universe = sorted(base["code"].unique())
    hot_codes = sorted({normalize_to_code(str(row.get("代码", ""))) for rows in hot_history.values() for row in rows})
    if mode == "hot":
        codes = [code for code in hot_codes if code in set(universe)]
    else:
        codes = universe
    if max_stocks > 0:
        codes = codes[:max_stocks]
    if mode == "all" and len(codes) > 500 and not confirm_heavy_news:
        raise RuntimeError("news-mode=all 且股票数超过500；如确需全市场新闻，请添加 --confirm-heavy-news")

    name_map = base.drop_duplicates("code").set_index("code")["name"].fillna("").to_dict()
    news_by_code: dict[str, list[dict]] = {}
    announcements_by_code: dict[str, list[dict]] = {}
    for index, code in enumerate(codes, start=1):
        stats.attempted += 1
        name = str(name_map.get(code, ""))
        try:
            news = call_with_retries(
                f"eastmoney_stock_news {code}",
                lambda code=code: provider.eastmoney_stock_news(code, page_size=page_size),
                limiter=limiter,
                retries=retries,
            )
            news_by_code[code] = relevant_news_items(news, code, name)
            anns = call_with_retries(
                f"cninfo_announcements {code}",
                lambda code=code: provider.cninfo_announcements(code, page_size=ann_page_size),
                limiter=limiter,
                retries=retries,
            )
            announcements_by_code[code] = anns
            stats.ok += 1
            logging.info(
                "新闻公告 [%s/%s] %s %s：news=%s/%s anns=%s",
                index,
                len(codes),
                code,
                name,
                len(news_by_code[code]),
                len(news),
                len(anns),
            )
        except Exception as exc:
            news_by_code[code] = []
            announcements_by_code[code] = []
            stats.add_error(code, exc)
            logging.warning("新闻公告 %s 失败：%s", code, exc)
    return news_by_code, announcements_by_code, stats


def parse_news_time(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed


def build_sentiment_and_event_frames(
    base: pd.DataFrame,
    news_by_code: dict[str, list[dict]],
    announcements_by_code: dict[str, list[dict]],
    *,
    lookback_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    sentiment_columns = [
        "sentiment_score",
        "attention_heat",
        "news_count_log",
        "sentiment_data_coverage",
    ]
    event_columns = [
        "event_sentiment_score",
        "announcement_count_log",
        "event_risk_flag",
        "event_data_coverage",
    ]
    sentiment = empty_factor_frame(base, sentiment_columns)
    events = empty_factor_frame(base, event_columns)
    for code, group in base.groupby("code"):
        news_items = news_by_code.get(str(code), [])
        ann_items = announcements_by_code.get(str(code), [])
        news_rows = []
        for item in news_items:
            ts = parse_news_time(item.get("time"))
            if ts is not None:
                news_rows.append((ts, item))
        ann_rows = []
        for item in ann_items:
            ts = parse_news_time(item.get("date"))
            if ts is not None:
                ann_rows.append((ts.normalize() + pd.Timedelta(hours=9), item))

        fetched_news = code in news_by_code
        fetched_anns = code in announcements_by_code
        for idx, row in group.iterrows():
            cutoff = row["signal_date"] + pd.Timedelta(hours=14, minutes=55)
            start = cutoff - pd.Timedelta(days=max(int(lookback_days), 1))
            selected_news = [item for ts, item in news_rows if start <= ts <= cutoff]
            news_texts = [f"{item.get('title', '')} {item.get('content', '')}" for item in selected_news]
            sentiment.loc[idx, "sentiment_score"] = text_sentiment_score(news_texts)
            sentiment.loc[idx, "attention_heat"] = math.log1p(len(selected_news))
            sentiment.loc[idx, "news_count_log"] = math.log1p(len(selected_news))
            sentiment.loc[idx, "sentiment_data_coverage"] = 1.0 if fetched_news else 0.0

            selected_anns = [item for ts, item in ann_rows if start <= ts <= cutoff]
            ann_texts = [f"{item.get('title', '')} {item.get('type', '')}" for item in selected_anns]
            event_score = text_sentiment_score(ann_texts)
            events.loc[idx, "event_sentiment_score"] = event_score
            events.loc[idx, "announcement_count_log"] = math.log1p(len(selected_anns))
            events.loc[idx, "event_risk_flag"] = 1.0 if event_score < 0 else 0.0
            events.loc[idx, "event_data_coverage"] = 1.0 if fetched_anns else 0.0
    return sentiment, events


def fetch_current_board_proxy(
    provider: AStockDataProvider,
    base: pd.DataFrame,
    *,
    limiter: RateLimiter,
    retries: int,
    top_boards: int = 30,
) -> tuple[pd.DataFrame, FetchStats]:
    stats = FetchStats("eastmoney_current_board_proxy")
    columns = ["current_board_strength", "current_board_main_net_yi", "current_board_hit"]
    frame = empty_factor_frame(base, columns)
    latest_date = frame["signal_date"].max()
    try:
        boards = []
        for board_type in ("industry", "concept"):
            stats.attempted += 1
            rows = call_with_retries(
                f"eastmoney_board_list {board_type}",
                lambda board_type=board_type: provider.eastmoney_board_list(board_type, page_size=500),
                limiter=limiter,
                retries=retries,
            )
            boards.extend(rows)
            stats.ok += 1
        boards = sorted(boards, key=lambda row: safe_float(row.get("change_pct")), reverse=True)[:top_boards]
        for board in boards:
            board_code = board.get("board_code")
            if not board_code:
                continue
            stats.attempted += 1
            members = call_with_retries(
                f"eastmoney_board_constituents {board_code}",
                lambda board_code=board_code: provider.eastmoney_board_constituents(board_code, page_size=500),
                limiter=limiter,
                retries=retries,
            )
            for member in members:
                code = normalize_to_code(str(member.get("code", "")))
                mask = frame["signal_date"].eq(latest_date) & frame["code"].eq(code)
                if not mask.any():
                    continue
                frame.loc[mask, "current_board_strength"] = max(
                    frame.loc[mask, "current_board_strength"].max(), safe_float(board.get("change_pct"))
                )
                frame.loc[mask, "current_board_main_net_yi"] = max(
                    frame.loc[mask, "current_board_main_net_yi"].max(), safe_float(board.get("main_net")) / 1e8
                )
                frame.loc[mask, "current_board_hit"] = 1.0
        logging.info("当前板块代理：top_boards=%s latest_date=%s", len(boards), latest_date.date())
    except Exception as exc:
        stats.add_error("current_board_proxy", exc)
    return frame, stats


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    output = frame.copy()
    output["signal_date"] = pd.to_datetime(output["signal_date"]).dt.strftime("%Y-%m-%d")
    output.to_csv(path, index=False, encoding="utf-8-sig")
    logging.info("写入 %s 行：%s", len(output), path)


def main() -> None:
    args = parse_args()
    configure_logging(args.output_dir)
    if args.request_interval < 1.0 or args.news_request_interval < 1.0 or args.capital_flow_interval < 1.0:
        raise ValueError("风控限制：外部因子请求间隔不能低于 1 秒")
    if in_continuous_market_hours(datetime.now(CN_TZ)) and not args.allow_market_hours and not args.codes:
        raise RuntimeError("当前处于A股交易时段；全市场外部因子采集已拒绝。可指定 --codes 小样本或收盘后运行。")

    base = load_base_records(args)
    provider = AStockDataProvider()
    stats: list[FetchStats] = []
    domains = set(args.domains)
    provider_limiter = RateLimiter(args.request_interval)

    hot_history: dict[pd.Timestamp, list[dict]] = {}
    if domains & {"limit_ecology", "sector_concept", "sentiment_attention", "event_disclosure"} or args.news_mode == "hot":
        hot_history, hot_stats = fetch_hot_reason_history(
            provider,
            base["signal_date"].unique(),
            limiter=provider_limiter,
            retries=args.source_retries,
        )
        stats.append(hot_stats)

    if domains & {"limit_ecology", "sector_concept"}:
        limit_frame, sector_frame = build_limit_and_sector_frames(base, hot_history)
        if "limit_ecology" in domains:
            write_csv(limit_frame, args.output_dir / "limit_ecology.csv")
        if "sector_concept" in domains:
            write_csv(sector_frame, args.output_dir / "sector_concept.csv")

    if "capital_flow" in domains:
        codes = sorted(base["code"].unique())
        flows, flow_stats = fetch_capital_flows(
            provider,
            codes,
            limiter=RateLimiter(args.capital_flow_interval),
            retries=args.source_retries,
            cooldown_every=args.cooldown_every,
            cooldown_seconds=args.cooldown_seconds,
        )
        stats.append(flow_stats)
        write_csv(build_capital_flow_frame(base, flows), args.output_dir / "capital_flow.csv")

    if domains & {"sentiment_attention", "event_disclosure"}:
        news_by_code, announcements_by_code, news_stats = fetch_news_and_events(
            provider,
            base,
            hot_history,
            mode=args.news_mode,
            max_stocks=args.news_max_stocks,
            page_size=args.news_page_size,
            ann_page_size=args.announcement_page_size,
            limiter=RateLimiter(args.news_request_interval),
            retries=args.source_retries,
            confirm_heavy_news=args.confirm_heavy_news,
        )
        stats.append(news_stats)
        sentiment_frame, event_frame = build_sentiment_and_event_frames(
            base,
            news_by_code,
            announcements_by_code,
            lookback_days=args.sentiment_lookback_days,
        )
        if "sentiment_attention" in domains:
            write_csv(sentiment_frame, args.output_dir / "sentiment_attention.csv")
        if "event_disclosure" in domains:
            write_csv(event_frame, args.output_dir / "event_disclosure.csv")

    if "current_board_proxy" in domains:
        board_frame, board_stats = fetch_current_board_proxy(
            provider,
            base,
            limiter=provider_limiter,
            retries=args.source_retries,
        )
        stats.append(board_stats)
        write_csv(board_frame, args.output_dir / "current_board_proxy.csv")

    summary = {
        "created_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "input": str(args.input),
        "window_config": str(args.window_config),
        "output_dir": str(args.output_dir),
        "domains": sorted(domains),
        "rows": int(len(base)),
        "codes": int(base["code"].nunique()),
        "dates": int(base["signal_date"].nunique()),
        "source_policy": SOURCE_POLICY_VERSION,
        "stats": [stat.__dict__ for stat in stats],
        "notes": [
            "limit_ecology/sector_concept 使用上一交易日同花顺热点题材，避免14:55后全日信息泄漏。",
            "capital_flow 使用信号日前最近一个交易日的东方财富日资金流。",
            "sentiment/event 使用可解析时间且不晚于信号日14:55的信息；代码搜索新闻还会用股票名称过滤假阳性。",
            "current_board_proxy 是当前快照代理，不建议用于历史训练回测，除非你明确接受该口径。",
        ],
    }
    (args.output_dir / "external_factor_fetch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    errors = [error for stat in stats for error in (stat.errors or [])]
    pd.DataFrame(errors).to_csv(args.output_dir / "external_factor_fetch_errors.csv", index=False, encoding="utf-8-sig")
    logging.info("外部因子生成完成：%s", args.output_dir)


if __name__ == "__main__":
    main()
