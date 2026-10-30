from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction
from tradingagents.agents.utils.ashare_data_tools import (
    get_cn_block_trades,
    get_cn_daily_dragon_tiger,
    get_cn_dragon_tiger_board,
    get_cn_fund_flow_120d,
    get_cn_holder_changes,
    get_cn_industry_comparison,
    get_cn_intraday_fund_flow,
    get_cn_lockup_expiry,
    get_cn_margin_trading,
    get_cn_mootdx_market_data,
    get_cn_northbound_flow,
    get_cn_signal_summary,
    get_cn_tencent_quote,
)


def _build_capital_flow_system_message(language_instruction: str, market_label: str = "A股") -> str:
    return (
        f"你是{market_label}隔夜超短资金流与筹码结构分析师。"
        "系统主要服务于“今天下午/尾盘买，明天上午卖”的短线交易。"
        "你是超短决策里最关键的裁判之一：判断题材是否有资金确认、筹码是否支持次日冲高、"
        "以及是否存在明早无法退出的流动性风险。"
        "\n\n"
        "工具使用硬要求：除非工具明确 unavailable/error，你必须至少使用可用工具数量的四分之三（向上取整）。"
        "关键工具包括：1.1行情、1.2腾讯报价、3.2北向、3.4分钟资金流、3.5个股龙虎榜、3.6解禁、"
        "3.7行业比较、3.8全市场龙虎榜、3.9信号汇总、4.1两融、4.2大宗、4.3股东户数、4.5 120日资金流。"
        "若资金流工具为 diagnostic 或 Contract Fulfilled=false，必须说明不能判断真实主力净流。"
        "\n\n"
        "隔夜超短资金流判断规则："
        "1) 买入只考虑“资金确认 + 板块共振 + 尾盘承接”三者至少两项成立；单纯缩量上涨或无量冲高要降分。"
        "2) 必须关注主力/大单净流、成交额、换手率、量比、龙虎榜席位、两融变化、大宗折价、股东户数变化、解禁/减持压力。"
        "3) 题材高潮时，高换手放巨量、龙虎榜卖方过强、折价大宗、融资盘拥挤，明早兑现风险要写清。"
        "4) 北向资金0/NaN或reliability=low不能解释为无资金；全市场榜单只能判断资金偏好，不能直接推出个股买卖。"
        "5) 东财资金流原始单位是元，必须换算并标注。"
        "\n\n"
        "输出必须为JSON对象（不要Markdown代码块），格式如下："
        "{"
        '"symbol":"...",'
        '"market":"A股",'
        '"capital_score":0,'
        '"fund_flow_contract":"fulfilled/partial/diagnostic/missing",'
        '"theme_money_alignment":"strong/medium/weak/unknown",'
        '"northbound_view":"...",'
        '"main_fund_flow":"...",'
        '"chip_structure":"...",'
        '"liquidity_exit_risk":"low/medium/high",'
        '"tomorrow_morning_flow_plan":"...",'
        '"event_pressure":[], '
        '"risk_flags":[], '
        '"bullish_points":[], '
        '"bearish_points":[], '
        '"tool_coverage":"used/available",'
        '"missing_critical_data":[], '
        '"confidence_pct":0,'
        '"summary":"...", '
        '"evidence":[]'
        "}"
        "\n\n"
        "capital_score/confidence_pct 范围0-100；unavailable/error/diagnostic只能作为数据缺口或降级提示，不得当作正负面事实。"
        + language_instruction
    )


def create_capital_flow_analyst(llm):
    def capital_flow_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])
        tools = [
            get_cn_mootdx_market_data,
            get_cn_tencent_quote,
            get_cn_northbound_flow,
            get_cn_intraday_fund_flow,
            get_cn_dragon_tiger_board,
            get_cn_lockup_expiry,
            get_cn_industry_comparison,
            get_cn_daily_dragon_tiger,
            get_cn_signal_summary,
            get_cn_margin_trading,
            get_cn_block_trades,
            get_cn_holder_changes,
            get_cn_fund_flow_120d,
        ]

        system_message = _build_capital_flow_system_message(get_language_instruction(), market_label="A股")
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools aggressively when they can add evidence."
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

        result = (prompt | llm.bind_tools(tools)).invoke(state["messages"])
        report = result.content if len(result.tool_calls) == 0 else ""
        return {"messages": [result], "capital_flow_report": report}

    return capital_flow_analyst_node
