from pathlib import Path

import pandas as pd

from experiments.small_capital_quant_factor_system.quant_strategy_system import (
    StrategyConfig,
    backtest,
    datewise_percentile_score,
    prepare_ohlcv,
    select_single_stock_signals,
)


def _config() -> StrategyConfig:
    return StrategyConfig(
        strategy_name="test",
        score_threshold=0.5,
        min_cross_section_size=2,
        min_amount=0,
        transaction_cost_bps=10,
        slippage_bps=5,
        stop_loss_pct=3,
        take_profit_pct=6,
        max_trades_per_day=1,
        allow_risk_names=False,
        factor_weights_overnight={},
        factor_weights_ohlcv={"momentum_3d": 1.0, "volatility_5d": -0.5},
    )


def _ohlcv() -> pd.DataFrame:
    rows = []
    for code, base in (("000001", 10.0), ("000002", 20.0)):
        for index in range(30):
            close = base + index * (0.08 if code == "000001" else 0.02)
            rows.append(
                {
                    "code": code,
                    "date": f"2026-06-{index + 1:02d}",
                    "open": close * 0.998,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1000000 + index * 1000,
                    "amount": close * (1000000 + index * 1000),
                    "is_risk_name": 0,
                }
            )
    return pd.DataFrame(rows)


def test_prepare_ohlcv_builds_factors_and_targets():
    data, rejected = prepare_ohlcv(_ohlcv(), _config(), hold_days=1)

    assert not rejected.empty
    assert rejected["reject_reason"].str.contains("missing_future_execution_price").any()
    assert {"momentum_3d", "ma5_gap_ma10", "target_return_pct"}.issubset(data.columns)
    assert data["target_return_pct"].notna().any()


def test_scoring_selects_one_stock_per_day():
    data, _ = prepare_ohlcv(_ohlcv(), _config(), hold_days=1)
    factor_names = ["momentum_3d", "volatility_5d"]
    scored = datewise_percentile_score(data.dropna(subset=factor_names + ["target_return_pct"]), factor_names, _config().factor_weights_ohlcv)
    signals = select_single_stock_signals(scored, _config())

    assert not signals.empty
    assert signals.groupby("signal_date").size().max() == 1
    assert signals["raw_score"].min() >= _config().score_threshold


def test_backtest_compounds_full_position():
    signals = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "code": ["000001", "000002"],
            "name": ["A", "B"],
            "target_return_pct": [1.0, -0.5],
        }
    )

    trades, curve, summary = backtest(signals, _config(), initial_cash=10000)

    assert len(trades) == 2
    assert len(curve) == 2
    assert summary["trade_count"] == 2
    assert summary["final_equity"] != 10000

