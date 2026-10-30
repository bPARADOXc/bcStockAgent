# 多域因子体系

当前策略已经从单纯尾盘技术因子扩展为多域候选因子库。原则是：能从现有行情数据稳定计算的因子直接内置；需要外部数据源的因子通过 `--aux-factor-csv` 接入，并用训练期 IC 自动筛选。

## 内置因子

### 技术 / 尾盘价量

- `ma5_gap_ma10_1455`
- `ma5_gap_change`
- `ma5_slope`
- `ma10_slope`
- `ma5_acceleration`
- `ma5_volatility`
- `price_gap_ma60_1455`
- `late_price_return`
- `volume_gap_ma5_ma10_1455`
- `volume_gap_change`
- `volume_ma5_slope`

### 市场状态 / 横截面相对强弱

- `stock_vs_market_late_return`
- `regime_adjusted_late_return`
- `ma5_slope_vs_market`
- `regime_adjusted_ma5_slope`
- `volume_gap_change_vs_market`
- `regime_adjusted_volume_flow`
- `daily_return_vs_market`
- `regime_adjusted_momentum_3d`

这些因子避免直接使用未来收益。旧数据里的 `market_regime_return` 是诊断列，来自未来目标收益，代码已禁止把它放入因子配置。

### 流动性 / 微结构代理

- `tail_close_volatility`
- `tail_intraday_drawdown_proxy`
- `liquidity_tail_volume_ma5_log`
- `liquidity_tail_volume_spike`
- `amount_score_vs_market`
- `volatility_5d_vs_market`

### 涨跌停生态代理

如果数据里有 `previous_close` / `prev_close`，或日线模式可计算前收，则会生成：

- `limit_up_distance_pct`
- `limit_down_distance_pct`
- `near_limit_up_proxy`
- `near_limit_down_proxy`

这些按主板非 ST 的 10% 涨跌停近似处理。

## 外部 CSV 因子

命令示例：

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/train_walk_forward_strategy.py \
  --input experiments/small_capital_quant_factor_system/data_4m/ashare_overnight_5m.sqlite3 \
  --window-config experiments/small_capital_quant_factor_system/data_4m/training_window.json \
  --aux-factor-csv experiments/small_capital_quant_factor_system/my_factors/sentiment_attention.csv \
  --aux-factor-csv experiments/small_capital_quant_factor_system/my_factors/sector_concept.csv \
  --output-dir experiments/small_capital_quant_factor_system/results_4m_walk_forward
```

### CSV 连接规则

支持这些键：

- `date` / `signal_date` / `trade_date`
- `code` / `symbol` / `ts_code`
- `sector` / `industry` / `concept`
- `available_at`

如果存在 `available_at`：

- 隔夜 5 分钟模式只接受 `signal_date 14:55:00` 前已经可见的数据。
- 日线 OHLCV 模式只接受 `signal_date 23:59:59` 前已经可见的数据。

如果没有 `available_at`，系统会假设该 CSV 的数据在信号时点前已经可见；这时需要你保证数据口径没有未来函数。

### 列名规则

系统会把文件名作为命名空间。例如：

- 文件：`sentiment_attention.csv`
- 原始列：`sentiment_score`
- 入模列：`sentiment_attention_sentiment_score`

默认配置已经给这些外部候选因子预留权重：

- 情绪/注意力：`sentiment_attention_sentiment_score`、`sentiment_attention_attention_heat`、`sentiment_attention_news_count_log`
- 板块/概念：`sector_concept_sector_strength`、`sector_concept_concept_heat`、`sector_concept_stock_rank_in_sector`
- 涨跌停生态：`limit_ecology_limit_up_count_in_sector`、`limit_ecology_broken_limit_rate`
- 资金流：`capital_flow_main_net_inflow_ratio`、`capital_flow_large_order_net_inflow_ratio`
- 事件公告：`event_disclosure_event_sentiment_score`
- 盘口微结构：`microstructure_order_imbalance`、`microstructure_bid_ask_spread_bp`

可以参考 `aux_factor_template.csv`。

## 训练筛选

外部因子不会天然被相信。训练脚本会：

1. 在前三个月训练期计算每个因子的每日 Rank IC。
2. IC 样本天数不够或绝对值太弱的因子权重归零。
3. 只用训练期搜索分数阈值。
4. 最后一个月固定权重和阈值做样本外回测。

这保证了“考虑更多因子”，但不等于“盲目增加复杂度”。
