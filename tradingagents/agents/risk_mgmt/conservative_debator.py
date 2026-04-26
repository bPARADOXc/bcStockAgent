
def create_conservative_debator(llm):
    def conservative_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        conservative_history = risk_debate_state.get("conservative_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]

        trader_decision = state["trader_investment_plan"]

        prompt = f"""As the Conservative Risk Analyst in a China A-share context, prioritize capital protection and rule-compliant execution.

Trader advisory decision:
{trader_decision}

Debate instructions:
- Evaluate hard veto risks first: ST/*ST, suspension, delisting signals, severe liquidity risk.
- Evaluate execution risk: limit-down exit failure, limit-up chase risk, T+1 inability to same-day exit.
- Evaluate fundamental tail risk: earnings miss, goodwill impairment, regulatory inquiry, pledge/reduction/unlock pressure.
- Rebut aggressive/neutral assumptions where downside is underpriced.
- Ensure recommendations preserve human-review-first workflow.

Inputs:
Market report: {market_research_report}
Sentiment report: {sentiment_report}
News/policy report: {news_report}
Fundamentals report: {fundamentals_report}
History: {history}
Aggressive latest: {current_aggressive_response}
Neutral latest: {current_neutral_response}

Output should be conversational but explicit about risk triggers and veto conditions.
"""

        response = llm.invoke(prompt)

        argument = f"Conservative Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": conservative_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return conservative_node
