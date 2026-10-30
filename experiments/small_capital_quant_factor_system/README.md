# 小资金单股票短线量化因子系统

这个实验系统面向“小资金、每天最多全仓一只股票、短周期持有”的场景。它不是交易建议生成器，而是一个可复现的研究框架：把价量因子转成横截面分数，输出当天最值得跟踪的一只候选，同时生成回测、因子IC、分箱表现和风险报告。

## 运行

默认直接使用前一个实验目录下的隔夜5分钟 SQLite：

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/quant_strategy_system.py
```

输出在：

```text
experiments/small_capital_quant_factor_system/results/
```

也可以指定普通日线 OHLCV CSV：

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/quant_strategy_system.py \
  --input path/to/daily_ohlcv.csv \
  --input-kind ohlcv_csv \
  --output-dir experiments/small_capital_quant_factor_system/results_daily
```

CSV 至少需要：`code,date,open,high,low,close,volume`，最好还有 `amount,name,is_risk_name`。

## 输出

- `latest_strategy.csv`：最后一个信号日的全仓单票候选和因子解释。
- `signals.csv`：每天分数最高的候选。
- `trades.csv`：按单股票全仓执行的回测交易。
- `equity_curve.csv`：资金曲线。
- `factor_ic.csv`：每日因子Rank IC。
- `factor_bins.csv`：因子分箱收益、胜率。
- `rejected_rows.csv`：明显有误或不满足风控的数据。
- `report.md`：中文摘要报告。

## 因子逻辑

隔夜5分钟模式主要看：

- MA5/MA10相对位置、差值扩张、斜率、加速度、波动。
- 成交量MA5/MA10相对位置、扩张和斜率。
- 价格相对MA60的位置，用作趋势背景。
- 14:30–14:55尾盘价格变化。

日线模式主要看：

- 3/5日动量、1日反转。
- MA5/MA10、MA10/MA20趋势。
- MA5斜率、20日区间位置、20日突破。
- 量能放大、成交额、短期波动和 Amihud 式流动性冲击。

## 风控

- 默认使用 `adaptive_ic`：每个交易日只用此前若干天的Rank IC决定因子方向和权重；也可用 `--weight-mode config` 固定配置权重。
- 每天最多一只，分数低于阈值则空仓。
- 默认排除 ST/*ST/退市整理名称。
- 默认要求横截面样本数不少于 80。
- 成本默认 20bp，滑点默认 10bp。
- 报告会给出最大回撤、胜率、平均收益和交易覆盖率。
- 若当前因子组合历史均值为负、总收益为负或回撤过深，风险总闸会关闭，最新候选只保留为观察名单。
- 原始数据不会被修改，清洗出来的异常样本单独输出。

## 资料依据

实现参考了动量、短期反转、日内周期性、交易成本和弱式有效市场相关文献。详见 `SOURCES.md`。这里的重点不是追求复杂模型，而是让因子、阈值、收益标签和风控都能审计。

