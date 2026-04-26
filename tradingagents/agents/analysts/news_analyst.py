from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
)
from tradingagents.dataflows.config import get_config


def _build_news_system_message(language_instruction: str, market_label: str = "A股") -> str:
    """Build market-specific news analyst prompt.

    NOTE: helper extraction supports deterministic prompt tests.
    """
    return (
        f"你是{market_label}新闻与政策研究员。"
        "你需要从公司新闻、行业新闻、宏观政策和监管动态中评估事件冲击。"
        "\n\n"
        "请使用："
        "\n"
        "1) get_news(query,start_date,end_date) 获取公司与行业相关新闻"
        "\n"
        "2) get_global_news(curr_date,look_back_days,limit) 获取宏观/政策背景"
        "\n\n"
        "A股语境必须覆盖：证监会/交易所监管动态、问询函、产业政策、北向资金叙事、"
        "以及潜在停复牌或重大事项公告影响（若可得）。"
        "\n\n"
        "输出必须为JSON对象（不要输出Markdown代码块），格式如下："
        "\n"
        "{"
        '"symbol":"...",'
        '"company_news":[], '
        '"industry_news":[], '
        '"macro_policy_news":[], '
        '"regulatory_news":[], '
        '"sentiment_score":0,'
        '"event_importance":0,'
        '"short_term_impact":"...",'
        '"medium_term_impact":"...",'
        '"risk_flags":[], '
        '"summary":"...", '
        '"evidence":[]'
        "}"
        "\n\n"
        "评分要求：sentiment_score 范围 -100 到 100，event_importance 范围 0 到 100。"
        + language_instruction
    )


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
            get_global_news,
        ]

        config = get_config()
        market_label = "A股" if config.get("market", {}).get("default_market") == "CN_A_SHARE" else "Global"
        # NOTE: keep language configurable via global config.
        system_message = _build_news_system_message(get_language_instruction(), market_label=market_label)

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
            "news_report": report,
        }

    return news_analyst_node
