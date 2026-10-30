"""A-share research example. Configure .env before running python main.py."""

from copy import deepcopy

from dotenv import load_dotenv

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


def main():
    load_dotenv()
    config = deepcopy(DEFAULT_CONFIG)
    config["provider_fallback_enabled"] = False
    config["output_language"] = "Chinese"
    # Set llm_provider, quick_think_llm and deep_think_llm here if needed.
    agent = TradingAgentsGraph(debug=False, config=config)
    # Historical dates do not guarantee point-in-time data for every source.
    # Research only: no broker orders are submitted.
    state, signal = agent.propagate("600519.SH", "2026-10-29")
    print("最终信号：", signal)
    print(state["trader_investment_plan"])
    print(state["final_trade_decision"])


if __name__ == "__main__":
    main()
