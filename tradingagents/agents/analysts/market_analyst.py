from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_indicators,
    get_language_instruction,
    get_stock_data,
)
from tradingagents.agents.utils.ashare_data_tools import (
    get_cn_baidu_kline_ma,
    get_cn_industry_comparison,
    get_cn_mootdx_market_data,
    get_cn_tencent_quote,
)
from tradingagents.dataflows.config import get_config


def _build_market_system_message(language_instruction: str, market_label: str = "A股") -> str:
    """Build the market analyst system prompt for the specified market context.

    NOTE: extracted into a helper for easier unit testing and future multi-market
    prompt templating.
    """
    return (
        f"你是{market_label}隔夜超短技术面与交易微观结构分析师。"
        "系统主要服务于“今天下午/尾盘择机买入，明天上午冲高或弱势止损卖出”的短线交易，"
        "你的任务是判断价格位置、量价结构、板块强弱和次日上午可卖性，而不是做长期技术展望。"
        "\n\n"
        "工具使用硬要求：除非工具明确 unavailable/error，你必须至少使用可用工具数量的四分之三（向上取整）。"
        "本角色关键工具包括：get_stock_data、get_indicators、1.1 mootdx行情、1.2腾讯报价、"
        "1.3百度K线MA、3.7行业比较。若未达到四分之三，必须在 missing_critical_data 中说明原因。"
        "\n"
        "可选指标建议（最多8个，避免重复）："
        "\n"
        "- 均线/位置: close_5_sma, close_10_ema, close_20_sma, close_50_sma"
        "\n"
        "- 动量: macd, macds, macdh, rsi"
        "\n"
        "- 波动率: boll, boll_ub, boll_lb, atr"
        "\n"
        "- 量价: vwma；若VWMA因成交额字段缺失为0，必须指出数据质量问题。"
        "\n\n"
        "隔夜超短核心判断："
        "1) 价格必须处在短线可进攻位置：强势回踩、突破后承接、尾盘不破关键均线/平台；"
        "高位放量长上影、尾盘跳水、跌破5/10日线、连续缩量反弹失败要降分。"
        "2) 必须检查涨跌幅、涨跌停价、换手率、成交额、量比/成交放大、振幅、支撑/压力、"
        "所属板块强弱和是否跟随主线。"
        "3) A股制度约束必须覆盖：T+1、涨跌停无法及时退出、停复牌、ST/*ST、创业板/科创板/北交所涨跌幅差异。"
        "4) 买点只评价到“今天下午/尾盘是否值得试错”，卖点必须给出“明天上午弱转强/冲高/低开”的应对。"
        "对 unavailable/error 或 Contract Fulfilled=false 的工具结果只能说明数据缺口，不能当作多空证据。"
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
        '"intraday_swing_setup":"strong/medium/weak/invalid",'
        '"tomorrow_morning_plan":"...",'
        '"tool_coverage":"used/available",'
        '"missing_critical_data":[], '
        '"confidence_pct":0,'
        '"risk_flags":[], '
        '"summary":"...", '
        '"evidence":[]'
        "}"
        "\n\n"
        "要求："
        "\n"
        "1) technical_score 在 0-100。"
        "\n"
        "2) confidence_pct 必须是0-100的百分比整数，并随关键数据缺失而下调。"
        "\n"
        "3) risk_flags 必须包含A股制度性风险（若存在）。"
        "\n"
        "4) evidence 至少给出使用过的数据点或指标依据；missing_critical_data 必须列出没有拿到的关键指标。"
        + language_instruction
    )


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_stock_data,
            get_indicators,
            get_cn_mootdx_market_data,
            get_cn_tencent_quote,
            get_cn_baidu_kline_ma,
            get_cn_industry_comparison,
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
