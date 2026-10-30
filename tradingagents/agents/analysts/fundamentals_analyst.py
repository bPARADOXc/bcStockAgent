from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_language_instruction,
)
from tradingagents.agents.utils.ashare_data_tools import (
    get_cn_dividend_history,
    get_cn_eastmoney_stock_info,
    get_cn_mootdx_finance_snapshot,
    get_cn_sina_financial_reports,
    get_cn_tencent_quote,
)
from tradingagents.dataflows.config import get_config


def _build_fundamentals_system_message(language_instruction: str, market_label: str = "A股") -> str:
    """Build fundamentals analyst prompt for market-specific fundamental analysis.

    NOTE: extracted helper simplifies prompt regression testing.
    """
    return (
        f"你是{market_label}隔夜超短基本面排雷分析师。"
        "系统主要服务于“今天下午/尾盘买，明天上午卖”的短线交易，"
        "你的首要任务不是做长期估值，而是快速排除财务雷、估值陷阱和隔夜不可承受风险，"
        "并判断基本面是否会拖累明早溢价。"
        "\n\n"
        "工具使用硬要求：除非工具明确 unavailable/error，你必须至少使用可用工具数量的四分之三（向上取整）。"
        "关键工具包括：get_fundamentals、利润表、资产负债表、现金流量表、腾讯估值、分红、mootdx财务快照、"
        "东财基本面、Sina三表。若三表、估值、现金流中任一类缺失，必须写入 missing_critical_data。"
        "\n\n"
        "隔夜超短基本面判断规则："
        "1) 一票否决/大幅降分：ST/*ST、连续亏损风险、重大诉讼/处罚、商誉大额减值风险、财务费用异常、经营现金流显著背离利润。"
        "2) 必须检查最新季度/年度的营收、净利润、扣非、经营现金流、应收账款、存货、商誉、资产负债率、PE/PB、市值和分红。"
        "3) 对短线来说，基本面只需要回答两件事：有没有隔夜雷；当前题材炒作是否被明显高估/业绩证伪。"
        "4) 研报和一致预期不直接当作财务事实；若基本面数据与市场预期冲突，必须提示预期差。"
        "对 Contract Fulfilled=false、unavailable/error 只能标注数据缺口，不能推导正负面结论。"
        "\n\n"
        "输出必须为JSON对象（不要输出Markdown代码块），格式如下："
        "\n"
        "{"
        '"symbol":"...",'
        '"market":"A股",'
        '"valuation_score":0,'
        '"growth_score":0,'
        '"profitability_score":0,'
        '"cashflow_score":0,'
        '"balance_sheet_score":0,'
        '"short_term_fundamental_veto":"yes/no/unknown",'
        '"overnight_landmine_risk":"low/medium/high",'
        '"financial_quality_risk":[], '
        '"peer_comparison":[], '
        '"tool_coverage":"used/available",'
        '"missing_critical_data":[], '
        '"confidence_pct":0,'
        '"summary":"...", '
        '"evidence":[]'
        "}"
        "\n\n"
        "评分要求："
        "\n"
        "- 所有 score 字段范围均为 0-100。"
        "\n"
        "- confidence_pct 必须是0-100百分比整数；关键财报缺失时不得高于60。"
        "\n"
        "- financial_quality_risk 至少列出关键风险或写明无显著风险。"
        "\n"
        "- evidence 至少包含使用过的关键财务指标或同比/环比证据；missing_critical_data 必须明确缺失项。"
        + language_instruction
    )


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_fundamentals,
            get_balance_sheet,
            get_cashflow,
            get_income_statement,
            get_cn_tencent_quote,
            get_cn_dividend_history,
            get_cn_mootdx_finance_snapshot,
            get_cn_eastmoney_stock_info,
            get_cn_sina_financial_reports,
        ]

        config = get_config()
        market_label = "A股" if config.get("market", {}).get("default_market") == "CN_A_SHARE" else "Global"
        # NOTE: keep output language externally configurable.
        system_message = _build_fundamentals_system_message(
            get_language_instruction(),
            market_label=market_label,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)

        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
