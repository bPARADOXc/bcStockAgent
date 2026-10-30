from datetime import date, datetime, timedelta
import sqlite3

import pandas as pd

from experiments.ashare_overnight_5m.fetch_dataset import (
    MinuteSourceChain,
    NoDataError,
    Stock,
    build_stock_day_records,
    enrich_rolling_indicators,
    open_database,
)


def _session_times(day: date) -> list[datetime]:
    morning = pd.date_range(f"{day} 09:35", f"{day} 11:30", freq="5min")
    afternoon = pd.date_range(f"{day} 13:05", f"{day} 15:00", freq="5min")
    return [value.to_pydatetime() for value in morning.append(afternoon)]


def _bars(days: list[date]) -> list[dict]:
    rows = []
    counter = 1
    for day in days:
        for timestamp in _session_times(day):
            rows.append({"timestamp": timestamp, "close": float(counter), "volume": float(counter * 100)})
            counter += 1
    return rows


def test_rolling_indicators_continue_across_sessions():
    day1 = date(2026, 6, 1)
    day2 = day1 + timedelta(days=1)
    frame = enrich_rolling_indicators(_bars([day1, day2]))

    first_day2 = frame.loc[frame["timestamp"] == pd.Timestamp("2026-06-02 09:35")].iloc[0]
    assert first_day2["price_ma5"] == sum(range(45, 50)) / 5
    assert first_day2["volume_ma5"] == (sum(range(45, 50)) / 5) * 100


def test_builds_one_signal_day_record_with_exact_next_market_day():
    warmup = date(2026, 6, 1)
    signal = date(2026, 6, 2)
    target = date(2026, 6, 3)
    records = build_stock_day_records(
        Stock("600000", "浦发银行"),
        _bars([warmup, signal, target]),
        [signal.isoformat(), target.isoformat()],
        signal,
        signal,
    )

    assert len(records) == 1
    row = records[0]
    assert row["signal_date"] == "2026-06-02"
    assert row["next_trade_date"] == "2026-06-03"
    assert row["signal_close"] == 96.0
    assert row["afternoon_1430_price_ma60"] is not None
    assert row["next_0940_close"] == 98.0
    assert row["next_1005_close"] == 103.0
    assert row["quality_ok"] == 1


def test_suspension_does_not_jump_to_later_resume_day():
    signal = date(2026, 6, 2)
    suspended_target = date(2026, 6, 3)
    resumed = date(2026, 6, 4)
    records = build_stock_day_records(
        Stock("600001", "样本股份"),
        _bars([date(2026, 6, 1), signal, resumed]),
        [signal.isoformat(), suspended_target.isoformat(), resumed.isoformat()],
        signal,
        signal,
    )

    assert records[0]["next_trade_date"] == suspended_target.isoformat()
    assert records[0]["next_0940_close"] is None
    assert records[0]["quality_ok"] == 0


def _chain_without_network() -> MinuteSourceChain:
    chain = object.__new__(MinuteSourceChain)
    chain._mootdx_client = object()
    chain.source_retries = 1
    return chain


def test_source_priority_stops_after_mootdx_success():
    chain = _chain_without_network()
    calls = []
    chain._fetch_mootdx = lambda code, start, end: calls.append("mootdx") or _bars([start])
    chain._fetch_sina = lambda code, start, end: calls.append("sina") or _bars([start])
    chain._fetch_eastmoney_last = lambda code, start, end: calls.append("eastmoney") or _bars([start])

    result = chain.fetch("600000", date(2026, 6, 1), date(2026, 6, 2))

    assert result.source == "mootdx_tdx_5m"
    assert result.adjustment == "none"
    assert calls == ["mootdx"]


def test_eastmoney_is_called_only_after_mootdx_and_sina():
    chain = _chain_without_network()
    calls = []
    chain._fetch_mootdx = lambda code, start, end: calls.append("mootdx") or []

    def no_sina(code, start, end):
        calls.append("sina")
        raise NoDataError("新浪覆盖不足")

    chain._fetch_sina = no_sina
    chain._fetch_eastmoney_last = lambda code, start, end: calls.append("eastmoney") or _bars([start])

    result = chain.fetch("600000", date(2026, 6, 1), date(2026, 6, 2))

    assert result.source == "eastmoney_5m_last_resort"
    assert calls == ["mootdx", "sina", "eastmoney"]


def test_existing_fetch_status_schema_is_migrated(tmp_path):
    database = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE fetch_status (
            code TEXT PRIMARY KEY,
            coverage_start TEXT NOT NULL,
            coverage_end TEXT NOT NULL,
            status TEXT NOT NULL,
            record_count INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.close()

    migrated = open_database(database)
    columns = {row[1] for row in migrated.execute("PRAGMA table_info(fetch_status)")}
    migrated.close()

    assert "source_policy" in columns
