from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_language_instruction,
    get_stock_data,
)
from tradingagents.dataflows.config import get_config


def _build_market_system_message(language_instruction: str, market_label: str = "A股") -> str:
    """Build the market analyst system prompt for the specified market context.

    NOTE: extracted into a helper for easier unit testing and future multi-market
    prompt templating.
    """
    return (
        f"你是{market_label}技术面与交易微观结构分析师。"
        "你的任务是基于行情和技术指标，输出可执行的分析结论，并严格考虑A股交易制度。"
        "\n\n"
        "请先调用 get_stock_data 获取OHLCV数据，再按需调用 get_indicators。"
        "\n"
        "可选指标建议（最多8个，避免重复）："
        "\n"
        "- 均线: close_10_ema, close_50_sma, close_200_sma"
        "\n"
        "- 动量: macd, macds, macdh, rsi"
        "\n"
        "- 波动率: boll, boll_ub, boll_lb, atr"
        "\n"
        "- 量价: vwma"
        "\n\n"
        "A股语境必须覆盖：涨跌停、T+1、停复牌、ST风险、板块属性（主板/创业板/科创板/北交所）"
        "以及量价背离和资金博弈特征。"
        "\n\n"
        "输出必须为JSON对象（不要输出Markdown代码块），格式如下："
        "\n"
        "{"
        '"symbol":"...",'
        '"name":"...",'
        '"market":"A股",'
        '"trend":"up/down/sideways",'
        '"technical_score":0,'
        '"volume_price_analysis":"...",'
        '"support_levels":[], '
        '"resistance_levels":[], '
        '"momentum_signals":[], '
        '"risk_flags":[], '
        '"summary":"...", '
        '"evidence":[]'
        "}"
        "\n\n"
        "要求："
        "\n"
        "1) technical_score 在 0-100。"
        "\n"
        "2) risk_flags 必须包含A股制度性风险（若存在）。"
        "\n"
        "3) evidence 至少给出使用过的数据点或指标依据。"
        + language_instruction
    )


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_stock_data,
            get_indicators,
        ]

        config = get_config()
        market_label = "A股" if config.get("market", {}).get("default_market") == "CN_A_SHARE" else "Global"
        # NOTE: keep language configurable, but default to existing utility behavior.
        system_message = _build_market_system_message(get_language_instruction(), market_label=market_label)

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
            "market_report": report,
        }

    return market_analyst_node
