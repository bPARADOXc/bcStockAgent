# 四个月训练/回测流程

目标：用之前的隔夜 5 分钟爬虫拉取连续四个月数据，前三个月只训练，最后一个月只做样本外回测。

## 1. 拉取连续四个月数据

这个脚本只是 `experiments/ashare_overnight_5m/fetch_dataset.py` 的包装。原爬虫的功能、断点续跑、熔断、空数据处理、东方财富最后兜底和风控默认值都保留。

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/fetch_training_data_4m.py \
  --full-market \
  --end-date 2026-07-09 \
  --output-dir experiments/small_capital_quant_factor_system/data_4m
```

小样本或命令预检：

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/fetch_training_data_4m.py \
  --codes 600000,000001 \
  --end-date 2026-07-09 \
  --output-dir experiments/small_capital_quant_factor_system/data_4m_sample \
  --dry-run
```

输出：

- `ashare_overnight_5m.sqlite3`
- `ashare_overnight_5m.csv`
- `training_window.json`

`training_window.json` 会固定写入 `train_start`、`train_end`、`backtest_start`、`backtest_end`，避免训练时重新手工切窗口。

## 2. 训练并回测

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/train_walk_forward_strategy.py \
  --input experiments/small_capital_quant_factor_system/data_4m/ashare_overnight_5m.sqlite3 \
  --window-config experiments/small_capital_quant_factor_system/data_4m/training_window.json \
  --output-dir experiments/small_capital_quant_factor_system/results_4m_walk_forward
```

训练逻辑：

- 只用前三个月训练期的 Rank IC 学习因子方向和权重。
- 只在前三个月训练期搜索分数阈值。
- 最后一个月回测期固定使用训练得到的权重和阈值。
- 若训练期或样本外回测期收益为负、没有交易或回撤过大，风险总闸关闭，候选只作为观察。

主要输出：

- `trained_factor_model.json`：训练得到的权重、阈值、窗口和风险总闸状态。
- `trained_factor_weights.csv`：每个因子的训练期 Rank IC 与最终权重。
- `threshold_search_train.csv`：训练期阈值搜索表。
- `train_signals.csv` / `backtest_signals.csv`：训练期与样本外回测信号。
- `backtest_trades.csv` / `backtest_equity_curve.csv`：样本外交易和权益曲线。
- `latest_backtest_candidates.csv`：回测期最后一个交易日的候选解释。
- `report.md`：中文报告。

## 3. 采用的权威训练原则

实现参考了 scikit-learn 官方文档中的模型评估与防泄漏原则，但没有依赖 scikit-learn 包，因为当前 `bcstock` 环境未安装它。

- TimeSeriesSplit / 时间序列交叉验证：训练集必须位于测试集之前，避免用未来预测过去。
- Common pitfalls / Data leakage：预处理、调参、特征选择等任何拟合步骤都不能在切分前使用全量数据。
- Pipeline 思想：工程上应把拟合步骤限制在训练集内；本项目用 pandas/numpy 实现相同纪律。

参考链接：

- https://scikit-learn.org/stable/modules/cross_validation.html#time-series-split
- https://scikit-learn.org/stable/common_pitfalls.html#data-leakage
- https://scikit-learn.org/stable/modules/generated/sklearn.pipeline.Pipeline.html

## 4. 风控提醒

全市场四个月 5 分钟数据会跑很久。建议：

- 收盘后运行，不要在交易时段全市场请求。
- 保持默认东方财富最后兜底，不要把请求间隔调得太激进。
- 先用 `--codes` 做小样本预检，再跑 `--full-market`。
- 如果中断，使用同一命令续跑即可。
