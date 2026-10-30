"""Research Manager: turns the bull/bear debate into a structured investment plan for the trader."""

from __future__ import annotations

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])
        history = state["investment_debate_state"].get("history", "")

        investment_debate_state = state["investment_debate_state"]

        prompt = f"""As the Research Manager and debate facilitator, your role is to evaluate this round of debate and deliver a clear, actionable overnight-swing plan for the trader.
The system is mainly used for short-term A-share trades: buy this afternoon/near the close, sell tomorrow morning. Do not drift into a long-term investment recommendation.

{instrument_context}

---

**Rating Scale** (use exactly one, interpreted for the overnight horizon):
- **Buy**: Conditions support a small, rule-bound afternoon/close entry for tomorrow-morning exit
- **Overweight**: Constructive but not clean enough for a full signal; only consider reduced sizing
- **Hold**: No new entry; maintain observation or existing plan
- **Underweight**: Avoid new entry or reduce if already holding
- **Sell**: Exit/avoid; overnight risk dominates

Commit to a clear stance whenever the debate's strongest arguments warrant one; reserve Hold for genuinely balanced evidence.
Require an explicit confidence percentage from 0-100. Lower confidence when key indicators are missing, when analysts report Contract Fulfilled=false, or when tool coverage is below three quarters.
The plan must name the minimum conditions for an afternoon entry and tomorrow-morning exit triggers.

---

**Debate History:**
{history}"""

        investment_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
