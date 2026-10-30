"""Trader: turns the Research Manager's investment plan into a structured A-share advisory decision."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import AShareTraderDecision, render_ashare_trader_decision
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_trader(llm):
    structured_llm = bind_structured(llm, AShareTraderDecision, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a China A-share overnight-swing trading advisor. "
                    "Do NOT place orders. Output an advisory decision only, "
                    "with explicit risk flags and mandatory human review. "
                    "The system is mainly used for short-term trades: buy this afternoon/near the close, sell tomorrow morning."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"基于研究团队结论，请为 {company_name} 生成A股隔夜超短交易建议。{instrument_context} "
                    f"默认交易场景是今天下午/尾盘买入，明天上午卖出；你必须考虑A股制度约束"
                    f"（T+1、涨跌停、停复牌、ST/*ST、不同板块涨跌幅）并输出结构化结论。"
                    f"\n\n研究计划：{investment_plan}\n\n"
                    "只有在主线/题材、技术位置、资金确认、披露排雷至少三项支持，且无硬性否决风险时，才允许给 buy。"
                    "若关键指标缺失或分析报告出现 Contract Fulfilled=false/diagnostic fallback，必须降低 confidence。"
                    "输出字段至少覆盖：decision, confidence（0-100百分比）, suggested_position_ratio, "
                    "stop_loss_reference, take_profit_reference, risk_flags, evidence, "
                    "human_review_required。summary 必须写清下午入场条件、明天上午卖出触发条件和人工复核项。"
                ),
            },
        ]

        trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_ashare_trader_decision,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
