from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction, get_news
from tradingagents.agents.utils.ashare_data_tools import (
    get_cn_concept_blocks,
    get_cn_eastmoney_global_news,
    get_cn_eastmoney_guba_sentiment,
    get_cn_eastmoney_stock_news,
    get_cn_ths_hot_reason,
    get_cn_xueqiu_sentiment,
)
from tradingagents.dataflows.config import get_config


def _build_social_system_message(language_instruction: str, market_label: str = "A股") -> str:
    """Build market-specific social sentiment analyst prompt."""
    return (
        f"你是{market_label}隔夜超短舆情与题材热度分析师。"
        "系统主要服务于“今天下午/尾盘买，明天上午卖”的短线交易，"
        "你要判断目标股是否站在当下主线题材、情绪是否过热、次日是否可能有溢价。"
        "\n\n"
        "工具使用硬要求：除非工具明确 unavailable/error，你必须至少使用可用工具数量的四分之三（向上取整）。"
        "关键工具包括：get_news、3.1同花顺热点、3.3概念板块、5.1东财个股新闻、5.3东财7x24、"
        "东方财富股吧、雪球。若股吧/雪球缺失，必须写入 missing_critical_data，不得等同于无人关注。"
        "\n\n"
        "隔夜超短舆情核心判断："
        "1) 先找主线：AI算力、机器人、低空、芯片、新能源、国改、业绩线等热点只作例子，必须以当天工具返回为准。"
        "目标股若只是蹭概念、没有板块联动或没有资金确认，不能给高分。"
        "2) 判断情绪周期：题材扩散、龙头强度、跟风高度、是否高潮后分歧；高潮一致且高位缩量要警惕次日兑现。"
        "3) 股吧/雪球/新闻只作为情绪证据，不能把传闻当事实；必须区分多头观点、空头观点、未证实传闻。"
        "4) 对今天下午买入，最重要的是题材热度仍在、关注度上升但未极端拥挤；明天上午若低开无承接或热点退潮，应优先卖出。"
        "对 Contract Fulfilled=false、unavailable/error 的工具结果只能说明数据缺口。"
        "\n\n"
        "输出必须为JSON对象（不要输出Markdown代码块），格式如下："
        "\n"
        "{"
        '"symbol":"...",'
        '"sentiment_score":0,'
        '"attention_score":0,'
        '"theme_heat_score":0,'
        '"crowding_risk":"low/medium/high",'
        '"intraday_swing_sentiment":"strong/medium/weak/invalid",'
        '"main_topics":[], '
        '"bullish_points":[], '
        '"bearish_points":[], '
        '"rumor_risk":"low/medium/high",'
        '"tomorrow_morning_sentiment_risk":"...",'
        '"tool_coverage":"used/available",'
        '"missing_critical_data":[], '
        '"confidence_pct":0,'
        '"evidence":[], '
        '"summary":"..."'
        "}"
        "\n\n"
        "评分要求：sentiment_score 范围 -100 到 100；attention_score/theme_heat_score/confidence_pct 范围 0 到 100。"
        + language_instruction
    )


def create_social_media_analyst(llm):
    def social_media_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
            get_cn_ths_hot_reason,
            get_cn_concept_blocks,
            get_cn_eastmoney_stock_news,
            get_cn_eastmoney_global_news,
            get_cn_eastmoney_guba_sentiment,
            get_cn_xueqiu_sentiment,
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
