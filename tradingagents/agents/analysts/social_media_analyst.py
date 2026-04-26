from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction, get_news
from tradingagents.dataflows.config import get_config


def _build_social_system_message(language_instruction: str, market_label: str = "A股") -> str:
    """Build market-specific social sentiment analyst prompt."""
    return (
        f"你是{market_label}舆情分析师。"
        "你需要综合公司相关新闻、讨论热度和情绪方向，识别短线情绪驱动与谣言风险。"
        "\n\n"
        "请使用 get_news(query,start_date,end_date) 搜集可得的舆情/媒体线索，并区分："
        "\n"
        "- 多头观点"
        "\n"
        "- 空头观点"
        "\n"
        "- 未证实传闻"
        "\n\n"
        "A股语境必须覆盖：股吧/雪球/东方财富讨论倾向、互动易问答与公告解读（若可得）。"
        "\n\n"
        "输出必须为JSON对象（不要输出Markdown代码块），格式如下："
        "\n"
        "{"
        '"symbol":"...",'
        '"sentiment_score":0,'
        '"attention_score":0,'
        '"main_topics":[], '
        '"bullish_points":[], '
        '"bearish_points":[], '
        '"rumor_risk":"low/medium/high",'
        '"evidence":[], '
        '"summary":"..."'
        "}"
        "\n\n"
        "评分要求：sentiment_score 范围 -100 到 100；attention_score 范围 0 到 100。"
        + language_instruction
    )


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
        ]

        config = get_config()
        market_label = "A股" if config.get("market", {}).get("default_market") == "CN_A_SHARE" else "Global"
        # NOTE: keep language configurable via global config.
        system_message = _build_social_system_message(get_language_instruction(), market_label=market_label)

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
            "sentiment_report": report,
        }

    return social_media_analyst_node
