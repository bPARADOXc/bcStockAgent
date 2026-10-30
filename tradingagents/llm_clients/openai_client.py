import os
from typing import Any, Optional

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from .base_client import BaseLLMClient, normalize_content
from .validators import validate_model


class NormalizedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with normalized content output.

    The Responses API returns content as a list of typed blocks
    (reasoning, text, etc.). This normalizes to string for consistent
    downstream handling.
    """

    preserve_reasoning_content: bool = False

    def invoke(self, input, config=None, **kwargs):
        return normalize_content(super().invoke(input, config, **kwargs))

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)

        if not self.preserve_reasoning_content:
            return result

        response_dict = (
            response
            if isinstance(response, dict)
            else response.model_dump(
                exclude={"choices": {"__all__": {"message": {"parsed"}}}}
            )
        )
        choices = response_dict.get("choices") or []

        for generation, choice in zip(result.generations, choices):
            message = choice.get("message", {}) if isinstance(choice, dict) else {}
            reasoning_content = message.get("reasoning_content")
            if reasoning_content is None:
                continue

            lc_message = generation.message
            if isinstance(lc_message, AIMessage):
                lc_message.additional_kwargs["reasoning_content"] = reasoning_content

        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        if not self.preserve_reasoning_content or "messages" not in payload:
            return payload

        messages = self._convert_input(input_).to_messages()
        for source_message, payload_message in zip(messages, payload["messages"]):
            if not isinstance(source_message, AIMessage):
                continue
            reasoning_content = source_message.additional_kwargs.get(
                "reasoning_content"
            )
            if reasoning_content is not None:
                payload_message["reasoning_content"] = reasoning_content

        return payload

    def with_structured_output(self, schema, *, method=None, **kwargs):
        """Wrap with structured output, defaulting to function_calling for OpenAI.

        langchain-openai's Responses-API-parse path (the default for json_schema
        when use_responses_api=True) calls response.model_dump(...) on the OpenAI
        SDK's union-typed parsed response, which makes Pydantic emit ~20
        PydanticSerializationUnexpectedValue warnings per call. The function-calling
        path returns a plain tool-call shape that does not trigger that
        serialization, so it is the cleaner choice for our combination of
        use_responses_api=True + with_structured_output. Both paths use OpenAI's
        strict mode and produce the same typed Pydantic instance.
        """
        if method is None:
            method = "function_calling"
        return super().with_structured_output(schema, method=method, **kwargs)

# Kwargs forwarded from user config to ChatOpenAI
_PASSTHROUGH_KWARGS = (
    "timeout", "max_retries", "reasoning_effort",
    "api_key", "callbacks", "http_client", "http_async_client",
)

# Provider base URLs, API key env vars, and optional base URL env overrides
_PROVIDER_CONFIG = {
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY", None),
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY", None),
    "qwen": (
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "DASHSCOPE_API_KEY",
        "DASHSCOPE_BASE_URL",
    ),
    "glm": ("https://api.z.ai/api/paas/v4/", "ZHIPU_API_KEY", None),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", None),
    "ollama": ("http://localhost:11434/v1", None, None),
}


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI, Ollama, OpenRouter, and xAI providers.

    For native OpenAI models, uses the Responses API (/v1/responses) which
    supports reasoning_effort with function tools across all model families
    (GPT-4.1, GPT-5). Third-party compatible providers (xAI, OpenRouter,
    Ollama) use standard Chat Completions.
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        provider: str = "openai",
        **kwargs,
    ):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance."""
        self.warn_if_unknown_model()
        llm_kwargs = {"model": self.model}
        explicit_api_key = self.kwargs.get("api_key")

        # Provider-specific base URL and auth
        if self.provider in _PROVIDER_CONFIG:
            default_base_url, api_key_env, base_url_env = _PROVIDER_CONFIG[self.provider]
            env_base_url = os.environ.get(base_url_env) if base_url_env else None
            llm_kwargs["base_url"] = self.base_url or env_base_url or default_base_url
            if api_key_env:
                api_key = explicit_api_key or os.environ.get(api_key_env)
                if api_key:
                    llm_kwargs["api_key"] = api_key
                else:
                    raise RuntimeError(
                        f"Missing {api_key_env} for provider '{self.provider}'. "
                        f"Set {api_key_env} in your environment or .env file. "
                        f"OPENAI_API_KEY is not used for provider '{self.provider}'."
                    )
            else:
                llm_kwargs["api_key"] = "ollama"
        elif self.base_url:
            llm_kwargs["base_url"] = self.base_url

        # Forward user-provided kwargs
        for key in _PASSTHROUGH_KWARGS:
            if key == "api_key" and self.provider in _PROVIDER_CONFIG:
                continue
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        # Native OpenAI: use Responses API for consistent behavior across
        # all model families. Third-party providers use Chat Completions.
        if self.provider == "openai":
            llm_kwargs["use_responses_api"] = True

        if self.provider == "deepseek":
            llm_kwargs["preserve_reasoning_content"] = True

        return NormalizedChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """Validate model for the provider."""
        return validate_model(self.provider, self.model)
