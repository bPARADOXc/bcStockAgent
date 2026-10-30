from datetime import date

import pandas as pd

from experiments.small_capital_quant_factor_system.fetch_training_data_4m import build_window, shift_months
from experiments.small_capital_quant_factor_system.quant_strategy_system import StrategyConfig
from experiments.small_capital_quant_factor_system.train_walk_forward_strategy import (
    choose_threshold,
    score_with_weights,
    split_train_backtest,
    train_factor_weights,
)


def _config() -> StrategyConfig:
    return StrategyConfig(
        strategy_name="walk_forward_test",
        score_threshold=0.5,
        min_cross_section_size=30,
        min_amount=0,
        transaction_cost_bps=0,
        slippage_bps=0,
        stop_loss_pct=3,
        take_profit_pct=6,
        max_trades_per_day=1,
        allow_risk_names=False,
        factor_weights_overnight={"good_factor": 1.0, "bad_factor": 1.0},
        factor_weights_ohlcv={},
    )


def _synthetic_factor_rows() -> pd.DataFrame:
    rows = []
    signal_dates = pd.bdate_range("2026-03-10", periods=20)
    for day_index, signal_date in enumerate(signal_dates):
        for code_index in range(40):
            strength = code_index / 39
            rows.append(
                {
                    "signal_date": signal_date,
                    "entry_date": signal_date,
                    "exit_date": signal_date + pd.Timedelta(days=1),
                    "code": f"{code_index:06d}",
                    "name": f"S{code_index}",
                    "good_factor": strength + day_index * 0.0001,
                    "bad_factor": 1 - strength,
                    "target_return_pct": strength * 2.0 - 0.5,
                    "entry_price": 10.0,
                    "exit_price": 10.0 * (1 + (strength * 2.0 - 0.5) / 100),
                    "amount_proxy": 1000000,
                }
            )
    return pd.DataFrame(rows)


def test_four_month_window_uses_calendar_months():
    assert shift_months(date(2026, 3, 31), -1) == date(2026, 2, 28)

    window = build_window(date(2026, 7, 9), train_months=3, backtest_months=1)

    assert window["start_date"] == "2026-03-10"
    assert window["train_end"] == "2026-06-09"
    assert window["backtest_start"] == "2026-06-10"
    assert window["backtest_end"] == "2026-07-09"


def test_walk_forward_training_learns_direction_and_threshold():
    data = _synthetic_factor_rows()
    window = {
        "train_start": "2026-03-10",
        "train_end": "2026-03-30",
        "backtest_start": "2026-03-31",
        "backtest_end": "2026-04-06",
    }
    _, train, backtest_slice = split_train_backtest(data, window)
    weights, weights_table, status = train_factor_weights(
        train,
        ["good_factor", "bad_factor"],
        _config().factor_weights_overnight,
        min_ic_days=3,
        min_abs_ic=0.001,
    )

    assert status == "trained_rank_ic"
    assert weights["good_factor"] > 0
    assert weights["bad_factor"] < 0
    assert set(weights_table["factor"]) == {"good_factor", "bad_factor"}

    train_scored = score_with_weights(train, ["good_factor", "bad_factor"], weights, status)
    threshold, search, train_signals, _, train_summary = choose_threshold(
        train_scored,
        _config(),
        thresholds=[0.50, 0.60, 0.70, 0.80],
        min_train_trades=3,
        initial_cash=10000,
    )

    assert threshold in {0.50, 0.60, 0.70, 0.80}
    assert not search.empty
    assert not train_signals.empty
    assert train_summary["trade_count"] > 0

    backtest_scored = score_with_weights(backtest_slice, ["good_factor", "bad_factor"], weights, status)
    assert backtest_scored["raw_score"].notna().all()
