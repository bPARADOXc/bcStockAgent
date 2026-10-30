from datetime import timedelta

import pandas as pd

from experiments.ashare_overnight_5m.analyze_ma_relationship import (
    FEATURE_TIMES,
    TARGET_TIMES,
    clean_records,
    engineer_features,
    split_by_date,
)
from experiments.ashare_overnight_5m.fetch_dataset import SOURCE_POLICY_VERSION


def _sample_row(code: str = "000001", quality_ok: int = 1) -> dict:
    row = {
        "code": code,
        "name": "样本",
        "is_risk_name": 0,
        "signal_date": "2026-06-01",
        "next_trade_date": "2026-06-02",
        "signal_close": 10.6,
        "afternoon_1500_close": 10.6,
        "quality_ok": quality_ok,
        "adjustment": "none",
        "source_policy": SOURCE_POLICY_VERSION,
    }
    for index, bar_time in enumerate(FEATURE_TIMES):
        row[f"afternoon_{bar_time}_close"] = 10.1 + index * 0.1
        row[f"afternoon_{bar_time}_price_ma5"] = 10.0 + index * 0.1
        row[f"afternoon_{bar_time}_price_ma10"] = 10.0
        row[f"afternoon_{bar_time}_price_ma60"] = 9.5 + index * 0.01
        row[f"afternoon_{bar_time}_volume_ma5"] = 1000 + index * 100
        row[f"afternoon_{bar_time}_volume_ma10"] = 1000
    for bar_time in TARGET_TIMES:
        row[f"next_{bar_time}_close"] = 11.0
    return row


def test_cleaning_rejects_bad_crawler_quality_without_mutating_good_row():
    raw = pd.DataFrame([_sample_row("000001", 1), _sample_row("000002", 0)])

    clean, rejected, summary = clean_records(raw, include_risk_names=False)

    assert clean["code"].tolist() == ["000001"]
    assert rejected["code"].tolist() == ["000002"]
    assert "crawler_quality_not_ok" in rejected.iloc[0]["reject_reason"]
    assert summary["input_rows"] == 2


def test_feature_engineering_captures_ma_cross_slope_and_target():
    clean, _, _ = clean_records(pd.DataFrame([_sample_row()]), include_risk_names=False)

    featured, feature_columns = engineer_features(clean, big_rise_pct=1.0, cost_bps=20)
    row = featured.iloc[0]

    assert "ma5_slope_pct_per_bar" in feature_columns
    assert row["ma5_slope_pct_per_bar"] > 0
    assert row["ma5_gap_change_pp"] > 0
    assert row["ma5_cross_up"] == 1
    assert row["target_return_pct"] > 0
    assert row["target_net_return_pct"] < row["target_return_pct"]


def test_time_split_uses_last_dates_for_validation():
    start = pd.Timestamp("2026-05-01")
    frame = pd.DataFrame(
        {
            "signal_date": [start + timedelta(days=index) for index in range(12)],
            "value": range(12),
        }
    )

    train, validation, validation_dates = split_by_date(frame, validation_days=4)

    assert len(train) == 8
    assert len(validation) == 4
    assert list(validation["value"]) == [8, 9, 10, 11]
    assert validation_dates[0] == pd.Timestamp("2026-05-09")

