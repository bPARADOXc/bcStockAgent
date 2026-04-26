
def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        trader_decision = state["trader_investment_plan"]

        prompt = f"""As the Aggressive Risk Analyst in a China A-share context, advocate for upside capture while acknowledging hard market constraints.

Trader advisory decision:
{trader_decision}

Debate instructions:
- Defend high-conviction opportunities when catalysts are strong (policy, earnings inflection, capital flow).
- Explicitly address A-share execution constraints (T+1, limit-up/limit-down, suspension risk).
- Rebut conservative/neutral arguments with data-backed upside scenarios.
- Do NOT suggest bypassing risk controls; keep human review mandatory.

Inputs:
Market report: {market_research_report}
Sentiment report: {sentiment_report}
News/policy report: {news_report}
Fundamentals report: {fundamentals_report}
History: {history}
Conservative latest: {current_conservative_response}
Neutral latest: {current_neutral_response}

Output should be conversational and persuasive, with explicit evidence references.
"""

        response = llm.invoke(prompt)

        argument = f"Aggressive Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
