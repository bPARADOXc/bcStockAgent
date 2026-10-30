from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_global_news,
    get_language_instruction,
    get_news,
)
from tradingagents.agents.utils.ashare_data_tools import (
    get_cn_cls_telegraph_status,
    get_cn_cninfo_announcements,
    get_cn_eastmoney_global_news,
    get_cn_eastmoney_stock_news,
    get_cn_f10_announcement_summary,
)
from tradingagents.dataflows.config import get_config


def _build_news_system_message(language_instruction: str, market_label: str = "A股") -> str:
    """Build market-specific news analyst prompt.

    NOTE: helper extraction supports deterministic prompt tests.
    """
    return (
        f"你是{market_label}隔夜事件催化与政策新闻研究员。"
        "系统主要服务于“今天下午/尾盘买，明天上午卖”的短线交易，"
        "你要判断新闻、公告、政策和监管信息是否足以支持次日上午溢价，或是否构成隔夜雷。"
        "\n\n"
        "工具使用硬要求：除非工具明确 unavailable/error，你必须至少使用可用工具数量的四分之三（向上取整）。"
        "关键工具包括：get_news、get_global_news、5.1东财个股新闻、5.3东财7x24、7.1巨潮公告、7.2 F10公告摘要。"
        "财联社旧接口已下线，只能把 5.2 status 作为数据源状态说明。若公告或个股新闻缺失，必须写入 missing_critical_data。"
        "\n\n"
        "隔夜超短新闻判断规则："
        "1) 优先识别今天盘中/盘后能影响明早集合竞价的催化：政策发布、订单/合同、业绩预告、重组、回购、分红、行业景气新闻。"
        "2) 必须排查隔夜硬雷：监管问询、处罚、立案、减持/清仓式减持、质押爆仓、停复牌、ST/*ST、业绩暴雷、重大诉讼。"
        "3) 新闻强度要看可验证性和新鲜度：旧闻、重复转载、泛行业利好、与个股弱相关，不能高估。"
        "4) 如果新闻已在盘中充分发酵且股价/题材进入一致高潮，明天上午兑现风险要写清楚。"
        "对 Contract Fulfilled=false、unavailable/error 的工具结果只能说明数据缺口。"
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
        '"overnight_catalyst_score":0,'
        '"short_term_impact":"...",'
        '"tomorrow_morning_impact":"...",'
        '"is_news_already_priced_in":"yes/no/unknown",'
        '"tool_coverage":"used/available",'
        '"missing_critical_data":[], '
        '"confidence_pct":0,'
        '"risk_flags":[], '
        '"summary":"...", '
        '"evidence":[]'
        "}"
        "\n\n"
        "评分要求：sentiment_score 范围 -100 到 100；event_importance/overnight_catalyst_score/confidence_pct 范围 0 到 100。"
        + language_instruction
    )


def create_news_analyst(llm):
    def news_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_news,
            get_global_news,
            get_cn_eastmoney_stock_news,
            get_cn_eastmoney_global_news,
            get_cn_cninfo_announcements,
            get_cn_f10_announcement_summary,
            get_cn_cls_telegraph_status,
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
