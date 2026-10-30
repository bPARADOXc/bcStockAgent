# 外部因子自动生成

脚本：`fetch_external_factors.py`

它会读取已经爬好的隔夜 5 分钟实验数据，生成训练脚本可直接使用的外部因子 CSV。

## 已验证并接入的数据源

小样本验证结果：

- 腾讯行情：可返回价格、涨跌停价、市值、成交额等。
- 同花顺热点题材：历史日期可返回热点/涨停题材，适合做上一交易日题材生态和涨停生态。
- 东方财富 120 日资金流：可返回个股历史主力/大单资金流，适合做滞后资金流因子。
- 东方财富新闻：可返回个股相关新闻，但裸搜代码会有假阳性，所以脚本会用股票名再过滤。
- 巨潮公告：可返回个股公告，适合做事件/公告情绪因子。
- 东方财富板块列表/成分股：当前快照可用，已补进 provider；但默认不用于历史训练，避免当前快照污染历史回测。

## 先小样本验证

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/fetch_external_factors.py \
  --input experiments/ashare_overnight_5m/data/ashare_overnight_5m.sqlite3 \
  --codes 600000,000001 \
  --start-date 2026-06-10 \
  --end-date 2026-06-17 \
  --news-mode all \
  --news-max-stocks 2 \
  --output-dir experiments/small_capital_quant_factor_system/my_factors_probe
```

## 四个月数据对应的正式外部因子

在四个月主数据爬完后运行：

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/fetch_external_factors.py \
  --input experiments/small_capital_quant_factor_system/data_4m/ashare_overnight_5m.sqlite3 \
  --window-config experiments/small_capital_quant_factor_system/data_4m/training_window.json \
  --output-dir experiments/small_capital_quant_factor_system/my_factors_4m
```

默认会生成：

- `limit_ecology.csv`
- `sector_concept.csv`
- `capital_flow.csv`
- `sentiment_attention.csv`
- `event_disclosure.csv`
- `external_factor_fetch_summary.json`
- `external_factor_fetch_errors.csv`

默认 `news-mode=hot`，只对同花顺热点题材命中的股票拉新闻/公告，控制请求量。若要全市场新闻/公告，需要显式确认：

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/fetch_external_factors.py \
  --input experiments/small_capital_quant_factor_system/data_4m/ashare_overnight_5m.sqlite3 \
  --window-config experiments/small_capital_quant_factor_system/data_4m/training_window.json \
  --news-mode all \
  --confirm-heavy-news \
  --output-dir experiments/small_capital_quant_factor_system/my_factors_4m_full_news
```

这会非常慢，不建议第一次直接跑。

## 训练时接入

```bash
conda run -n bcstock python experiments/small_capital_quant_factor_system/train_walk_forward_strategy.py \
  --input experiments/small_capital_quant_factor_system/data_4m/ashare_overnight_5m.sqlite3 \
  --window-config experiments/small_capital_quant_factor_system/data_4m/training_window.json \
  --aux-factor-csv experiments/small_capital_quant_factor_system/my_factors_4m/limit_ecology.csv \
  --aux-factor-csv experiments/small_capital_quant_factor_system/my_factors_4m/sector_concept.csv \
  --aux-factor-csv experiments/small_capital_quant_factor_system/my_factors_4m/capital_flow.csv \
  --aux-factor-csv experiments/small_capital_quant_factor_system/my_factors_4m/sentiment_attention.csv \
  --aux-factor-csv experiments/small_capital_quant_factor_system/my_factors_4m/event_disclosure.csv \
  --output-dir experiments/small_capital_quant_factor_system/results_4m_walk_forward_external
```

## 防泄漏口径

- 涨停/题材生态：使用上一交易日的同花顺热点题材，作为当前信号日 09:00 前已知信息。
- 资金流：使用信号日前最近一个交易日的东方财富日资金流。
- 新闻/公告：只使用不晚于信号日 14:55 的信息；新闻还会用股票名过滤代码假阳性。
- 当前板块快照：只作为当前代理，默认不用于历史训练回测。

## 风控

- 默认请求间隔不低于 1 秒。
- 全市场新闻/公告必须加 `--confirm-heavy-news`。
- 交易时段全市场采集默认拒绝；小样本 `--codes` 可以跑。
- 中间错误会记录到 `external_factor_fetch_errors.csv`，不会静默吞掉。
