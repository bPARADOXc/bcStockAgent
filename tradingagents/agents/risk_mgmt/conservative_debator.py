
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
        capital_flow_report = state.get("capital_flow_report", "")
        disclosure_report = state.get("disclosure_report", "")

        trader_decision = state["trader_investment_plan"]

        prompt = f"""As the Conservative Risk Analyst in a China A-share overnight-swing context, prioritize capital protection and rule-compliant execution.
The trade horizon is short: buy this afternoon/near the close, sell tomorrow morning. Treat overnight gap risk and next-morning exit risk as first-class risks.

Trader advisory decision:
{trader_decision}

Debate instructions:
- Evaluate hard veto risks first: ST/*ST, suspension/delisting signals, severe liquidity risk, major negative disclosure, regulatory inquiry, pledge/reduction/unlock pressure, limit-down exit failure.
- Evaluate execution risk under A-share rules: T+1 inability to same-day exit, chasing near limit-up, next-morning liquidity collapse, weak auction/late-session acceptance.
- Penalize setups where key short-term data is missing: K-line/turnover/amount, main funds, industry/theme strength, news/disclosure, LHB/margin/block-trade/chip overhang when relevant.
- Treat Contract Fulfilled=false, unavailable tools, or diagnostic fallback as evidence-quality risk, not as proof that the risk is absent.
- Rebut aggressive/neutral assumptions where downside is underpriced; name the exact condition that would remove the veto.
- Ensure recommendations preserve human-review-first workflow, and state a conservative confidence percentage (0-100%).

Inputs:
Market report: {market_research_report}
Sentiment report: {sentiment_report}
News/policy report: {news_report}
Fundamentals report: {fundamentals_report}
Capital flow/chip report: {capital_flow_report}
Disclosure/research report: {disclosure_report}
History: {history}
Aggressive latest: {current_aggressive_response}
Neutral latest: {current_neutral_response}

Output should be conversational but explicit about risk triggers, no-trade conditions, and tomorrow-morning exit triggers.
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
