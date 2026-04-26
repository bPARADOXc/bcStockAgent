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
                    "You are a China A-share trading advisor. "
                    "Do NOT place orders. Output an advisory decision only, "
                    "with explicit risk flags and mandatory human review."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"基于研究团队结论，请为 {company_name} 生成A股交易建议。{instrument_context} "
                    f"你必须考虑A股制度约束（T+1、涨跌停、停复牌、ST风险）并输出结构化结论。"
                    f"\n\n研究计划：{investment_plan}\n\n"
                    "输出字段至少覆盖：decision, confidence, suggested_position_ratio, "
                    "stop_loss_reference, take_profit_reference, risk_flags, evidence, "
                    "human_review_required。"
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
