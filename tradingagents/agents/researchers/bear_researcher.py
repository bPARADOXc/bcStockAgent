
def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        capital_flow_report = state.get("capital_flow_report", "")
        disclosure_report = state.get("disclosure_report", "")

        prompt = f"""You are the Bear Analyst for a China A-share overnight-swing debate.
The system is mainly used for short-term A-share trades: buy this afternoon/near the close, sell tomorrow morning.
Your goal is to stress-test the long thesis and identify downside paths that can hurt this specific overnight trade.

Focus areas:
- 情绪退潮风险: identify theme climax, weak followers, high-position blow-off, stale catalyst, and next-morning sell pressure.
- Policy/regulatory risk: examine 监管问询、处罚、停复牌、ST/*ST, and compliance shocks.
- Balance-sheet and earnings risk: highlight profit quality, cashflow pressure, goodwill impairment, receivables/inventory risk.
- Capital overhang: discuss 股东减持、质押、解禁压力、大宗折价、融资盘拥挤 and liquidity fragility.
- Trading constraints: assess limit-down exit risk, limit-up chase risk, suspension risk, and T+1 inability to same-day de-risk.
- Direct rebuttal: challenge the latest bull claims with concrete counter-evidence.

Rules:
- Use only evidence present in the reports; do not invent missing data.
- Missing critical data, Contract Fulfilled=false, or diagnostic fallback is not automatically bearish, but it lowers confidence and must be called out.
- End with a bearish confidence percentage (0-100%) and a concise invalidation condition for the bear case.

Resources:
Market research report: {market_research_report}
Social sentiment report: {sentiment_report}
News/policy report: {news_report}
Fundamentals report: {fundamentals_report}
Capital flow/chip report: {capital_flow_report}
Disclosure/research report: {disclosure_report}
Debate history: {history}
Last bull argument: {current_response}

Output style requirements:
- Conversational debate style (not bullet dump).
- Cite explicit evidence from the provided reports.
- End with a concise "bear conclusion" sentence.
"""

        response = llm.invoke(prompt)

        argument = f"Bear Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
