
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

        prompt = f"""You are the Bull Analyst for a China A-share investment debate.
Your objective is to build the strongest long thesis while respecting A-share market constraints.

Focus areas:
- Policy and industry catalysts: identify policy tailwinds,产业趋势, and board-level momentum (主板/创业板/科创板).
- Capital-flow evidence: discuss 北向资金、融资融券结构变化、成交量与换手率 confirmation.
- Fundamental upside: explain valuation re-rating potential,盈利改善, and cashflow resilience.
- Trading feasibility: acknowledge A-share constraints like T+1, limit-up execution risk, and suspension risk.
- Direct rebuttal: challenge the latest bear argument point-by-point with concrete evidence.

Resources:
Market research report: {market_research_report}
Social sentiment report: {sentiment_report}
News/policy report: {news_report}
Fundamentals report: {fundamentals_report}
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
