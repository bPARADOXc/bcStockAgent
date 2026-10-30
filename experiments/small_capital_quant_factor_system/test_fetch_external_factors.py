import pandas as pd

from experiments.small_capital_quant_factor_system.factor_domains import augment_factor_domains
from experiments.small_capital_quant_factor_system.fetch_external_factors import (
    build_capital_flow_frame,
    build_limit_and_sector_frames,
    build_sentiment_and_event_frames,
)


def _base() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-07-08", "2026-07-08", "2026-07-09", "2026-07-09"]),
            "code": ["600000", "000001", "600000", "000001"],
            "name": ["浦发银行", "平安银行", "浦发银行", "平安银行"],
        }
    )


def test_limit_sector_frames_use_previous_signal_date():
    hot_history = {
        pd.Timestamp("2026-07-08"): [
            {"代码": "600000", "题材归因": "银行+高股息", "涨幅%": 10.0, "换手率%": 2.0, "成交额": 10000, "大单净量": 1.2}
        ]
    }

    limit_frame, sector_frame = build_limit_and_sector_frames(_base(), hot_history)

    latest = limit_frame.loc[limit_frame["signal_date"].eq(pd.Timestamp("2026-07-09"))].set_index("code")
    assert latest.loc["600000", "limit_up_hit"] == 1.0
    assert latest.loc["000001", "limit_up_hit"] == 0.0
    assert latest.loc["600000", "market_limit_up_count"] == 1.0

    sector_latest = sector_frame.loc[sector_frame["signal_date"].eq(pd.Timestamp("2026-07-09"))].set_index("code")
    assert sector_latest.loc["600000", "concept_heat"] > 0
    assert sector_latest.loc["000001", "stock_rank_in_sector"] == 999.0


def test_capital_flow_uses_strictly_lagged_daily_record():
    flows = {
        "600000": [
            {"date": "2026-07-08", "main_net": 100.0, "small_net": -40.0, "mid_net": -60.0, "large_net": 80.0, "super_net": 20.0},
            {"date": "2026-07-09", "main_net": -999.0, "small_net": 0.0, "mid_net": 0.0, "large_net": 0.0, "super_net": 0.0},
        ]
    }

    frame = build_capital_flow_frame(_base(), flows)
    row = frame.loc[(frame["signal_date"].eq(pd.Timestamp("2026-07-09"))) & frame["code"].eq("600000")].iloc[0]

    assert row["main_net_inflow_yi"] > 0
    assert row["capital_flow_data_coverage"] == 1.0


def test_sentiment_event_frames_filter_by_cutoff():
    news = {
        "600000": [
            {"title": "浦发银行中标合作项目", "content": "增长", "time": "2026-07-09 14:30:00"},
            {"title": "浦发银行减持传闻", "content": "风险", "time": "2026-07-09 15:30:00"},
        ]
    }
    anns = {"600000": [{"title": "浦发银行回购公告", "type": "", "date": "2026-07-09"}]}

    sentiment, events = build_sentiment_and_event_frames(_base(), news, anns, lookback_days=2)
    row = sentiment.loc[(sentiment["signal_date"].eq(pd.Timestamp("2026-07-09"))) & sentiment["code"].eq("600000")].iloc[0]
    event_row = events.loc[(events["signal_date"].eq(pd.Timestamp("2026-07-09"))) & events["code"].eq("600000")].iloc[0]

    assert row["sentiment_score"] > 0
    assert row["news_count_log"] > 0
    assert event_row["event_sentiment_score"] > 0


def test_sparse_aux_csv_does_not_drop_unmatched_rows(tmp_path):
    base = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-07-09", "2026-07-09"]),
            "code": ["600000", "000001"],
            "late_price_return": [0.1, 0.2],
        }
    )
    aux = pd.DataFrame(
        {
            "signal_date": ["2026-07-09"],
            "code": ["600000"],
            "available_at": ["2026-07-09 14:30:00"],
            "sentiment_score": [0.8],
        }
    )
    path = tmp_path / "sentiment_attention.csv"
    aux.to_csv(path, index=False)

    result = augment_factor_domains(base, input_kind="overnight_sqlite", aux_factor_csvs=[path])
    values = result.frame.set_index("code")["sentiment_attention_sentiment_score"]

    assert values.loc["600000"] == 0.8
    assert values.loc["000001"] == 0.0
