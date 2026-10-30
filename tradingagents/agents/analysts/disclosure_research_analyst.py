from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction
from tradingagents.agents.utils.ashare_data_tools import (
    get_cn_cninfo_announcements,
    get_cn_eastmoney_reports,
    get_cn_f10_announcement_summary,
    get_cn_iwencai_report_search,
    get_cn_mootdx_f10,
    get_cn_sina_financial_reports,
    get_cn_ths_eps_forecast,
)


def _build_disclosure_system_message(language_instruction: str, market_label: str = "A股") -> str:
    return (
        f"你是{market_label}隔夜公告披露与预期差分析师。"
        "系统主要服务于“今天下午/尾盘买，明天上午卖”的短线交易。"
        "你的任务不是重复基本面分析，而是审查今天及近期公告、F10历史资料、研报假设和一致预期，"
        "判断是否存在隔夜雷、明早催化或短线预期差。"
        "\n\n"
        "工具使用硬要求：除非工具明确 unavailable/error，你必须至少使用可用工具数量的四分之三（向上取整）。"
        "关键工具包括：2.1东财研报、2.2同花顺EPS、2.3 i问财研报搜索、6.2 F10、7.1巨潮公告、"
        "7.2 F10公告摘要、6.4新浪三表。若公告/F10或研报/EPS缺失，必须写入 missing_critical_data。"
        "\n\n"
        "隔夜超短披露判断规则："
        "1) 一票否决/大幅降分：监管立案、交易所问询、处罚、ST/*ST、停牌风险、业绩暴雷、清仓减持、质押风险、重大诉讼。"
        "2) 明早可能有溢价的催化：订单/合同、重组进展、回购增持、业绩超预期、分红、政策相关公告、子公司上市/资产注入。"
        "3) 研报/EPS只用于判断市场预期，不可当作事实；若最新财报与一致预期冲突，要明确正/负预期差。"
        "4) F10长文本关注最新提示、公司概况、财务分析和股东研究；研报PDF不默认下载；iwencai无key只能说明不可用。"
        "5) 今天下午买入前，必须明确是否有盘后公告风险；明天上午卖出前，必须提示是否存在消息兑现。"
        "\n\n"
        "输出必须为JSON对象（不要Markdown代码块），格式如下："
        "{"
        '"symbol":"...",'
        '"market":"A股",'
        '"disclosure_score":0,'
        '"expectation_gap":"positive/negative/neutral/unknown",'
        '"overnight_disclosure_risk":"low/medium/high",'
        '"next_morning_catalyst":"strong/medium/weak/none/unknown",'
        '"announcement_events":[], '
        '"research_consensus":"...",'
        '"eps_assumption_quality":"...",'
        '"red_flags":[], '
        '"manual_review_items":[], '
        '"bullish_points":[], '
        '"bearish_points":[], '
        '"tool_coverage":"used/available",'
        '"missing_critical_data":[], '
        '"confidence_pct":0,'
        '"summary":"...", '
        '"evidence":[]'
        "}"
        "\n\n"
        "disclosure_score/confidence_pct 范围0-100；unavailable/error/Contract Fulfilled=false只能说明数据缺口，不得当作无风险。"
        + language_instruction
    )


def create_disclosure_research_analyst(llm):
    def disclosure_research_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        symbol = state["company_of_interest"]
        tools = [
            get_cn_eastmoney_reports,
            get_cn_ths_eps_forecast,
            get_cn_iwencai_report_search,
            get_cn_mootdx_f10,
            get_cn_cninfo_announcements,
            get_cn_f10_announcement_summary,
            get_cn_sina_financial_reports,
        ]

        system_message = _build_disclosure_system_message(get_language_instruction(), market_label="A股")
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools aggressively when they can add evidence."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}"
                    " For iwencai searches, formulate concise Chinese queries using the exact symbol {symbol}.",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )
        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)
        prompt = prompt.partial(symbol=symbol)

        result = (prompt | llm.bind_tools(tools)).invoke(state["messages"])
        report = result.content if len(result.tool_calls) == 0 else ""
        return {"messages": [result], "disclosure_report": report}

    return disclosure_research_analyst_node
