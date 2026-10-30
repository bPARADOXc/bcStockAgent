# bcStockAgent：面向 A 股的多智能体研究

**本项目基于 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 下载后修改而来，是面向中国 A 股场景的衍生版本。原始多智能体交易研究框架及相关研究成果归原作者所有；本仓库的 A 股数据源、分析流程和配套工具由本项目继续适配和扩展，不代表原项目官方版本。**

bcStockAgent 将行情、技术形态、新闻、市场情绪、财务、资金和公告研报汇总到同一研究流程，经过多空讨论与风险评估，生成中文分析报告和供人工复核的研究结论。当前重点场景是 A 股短线与隔夜观察。

仓库另外收录了**独立的条件规则筛选程序和 Android/iOS App**：它们依据固定行情条件筛选股票，各自运行，不调用 TradingAgents 的多智能体分析流程。使用方式第 1–3 项属于 TradingAgents；第 4–5 项属于这些独立工具。

项目仅用于研究和学习，不构成投资建议，不承诺收益。主流程没有接入券商实盘下单，也不会把模型结论自动发送到交易所。文中的证券代码仅用于演示。

## 相比原项目，做了哪些功能修改

| 功能方向 | 原项目基础 | 本项目的适配与扩展 |
| --- | --- | --- |
| 使用市场 | 通用多智能体金融研究，示例以美股为主 | 默认面向 A 股、人民币和上海时区，支持常见代码形式及有限的中文名称映射 |
| 国内行情 | 保留原有海外数据服务能力 | 接入通达信/mootdx、腾讯、东方财富、新浪、百度等国内数据渠道，覆盖报价、K 线、技术指标与财务数据 |
| 国内消息源 | 新闻与情绪分析框架 | 增加东方财富个股新闻和全球快讯、巨潮公告、东方财富研报、股吧及可选雪球讨论，补充同花顺热点与盈利预测等信息 |
| 分析团队 | 技术、基本面、新闻、情绪四类分析 | 扩展为六类：技术、基本面、新闻、情绪、资金流、公告研报；增加板块题材、龙虎榜、融资融券、大宗交易、股东变动和解禁等研究维度 |
| 研究目标 | 多空辩论、交易提案、组合评估 | 面向“当日下午观察、下一交易日上午退出条件”的隔夜研究，关注催化、量价、资金持续性与退出流动性 |
| A 股风险 | 通用风险讨论 | 加入 T+1、涨跌停、停复牌、ST/*ST、公告与监管事件等风险提示，交易提案要求人工复核 |
| 中文与模型使用 | 保留多模型服务商和交互终端 | 默认中文报告，补充 DeepSeek 推理内容兼容，终端支持新增分析角色与分阶段报告 |
| 研究记录 | 保留决策记忆和断点恢复 | 默认将日志、缓存与记忆集中到项目内 `.tradingagents/`，便于本地管理 |

以上是功能变化概览。数据渠道“已接入”不等于始终可用；部分工具依赖登录信息、第三方接口或特定网络环境，详见[数据源与已知限制](#数据源与已知限制)。

## 分析流程与输出

```text
股票代码与分析日期
    → 技术 / 基本面 / 新闻 / 情绪 / 资金流 / 公告研报
    → 多头与空头讨论 → 研究计划 → 交易研究提案
    → 激进 / 中性 / 保守风险讨论 → 最终组合研究结论
```

可按需选择分析角色，以减少耗时与模型调用。输出包括各角色报告、多空辩论、研究计划、交易提案、风险讨论和最终结论。

A 股交易提案包含 `buy / sell / hold / watch`、置信度、建议仓位、止损止盈参考、证据、风险标记及 `human_review_required=true`。**交易提案和最终结论是不同阶段的结果**：最终组合评级使用 `Buy / Overweight / Hold / Underweight / Sell`；`propagate()` 返回的第二项是从最终报告提取的信号，不是完整的交易提案 JSON。

## 安装

需要 Python 3.10 或更新版本。建议在独立虚拟环境中安装，并从仓库根目录运行示例。

```bash
git clone https://github.com/bPARADOXc/bcStockAgent.git
cd bcStockAgent
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
cp .env.example .env
```

在 `.env` 中填写所选模型服务商的凭据。默认配置使用 DeepSeek：

```dotenv
DEEPSEEK_API_KEY=your_deepseek_api_key
```

如果选择 OpenAI、Google、Anthropic、Qwen、GLM 等服务商，应同时在 CLI 或 Python 配置中切换服务商和模型，并设置相应环境变量；不要只替换 API Key。Azure 等企业配置可参考 [.env.enterprise.example](.env.enterprise.example)。模型 ID 以账号实际可用范围为准，调用可能产生费用。

默认 A 股数据源为 `a_stock_data`，常规行情调用无需 Alpha Vantage Key。问财研报搜索与雪球讨论属于可选能力，对应凭据见 `.env.example`。不要提交 `.env`、Cookie 或真实密钥。

## TradingAgents 使用方式（第 1–3 项）

### 1. 先运行离线演示

```bash
python -m scripts.e2e_mock_ashare_demo
```

这是使用固定报告和模拟模型的流程演示，覆盖多空讨论、研究计划和 A 股交易提案，无需 API Key，也不调用真实行情接口。它不代表真实数据质量、真实模型表现或完整六分析师在线运行结果。

### 2. 交互式命令行

```bash
tradingagents
# 或
python -m cli.main
```

根据提示选择证券、分析日期、分析角色、模型服务商、模型和讨论深度。首次建议使用标准代码（例如 `600519.SH`），选择少量角色、较浅讨论深度，确认凭据和网络正常后再扩展。

启用中断恢复或清除旧检查点：

```bash
tradingagents analyze --checkpoint
tradingagents analyze --clear-checkpoints
```

CLI 展示各角色运行进度和报告，完成后可按提示保存完整报告。默认运行目录为 `.tradingagents/logs/<证券>/<日期>/`；导出报告包含 `1_analysts` 至 `5_portfolio` 分阶段目录和 `complete_report.md`。

### 3. Python 单股分析

```python
from copy import deepcopy
from dotenv import load_dotenv
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

load_dotenv()
config = deepcopy(DEFAULT_CONFIG)
config["llm_provider"] = "deepseek"
config["quick_think_llm"] = "deepseek-v4-flash"
config["deep_think_llm"] = "deepseek-v4-pro"
config["output_language"] = "Chinese"
# 禁止跨服务商兜底；国内聚合数据源自身仍可能尝试多个渠道。
config["provider_fallback_enabled"] = False
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1

agent = TradingAgentsGraph(
    selected_analysts=[
        "market", "fundamentals", "news", "social", "capital_flow", "disclosure"
    ],
    debug=False,
    config=config,
)
state, signal = agent.propagate("600519.SH", "2026-10-29")
print("最终信号：", signal)
print(state["trader_investment_plan"])
print(state["final_trade_decision"])
```

模型 ID 是本仓库当前配置示例；如果服务商返回模型不可用，请改为账号可调用的型号。分析日期用于研究上下文和部分数据查询，**不能保证所有新闻、财务、资金和情绪工具都返回截至该日的历史快照**，因此上述示例不能直接作为无前视偏差的历史回测。

输入格式可使用 `600519`、`600519.SH`、`sh600519`；中文名称依赖当前映射表，建议优先使用标准代码。沪深北代码识别与各数据源实际覆盖范围不同。

更多配置与数据调用示例见 [A 股使用指南](docs/ashare_quickstart.md)。根目录 [main.py](main.py) 也提供可直接修改后运行的 A 股示例。

## 独立条件规则筛选工具（第 4–5 项）

下面的 Python 筛选程序与移动 App 是单独的规则筛选工具，与上面的 TradingAgents 研究流程分别使用。它们按预设行情条件产生候选结果，不经过六类分析师、多空辩论或模型风险讨论。Python 程序复用仓库内的行情模块；Android/iOS App 在手机本地独立实现筛选，不需要启动 Python 服务或配置大模型 API Key。

### 4. 独立 Python 条件规则筛选程序

```bash
python -m scripts.screen_ashare_main_board \
  --min-lot-amount 2000 --max-lot-amount 3000 \
  --output-dir reports
```

金额指买入 **100 股的一手名义金额（不含费用）**。默认筛选涨幅 3%–5%、量比大于 1 等实时行情条件，再检查最近 3 个交易日放量和 MA5/MA10/MA20 向上；K 线默认回看 45 个自然日，并给出最近 20 个交易日的价格区间位置。其他门槛以脚本参数和实际筛选规则为准。

先用少量证券验证网络与结果：

```bash
python -m scripts.screen_ashare_main_board --codes 600000,000001 --output-dir reports
python -m scripts.screen_ashare_main_board --help
```

默认输出：

- `reports/ashare_main_board_2000_3000_candidates.csv`：通过实时行情初筛的全部记录，`selected` 表示是否最终通过，`reject_reason` 说明未通过原因。
- `reports/ashare_main_board_2000_3000_codes.txt`：最终入选代码及优先级分组。

该工具适合尾盘观察，但命令需要手动运行，并非默认每天 14:30 自动执行。默认逐股串行检查 K 线、请求间隔 1.8 秒，全市场运行可能较慢。使用 `--max-turnover-pct 0` 可取消默认 10% 换手上限，`--quiet` 可关闭进度输出。筛选结果只是规则匹配，不代表买入建议。

### 5. 独立 Android/iOS 条件规则筛选 App

移动 App 用于本地运行条件规则筛选、查看单股和保存结果，属于独立客户端工程，不是 TradingAgents 的手机端，也不会展示或调用多智能体研究报告。

| 入口 | 用途 | 说明 |
| --- | --- | --- |
| [Android 客户端](android_app/README.md) | 手机本地主板筛选、单股查看、历史保存、HTML 分享 | 独立 Android 工程，需要 Android Studio 构建 |
| [iOS 客户端](ios_app/README.md) | 本地主板筛选、单股查询、历史与通知 | 需要 macOS/Xcode；后台定时由系统调度，无法保证准点完成 |

## 数据源与已知限制

- **行情与技术**：腾讯报价，通达信/mootdx、百度、新浪、东方财富 K 线等。公网 HTTP/TCP 可用性和数据源限流会影响成功率；聚合渠道可降级，具体结果应检查返回状态和来源。
- **财务与公司信息**：新浪财报、通达信财务/F10、东方财富公司信息、估值及相关披露。不同接口的报告期、更新时间和单位可能不同。
- **新闻与公告研报**：东方财富新闻/快讯/研报、巨潮公告及可选问财搜索；不会保证每个接口都能按历史日期回放。财联社旧接口当前仅返回不可用提示。
- **情绪与资金**：板块题材、股吧、资金流、龙虎榜及相关披露等；雪球讨论需要有效 `XUEQIU_COOKIE`，部分北向资金历史依赖本地积累，不能假定全部历史均可查询。
- **缺失结果**：无权限、断网、空数据或接口失效时会返回不可用、部分结果或错误信息。不要把缺失值当作零值，也不要将模型补充的推断当作事实。
- **离线占位**：`cn_placeholder` 是用于调试的确定性占位数据，不是真实市场行情。仅切换到它并不会免除真实模型调用；无需模型的离线演示应使用上面的 mock 脚本。
- **风险约束**：仓位、ST、停牌、涨跌停等配置用于研究提示与复核，不构成券商级交易合规或委托前拦截系统。模型置信度不是经校准的盈利概率。

## 日志、缓存与断点

默认记录保存在仓库内 `.tradingagents/`，包括 `logs/`、`cache/`、`memory/trading_memory.md`。决策记忆可为后续同证券研究提供反思上下文；开启 checkpoint 后可恢复中断节点，成功完成后清除本次检查点。数据缺失时，收益回看或反思也可能无法完成。

可使用以下环境变量覆盖位置：

```dotenv
TRADINGAGENTS_HOME=/path/to/local-state
TRADINGAGENTS_RESULTS_DIR=/path/to/reports
TRADINGAGENTS_CACHE_DIR=/path/to/cache
TRADINGAGENTS_MEMORY_LOG_PATH=/path/to/trading_memory.md
```

使用 Docker 时先配置 `.env`，再执行 `docker compose run --rm tradingagents`。如需沿用 Compose 中的持久卷，请在 `.env` 设置 `TRADINGAGENTS_HOME=/home/appuser/.tradingagents`，使运行目录与挂载点一致。

## 验证与贡献

```bash
python -m pip install pytest
python -m pytest -q
python -m scripts.e2e_mock_ashare_demo
```

常规自动化测试主要验证代码映射、数据契约、A 股分析提示、交易提案人工复核和模拟流程；通过测试不等于在线接口全部可用，也不代表策略有效。独立移动 App 的构建和测试方式见各自 README。

欢迎提交问题和改进。反馈数据源问题时请提供证券、时间、接口状态与脱敏日志。不要上传密钥、Cookie、个人研究记录、大批量行情数据或构建产物。

## 原项目、许可与引用

- 原项目：[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
- 本衍生版本：[bPARADOXc/bcStockAgent](https://github.com/bPARADOXc/bcStockAgent)
- 许可：保留原项目 [Apache License 2.0](LICENSE) 及原作者相关声明。原框架图片、论文和历史发布记录应归属于原项目；[CHANGELOG.md](CHANGELOG.md) 保留的上游历史不应理解为本衍生版本自行发布的成果。
- 原论文：[TradingAgents: Multi-Agents LLM Financial Trading Framework](https://arxiv.org/abs/2412.20138)

如使用原框架的研究成果，请保留原论文引用；如介绍本仓库，请同时说明它是在原项目基础上的 A 股适配版本。

```bibtex
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
  title={TradingAgents: Multi-Agents LLM Financial Trading Framework},
  author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
  year={2025},
  eprint={2412.20138},
  archivePrefix={arXiv},
  primaryClass={q-fin.TR},
  url={https://arxiv.org/abs/2412.20138}
}
```
