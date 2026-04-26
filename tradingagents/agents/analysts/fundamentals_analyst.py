from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_income_statement,
    get_language_instruction,
)
from tradingagents.dataflows.config import get_config


def _build_fundamentals_system_message(language_instruction: str, market_label: str = "A股") -> str:
    """Build fundamentals analyst prompt for market-specific fundamental analysis.

    NOTE: extracted helper simplifies prompt regression testing.
    """
    return (
        f"你是{market_label}基本面分析师。"
        "你需要围绕财报质量、估值、成长性、盈利能力、现金流和资产负债结构，"
        "输出结构化投资研究结论。"
        "\n\n"
        "请优先调用以下工具并交叉验证："
        "\n"
        "1) get_fundamentals（公司概览与估值）"
        "\n"
        "2) get_income_statement（收入与利润趋势）"
        "\n"
        "3) get_balance_sheet（资产负债结构）"
        "\n"
        "4) get_cashflow（经营现金流质量）"
        "\n\n"
        "A股语境必须覆盖：年报/半年报/季报口径、商誉减值风险、应收账款与存货质量、"
        "股东减持/质押与解禁压力（若可得）、监管问询或异常财务信号（若可得）。"
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
        '"financial_quality_risk":[], '
        '"peer_comparison":[], '
        '"summary":"...", '
        '"evidence":[]'
        "}"
        "\n\n"
        "评分要求："
        "\n"
        "- 所有 score 字段范围均为 0-100。"
        "\n"
        "- financial_quality_risk 至少列出关键风险或写明无显著风险。"
        "\n"
        "- evidence 至少包含使用过的关键财务指标或同比/环比证据。"
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
