# bcStockAgent A 股使用指南

本仓库是 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 的 A 股衍生版本。功能变化、安装和独立规则筛选工具入口见[主 README](../README.md)。以下命令均从仓库根目录执行。

## 选择运行路径

| 需求 | 入口 | 是否需要模型凭据 |
| --- | --- | --- |
| 了解模拟研究流程 | `python -m scripts.e2e_mock_ashare_demo` | 否，固定模拟结果 |
| 生成单股多智能体报告 | `tradingagents` 或 `python main.py` | 是 |
| 独立规则程序筛选沪深主板（不运行 TradingAgents） | `python -m scripts.screen_ashare_main_board` | 否，需要行情网络 |
| 直接读取国内数据 | 下面的 Provider 示例 | 否，部分服务需要额外凭据 |

## 安装与配置

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1`。在 `.env` 中设置 `DEEPSEEK_API_KEY` 后，可运行默认模型配置；如更换服务商，需要同时更换服务商、模型名与凭据。

```python
from copy import deepcopy
from dotenv import load_dotenv
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

load_dotenv()
config = deepcopy(DEFAULT_CONFIG)
config["market"] = {
    "default_market": "CN_A_SHARE",
    "timezone": "Asia/Shanghai",
    "currency": "CNY",
    "code_format": "ts_code",
}
config["data_vendors"] = {
    "core_stock_apis": "a_stock_data",
    "technical_indicators": "a_stock_data",
    "fundamental_data": "a_stock_data",
    "news_data": "a_stock_data",
}
config["provider_fallback_enabled"] = False
config["output_language"] = "Chinese"
config["llm_provider"] = "deepseek"
config["quick_think_llm"] = "deepseek-v4-flash"
config["deep_think_llm"] = "deepseek-v4-pro"
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1
config["checkpoint_enabled"] = True

agent = TradingAgentsGraph(
    selected_analysts=["market", "news", "social", "fundamentals", "capital_flow", "disclosure"],
    config=config,
)
state, signal = agent.propagate("600519.SH", "2026-10-29")
print(signal)
print(state["trader_investment_plan"])
print(state["final_trade_decision"])
```

这些市场与数据源设置已经是当前 A 股默认值，显式列出便于修改。使用 `deepcopy` 避免改动嵌套配置时影响全局默认值。关闭跨服务商兜底不等于关闭 `a_stock_data` 内部的多渠道尝试。模型名须与账号实际可用范围一致。

## 证券输入和角色

常见代码格式 `600519`、`600519.SH`、`sh600519` 会被规范化；`贵州茅台` 等中文名称依赖当前映射表，不提供全市场名称搜索保证。建议使用标准代码，尤其是名称变更或新上市证券。

六种角色为：

- `market`：行情、量价、均线与技术结构。
- `fundamentals`：财务、估值及公司经营风险。
- `news`：国内新闻、宏观快讯与事件催化。
- `social`：情绪、题材与讨论信息。
- `capital_flow`：资金流、龙虎榜与交易结构。
- `disclosure`：公告、研报、股东变化与披露风险。

可只选择其中几类。完整角色覆盖意味着更多数据请求和模型调用，并不保证所有第三方服务在线。

## 查看输出

`propagate()` 返回 `(state, signal)`，其中 `signal` 是最终组合报告的提取结果。

`state["trader_investment_plan"]` 为交易研究提案的可读报告，A 股提案包含 `symbol`、`decision`（`buy/sell/hold/watch`）、`confidence`、`suggested_position_ratio`、止损止盈参考、`risk_flags`、`evidence`、`summary` 与 `human_review_required`。

`state["final_trade_decision"]` 是风险讨论后的最终报告，评级使用 `Buy/Overweight/Hold/Underweight/Sell`。不要把这两个阶段的枚举或返回格式混用。人工复核标记不代表实盘风控已经执行，模型仓位与置信度也需要自行检查。

CLI 完成后可按提示导出完整报告。默认运行日志位于 `.tradingagents/logs/<证券>/<日期>/`；记忆和 checkpoint 分别在 `.tradingagents/memory/` 与 `.tradingagents/cache/`。根目录环境变量配置见 README。

## 不调用模型，直接查询数据

```python
from tradingagents.dataflows.a_stock_data_provider import AStockDataProvider

provider = AStockDataProvider()
result = provider.get_stock_data("600519.SH", "2026-10-01", "2026-10-29")
print("状态：", result.status)
print("错误：", result.errors)
print("数据：", result.data)
```

遇到不可用或部分结果，应先查看状态、错误和来源，再决定是否使用。行情来自多家渠道，口径和更新时点可能不同。新闻、财报、资金与情绪并非都能回放历史日期；指定过去日期不能消除前视偏差。

常规公开接口无需统一的付费行情 Key。通达信相关能力依赖 `mootdx` 和可达 TCP 节点；问财语义研报搜索需要 `IWENCAI_API_KEY`，雪球讨论需要有效 `XUEQIU_COOKIE`。缺少可选凭据时，相关工具会返回不可用信息。请勿上传真实 Cookie。

## 独立工具：主板条件规则筛选

以下程序与上面的 TradingAgents 多智能体研究分别运行。它仅复用仓库内行情模块，按固定条件筛选候选，不调用大模型、六类分析师、多空辩论或风险讨论。独立 Android/iOS App 的使用说明见主 README，它们也不依赖 TradingAgents 服务。

```bash
# 先验证少量代码；没有结果也可能是未满足规则，而非程序故障。
python -m scripts.screen_ashare_main_board --codes 600000,000001

# 默认一手名义金额 2000–3000 元，最多保存 50 个最终候选。
python -m scripts.screen_ashare_main_board --min-lot-amount 2000 --max-lot-amount 3000

# 调整量能、均线与历史窗口。
python -m scripts.screen_ashare_main_board \
  --volume-growth-days 3 --ma-slope-days 3 --kline-lookback-days 45

# 取消换手上限，允许高换手情形进入后续检查。
python -m scripts.screen_ashare_main_board --max-turnover-pct 0
```

默认使用 3%–5% 涨幅、量比大于 1、换手及流通市值等实时条件，再检查近期放量和 MA5/MA10/MA20 走势。默认 K 线逐股请求间隔与东方财富最小请求间隔均为 1.8 秒；进度输出可用 `--quiet` 关闭。该命令没有内置每日定时运行。

结果保存在 `reports/`：CSV 保留实时初筛通过记录，须根据 `selected` 判断最终是否入选，`reject_reason` 区分技术条件不符和数据不可读；TXT 保存最终入选代码及优先级。历史价格位置标签默认使用最近 20 个交易日区间。参数全集使用 `--help` 查看。

## 离线占位和验证

需要固定数据调试时，可将四类 `data_vendors` 全部设为 `cn_placeholder`，并设置 `provider_fallback_enabled=False`。占位数据不是实盘数据，完整研究流程仍可能调用模型或额外的 A 股工具；完全无需外部 API 的演示应使用专用 mock 脚本。

```bash
python -m pip install pytest
python -m pytest -q
python -m scripts.e2e_mock_ashare_demo
```

测试主要覆盖契约与模拟流程，不能证明在线接口可用性或交易有效性。全部研究结果需复核 T+1、涨跌停流动性、停牌、ST/*ST、监管问询、解禁和重大公告等风险；项目没有实盘委托执行能力。
