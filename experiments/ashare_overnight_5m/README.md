# A股主板隔夜 5 分钟实验数据

这个目录只负责拉取并整理实验输入，不执行交易，也不发送委托。

## 一行记录的口径

每行由 `code + signal_date` 唯一确定：

- `signal_close`：信号日 15:00 的前复权 5 分钟收盘价。
- `afternoon_1430` 至 `afternoon_1500`：信号日 14:30、14:35、…、15:00 的 5 分钟收盘价、价格 MA5/MA10/MA60、成交量 MA5/MA10。
- `next_0940_close` 至 `next_1005_close`：下一**市场交易日** 09:40、09:45、09:50、09:55、10:00、10:05 的 5 分钟收盘价。
- `quality_ok` / `quality_flags`：精确时点缺失、均线历史不足等数据质量标记。停牌时不会把“下一次复牌日”误当成“下一交易日”。

价格均线和成交量均线都在连续的 5 分钟序列上滚动，跨午休和隔夜延续，不按自然日清零。成交量单位为股；为避免多源复权口径污染，所有价格统一为不复权口径。

分钟数据优先级固定为 `mootdx/通达信 → 新浪 → 东方财富最后兜底`；交易日历优先新浪，东方财富最后兜底。新浪超过其 1023 根历史上限时不会与其他源拼接，而是整只股票降级。股票池仍使用腾讯批量报价。

## 风控设计

- 全市场运行必须显式传 `--full-market`，避免误触发数千次请求。
- 默认单线程，东方财富请求间隔不低于 1 秒，默认 1.8 秒；每 100 只股票额外冷却 20 秒。
- A股连续竞价时段默认禁止全市场拉取；确有需要才传 `--allow-market-hours`。
- 连续失败达到阈值后自动熔断。
- 永久空数据记为 `no_data`，不计入熔断；502/503/504 等基础设施错误按指数退避重试。
- `mootdx` 未配置节点时只顺序探测最多 3 个包内节点，不运行全量并发测速。
- 每只股票完成后立即提交 SQLite，支持 `Ctrl+C` 后用同一命令断点续跑。
- 当前股票池来自腾讯实时报价，因此存在“当前股票池/退市样本缺失”的幸存者偏差；`is_risk_name` 会标记 ST、*ST、退市整理名称，但默认不删除它们。

## 先做小样本

在仓库根目录执行：

```bash
conda run -n bcstock python experiments/ashare_overnight_5m/fetch_dataset.py \
  --codes 600000,000001 \
  --start-date 2026-05-18 \
  --end-date 2026-06-18
```

只检查股票池、不请求分钟线：

```bash
conda run -n bcstock python experiments/ashare_overnight_5m/fetch_dataset.py --full-market --dry-run
```

确认小样本和股票池后，再在非交易时段运行全市场：

```bash
conda run -n bcstock python experiments/ashare_overnight_5m/fetch_dataset.py --full-market
```

默认输出：

- `data/ashare_overnight_5m.sqlite3`：主存储和断点状态。
- `data/ashare_overnight_5m.csv`：便于后续 pandas/回测读取的宽表。
- `data/fetch.log`：运行日志。

常用参数可用 `python experiments/ashare_overnight_5m/fetch_dataset.py --help` 查看。全市场默认包含主板 ST/*ST；若实验明确不需要，可增加 `--exclude-risk-names`。

## 均线关系实验

爬取结束后，在仓库根目录运行：

```bash
conda run -n bcstock python experiments/ashare_overnight_5m/analyze_ma_relationship.py
```

实验只使用 14:30–14:55 已知信息，主标签是次日 09:55、10:00、10:05 均价相对信号日 14:55 价格的收益。它会分析 MA5/MA10 的相对位置、斜率、加速度、波动、上穿/下穿，成交量 MA5/MA10 的扩张和斜率，并把 MA60 作为趋势辅助。

默认将最后 6 个交易日作为时间外验证集，原始数据库不会被修改。明显错误、缺失值、非当前数据策略、异常收益以及默认排除的 ST 样本会写入带原因的拒绝清单。

主要输出位于 `analysis_results/`：

- `report.md`：最可能上涨、最可能涨得多的稳健规则及边界说明。
- `recommendations.csv`：训练和验证均优于基线的最终规则。
- `univariate_bins.csv`：每项特征五分位的收益、胜率和大涨概率。
- `rules_discovered_train.csv` / `rules_time_validation.csv`：规则发现和时间外验证明细。
- `modeling_dataset.csv.gz` / `rejected_rows.csv.gz`：清洗后的建模表及带拒绝原因的异常样本。

需要把 ST 纳入独立敏感性实验时使用 `--include-risk-names`，不建议与普通主板样本直接混为主结论。
