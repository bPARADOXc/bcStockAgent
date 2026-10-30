
def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        capital_flow_report = state.get("capital_flow_report", "")
        disclosure_report = state.get("disclosure_report", "")

        trader_decision = state["trader_investment_plan"]

        prompt = f"""As the Neutral Risk Analyst in a China A-share overnight-swing context, synthesize upside/downside into an implementable advisory stance.
The trade horizon is short: buy this afternoon/near the close, sell tomorrow morning. Do not drift into a multi-week or fundamental-value thesis.

Trader advisory decision:
{trader_decision}

Debate instructions:
- Integrate opportunity and risk views around tomorrow morning's exit liquidity, not a long holding period.
- Distinguish hard veto risks vs manageable risks. Hard veto examples: ST/*ST, suspension risk, major negative disclosure, limit-down exit risk, obvious capital flight, severe tool/data gaps.
- Check whether at least two of these support the setup: main theme/leader strength, capital-flow confirmation, healthy volume-price structure, fresh catalyst, disclosure clean-up.
- Challenge weak assumptions from both aggressive and conservative sides, especially when analysts report missing_critical_data, Contract Fulfilled=false, or diagnostic fallback.
- Provide balanced position sizing, stop-loss, and next-morning take-profit/exit triggers that still require human review.
- State a neutral confidence percentage (0-100%) and explain any confidence haircut from missing key indicators or low tool coverage.

Inputs:
Market report: {market_research_report}
Sentiment report: {sentiment_report}
News/policy report: {news_report}
Fundamentals report: {fundamentals_report}
Capital flow/chip report: {capital_flow_report}
Disclosure/research report: {disclosure_report}
History: {history}
Aggressive latest: {current_aggressive_response}
Conservative latest: {current_conservative_response}

Output should be conversational and end with a clear balanced risk conclusion for afternoon entry and tomorrow-morning exit.
"""

        response = llm.invoke(prompt)

        argument = f"Neutral Analyst: {response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
