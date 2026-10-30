import pandas as pd

from experiments.small_capital_quant_factor_system.factor_domains import (
    augment_factor_domains,
    available_factor_names,
)


def test_builtin_domains_add_market_and_liquidity_factors():
    frame = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-07-09", "2026-07-09", "2026-07-09"]),
            "code": ["600000", "000001", "000002"],
            "late_price_return": [1.0, -0.5, 0.2],
            "ma5_slope": [0.3, -0.1, 0.05],
            "volume_gap_change": [0.2, -0.3, 0.1],
            "afternoon_1430_close": [10.0, 20.0, 30.0],
            "afternoon_1435_close": [10.1, 19.9, 30.1],
            "afternoon_1440_close": [10.2, 19.8, 30.2],
            "afternoon_1445_close": [10.3, 19.7, 30.1],
            "afternoon_1450_close": [10.4, 19.8, 30.3],
            "afternoon_1455_close": [10.5, 19.9, 30.4],
            "afternoon_1455_volume_ma5": [1000, 2000, 3000],
            "afternoon_1455_volume_ma10": [900, 2100, 2500],
        }
    )

    result = augment_factor_domains(frame, input_kind="overnight_sqlite")

    assert {"stock_vs_market_late_return", "regime_adjusted_volume_flow", "liquidity_tail_volume_spike"}.issubset(
        result.frame.columns
    )
    assert not result.metadata.empty


def test_auxiliary_factor_csv_respects_available_at_cutoff(tmp_path):
    base = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-07-09", "2026-07-09"]),
            "code": ["600000", "000001"],
            "late_price_return": [0.1, 0.2],
        }
    )
    aux = pd.DataFrame(
        {
            "signal_date": ["2026-07-09", "2026-07-09", "2026-07-09"],
            "code": ["600000", "000001", "000001"],
            "available_at": ["2026-07-09 14:30:00", "2026-07-09 15:30:00", "2026-07-09 14:20:00"],
            "sentiment_score": [0.7, 0.9, -0.2],
        }
    )
    path = tmp_path / "sentiment_attention.csv"
    aux.to_csv(path, index=False)

    result = augment_factor_domains(base, input_kind="overnight_sqlite", aux_factor_csvs=[path])

    values = result.frame.set_index("code")["sentiment_attention_sentiment_score"]
    assert values.loc["600000"] == 0.7
    assert values.loc["000001"] == -0.2
    assert available_factor_names(result.frame, {"sentiment_attention_sentiment_score": 1.0}) == [
        "sentiment_attention_sentiment_score"
    ]
