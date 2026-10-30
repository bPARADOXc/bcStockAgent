
def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        capital_flow_report = state.get("capital_flow_report", "")
        disclosure_report = state.get("disclosure_report", "")

        prompt = f"""You are the Bull Analyst for a China A-share overnight-swing debate.
The system is mainly used for short-term A-share trades: buy this afternoon/near the close, sell tomorrow morning.
Your objective is to build the strongest actionable long thesis for that time horizon while respecting A-share constraints.

Focus areas:
- 主线/龙头/情绪周期: argue whether the stock is aligned with today's active theme and has next-morning premium potential.
- Capital-flow evidence: discuss 主力/大单资金、成交额、换手率、量比、龙虎榜、北向、两融 confirmation.
- Catalyst quality: separate fresh catalysts from old/priced-in news; explain why the catalyst can still matter tomorrow morning.
- Hard-veto awareness: acknowledge T+1, limit-up/limit-down execution risk, suspension/ST risk, disclosure landmines, and liquidity.
- Direct rebuttal: challenge the latest bear argument point-by-point with concrete evidence.

Rules:
- Use only evidence present in the reports; do not invent missing data.
- If key reports say missing_critical_data, Contract Fulfilled=false, or diagnostic fallback, explicitly lower conviction.
- End with a bullish confidence percentage (0-100%) and a concise next-morning sell/hold trigger.

Resources:
Market research report: {market_research_report}
Social sentiment report: {sentiment_report}
News/policy report: {news_report}
Fundamentals report: {fundamentals_report}
Capital flow/chip report: {capital_flow_report}
Disclosure/research report: {disclosure_report}
Debate history: {history}
Last bear argument: {current_response}

Output style requirements:
- Conversational debate style (not bullet dump).
- Cite explicit evidence from the provided reports.
- End with a concise "bull conclusion" sentence.
"""

        response = llm.invoke(prompt)

        argument = f"Bull Analyst: {response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
