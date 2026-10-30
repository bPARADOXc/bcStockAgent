# 量化因子与短线策略资料摘记

检索日期：2026-07-09。

## 采用到系统里的技术点

1. **动量/趋势**
   - 经典动量研究支持“近期强势可能延续”，但高换手会显著侵蚀收益，且动量存在崩溃风险。
   - 系统中对应：`momentum_3d`、`momentum_5d`、`ma5_gap_ma10`、`ma5_slope_3d`、隔夜模式的 MA5/MA10 斜率和差值扩张。

2. **短期反转**
   - 极短周期收益常受流动性冲击、bid-ask bounce 和临时价格压力影响，可能出现反转。
   - 系统中对应：日线 `reversal_1d`、隔夜模式的尾盘涨跌与均线偏离。

3. **量价与流动性**
   - 成交量、订单流、价差与日内收益可预测性有关；流动性差和成交冲击会影响实际可交易收益。
   - 系统中对应：量MA5/MA10、`volume_ratio_5_20`、`amount_ma5_score`、`amihud_illiquidity`。

4. **过拟合与交易成本**
   - 短线因子高换手，必须扣除成本，并用时间外样本验证。
   - 系统中对应：交易成本/滑点、Rank IC、分箱、时间序列回测、全仓单票约束。

## 主要资料

- Momentum investing overview and references: https://en.wikipedia.org/wiki/Momentum_investing
- Heston, Korajczyk, Sadka, *Intraday Patterns in the Cross-section of Stock Returns*: https://arxiv.org/abs/1005.3535
- Statistical arbitrage / short-term reversal background: https://en.wikipedia.org/wiki/Statistical_arbitrage
- Efficient-market hypothesis and weak-form caveats: https://en.wikipedia.org/wiki/Efficient-market_hypothesis

