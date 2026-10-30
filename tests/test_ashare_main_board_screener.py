from datetime import datetime, timedelta

import pytest

from tradingagents.dataflows.a_stock_data_provider import AStockDataProvider
from tradingagents.dataflows.ashare_main_board_screener import (
    AStockMainBoardScreenerConfig,
    CN_TZ,
    priority_signal,
    screen_main_board_candidates,
)


class _FakeScreenerProvider:
    def __init__(self, quotes, records_by_code):
        self.quotes = quotes
        self.records_by_code = records_by_code

    def tencent_quote(self, codes):
        return {code: self.quotes[code] for code in codes if code in self.quotes}

    def _baidu_kline_records(self, code):
        return self.records_by_code.get(code, [])

    def _eastmoney_kline_records(self, code, start_date="1900-01-01", end_date=""):
        return []

    def _sina_kline_records(self, code, datalen=800):
        return []


def _rising_records(days=30, *, volume_tail=(3000, 4200, 5600), start=None):
    start = start or datetime(2026, 5, 1)
    body_days = days - len(volume_tail)
    rows = []
    for idx in range(days):
        close = 10 + idx * 0.35
        volume = 1000 + idx * 50
        if idx >= body_days:
            volume = volume_tail[idx - body_days]
        rows.append(
            {
                "Date": (start + timedelta(days=idx)).strftime("%Y-%m-%d"),
                "Open": close - 0.1,
                "High": close + 0.2,
                "Low": close - 0.2,
                "Close": close,
                "Volume": volume,
            }
        )
    return rows


def _quote(code, *, name="样本股份", price=25.0, change_pct=4.0, vol_ratio=2.5, turnover_pct=6.0, float_mcap_yi=100.0):
    return {
        "code": code,
        "name": name,
        "price": price,
        "change_pct": change_pct,
        "vol_ratio": vol_ratio,
        "turnover_pct": turnover_pct,
        "float_mcap_yi": float_mcap_yi,
        "mcap_yi": float_mcap_yi * 1.2,
        "amount_wan": 12345,
    }


@pytest.mark.unit
def test_main_board_screener_filters_kline_and_sorts_by_priority():
    quotes = {
        "600001": _quote("600001", name="启动股份", vol_ratio=2.5, turnover_pct=6.2),
        "600002": _quote("600002", name="加速股份", vol_ratio=4.0, turnover_pct=8.0),
        "000001": _quote("000001", name="风险股份", vol_ratio=1.5, turnover_pct=6.0),
        "300001": _quote("300001", name="创业股份", vol_ratio=2.5, turnover_pct=6.0),
        "600003": _quote("600003", name="太贵股份", price=35.0, vol_ratio=2.5, turnover_pct=6.0),
    }
    records = {code: _rising_records() for code in quotes}
    provider = _FakeScreenerProvider(quotes, records)
    config = AStockMainBoardScreenerConfig(
        codes=tuple(quotes),
        quote_batch_interval=0,
        batch_size=2,
        limit=10,
    )

    payload = screen_main_board_candidates(provider, config, now=datetime(2026, 6, 8, 14, 45, tzinfo=CN_TZ))

    assert payload["summary"]["quote_count"] == 5
    assert payload["summary"]["quote_filter_count"] == 3
    assert payload["summary"]["short_term_windows"]["volume_growth_days"] == 3
    assert payload["summary"]["short_term_windows"]["kline_lookback_days"] == 45
    assert [row["code"] for row in payload["records"]] == ["600001", "600002", "000001"]
    assert [row["priority"] for row in payload["records"]] == [1, 2, 4]
    assert all(row["volume_curve_expanding"] and row["ma_upward"] for row in payload["records"])
    assert payload["records"][0]["position_label"] == "高位"


@pytest.mark.unit
def test_high_turnover_priority_is_available_when_turnover_cap_is_disabled():
    quotes = {
        "600010": _quote("600010", name="高换手股份", vol_ratio=5.5, turnover_pct=12.0),
    }
    provider = _FakeScreenerProvider(quotes, {"600010": _rising_records()})

    strict_config = AStockMainBoardScreenerConfig(codes=("600010",), quote_batch_interval=0)
    relaxed_config = AStockMainBoardScreenerConfig(codes=("600010",), quote_batch_interval=0, max_turnover_pct=None)

    strict = screen_main_board_candidates(provider, strict_config, now=datetime(2026, 6, 8, 14, 45, tzinfo=CN_TZ))
    relaxed = screen_main_board_candidates(provider, relaxed_config, now=datetime(2026, 6, 8, 14, 45, tzinfo=CN_TZ))

    assert strict["records"] == []
    assert relaxed["records"][0]["priority"] == 3
    assert relaxed["records"][0]["priority_label"] == "高换手高量比"


@pytest.mark.unit
def test_kline_volume_or_ma_failure_removes_candidate():
    quotes = {"600001": _quote("600001", name="回落股份")}
    falling_volume = _rising_records(volume_tail=(5600, 4200, 3000))
    provider = _FakeScreenerProvider(quotes, {"600001": falling_volume})
    config = AStockMainBoardScreenerConfig(codes=("600001",), quote_batch_interval=0)

    payload = screen_main_board_candidates(provider, config, now=datetime(2026, 6, 8, 14, 45, tzinfo=CN_TZ))

    assert payload["summary"]["quote_filter_count"] == 1
    assert payload["records"] == []


@pytest.mark.unit
def test_priority_signal_rule_boundaries():
    assert priority_signal(6, 2.5)[0] == 1
    assert priority_signal(8, 4)[0] == 2
    assert priority_signal(12, 5.5)[0] == 3
    assert priority_signal(6, 1.5)[0] == 4


@pytest.mark.unit
def test_provider_main_board_screener_returns_envelope(monkeypatch):
    provider = AStockDataProvider()
    current = datetime.now(CN_TZ).replace(hour=14, minute=45, second=0, microsecond=0)
    start = current - timedelta(days=35)
    quote = _quote("600001", name="启动股份", vol_ratio=2.5, turnover_pct=6.2)

    monkeypatch.setattr(provider, "tencent_quote", lambda codes: {"600001": quote})
    monkeypatch.setattr(provider, "_baidu_kline_records", lambda code: _rising_records(start=start.replace(tzinfo=None)))

    env = provider.screen_main_board_candidates(
        min_lot_amount=2000,
        max_lot_amount=3000,
        codes=["600001"],
        quote_batch_interval=0,
        volume_growth_days=3,
        ma_slope_days=3,
        kline_lookback_days=45,
    )

    assert env.status == "ok"
    assert env.source == "a_stock_main_board_screener"
    assert env.data["records"][0]["code"] == "600001"
    assert env.data["records"][0]["priority"] == 1
