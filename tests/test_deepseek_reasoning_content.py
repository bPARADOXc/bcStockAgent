import pytest
from langchain_core.messages import AIMessage

from tradingagents.llm_clients.openai_client import NormalizedChatOpenAI, OpenAIClient


def test_deepseek_client_preserves_reasoning_content(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    llm = OpenAIClient(
        "deepseek-v4-flash",
        provider="deepseek",
    ).get_llm()

    assert llm.preserve_reasoning_content is True


def test_deepseek_requires_deepseek_key_not_openai_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "wrong-provider-key")

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        OpenAIClient("deepseek-v4-flash", provider="deepseek").get_llm()


def test_reasoning_content_round_trips_for_chat_completions():
    llm = NormalizedChatOpenAI(
        model="deepseek-v4-flash",
        api_key="test-key",
        base_url="https://api.deepseek.com",
        preserve_reasoning_content=True,
    )

    response = {
        "id": "chatcmpl-test",
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "Need current market data before final answer.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_stock_data",
                                "arguments": '{"symbol":"600519"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }

    chat_result = llm._create_chat_result(response)
    ai_message = chat_result.generations[0].message

    assert ai_message.additional_kwargs["reasoning_content"] == (
        "Need current market data before final answer."
    )

    payload = llm._get_request_payload([ai_message])

    assert payload["messages"][0]["reasoning_content"] == (
        "Need current market data before final answer."
    )
