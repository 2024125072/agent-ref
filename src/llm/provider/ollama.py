from typing import Any

from ..base import BaseLLM, build_function_tools
from ..types import ChatOptions, LLMResponse, ToolCall


class OllamaLLM(BaseLLM):

    def __init__(
        self,
        host: str = "http://localhost:11434",
    ):
        try:
            from ollama import Client
        except ImportError as e:
            raise RuntimeError(
                "Ollama provider를 사용하려면 "
                "'ollama' 패키지가 필요합니다. "
                "pip install ollama"
            ) from e

        self.host = host
        self.client = Client(host=host)

    def get_available_models(self) -> list[str]:
        response = self.client.list()

        return [model.model for model in response.models if model.model]

    def list(self) -> list[str]:
        return self.get_available_models()

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: ChatOptions | None = None,
    ) -> LLMResponse:

        options = options or ChatOptions()

        api_messages = self._convert_messages(messages)
        api_tools = build_function_tools(tools)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
        }

        if api_tools:
            kwargs["tools"] = api_tools

        # -----------------------------
        # 공통 옵션 → Ollama options 변환
        # -----------------------------

        ollama_options: dict[str, Any] = {}

        if options.temperature is not None:
            ollama_options["temperature"] = options.temperature

        if options.top_p is not None:
            ollama_options["top_p"] = options.top_p

        if options.max_tokens is not None:
            ollama_options["num_predict"] = options.max_tokens

        if options.seed is not None:
            ollama_options["seed"] = options.seed

        if options.stop is not None:
            ollama_options["stop"] = options.stop

        # Ollama 전용 generation options
        #
        # extra={
        #     "options": {
        #         "top_k": 40,
        #         "repeat_penalty": 1.1
        #     }
        # }
        extra_options = options.extra.get("options")

        if isinstance(extra_options, dict):
            ollama_options.update(extra_options)

        if ollama_options:
            kwargs["options"] = ollama_options

        # -----------------------------
        # Ollama top-level 전용 옵션
        # -----------------------------

        top_level_keys = (
            "think",
            "format",
            "keep_alive",
            "logprobs",
            "top_logprobs",
        )

        for key in top_level_keys:
            if key in options.extra:
                kwargs[key] = options.extra[key]

        response = self.client.chat(**kwargs)

        message = response.message

        tool_calls: list[ToolCall] = []

        if message.tool_calls:
            for call in message.tool_calls:
                arguments = call.function.arguments or {}

                tool_calls.append(
                    ToolCall(
                        name=call.function.name,
                        arguments=dict(arguments),
                    )
                )

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
        )

    def _convert_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:

        result: list[dict[str, Any]] = []

        for message in messages:
            role = message["role"]

            # Assistant가 Tool을 호출했던 메시지
            if role == "assistant" and message.get("tool_calls"):

                tool_calls = []

                for call in message["tool_calls"]:
                    tool_calls.append(
                        {
                            "function": {
                                "name": call["name"],
                                "arguments": call["arguments"],
                            }
                        }
                    )

                result.append(
                    {
                        "role": "assistant",
                        "content": message.get("content", ""),
                        "tool_calls": tool_calls,
                    }
                )

            # Tool 실행 결과
            elif role == "tool":

                tool_message: dict[str, Any] = {
                    "role": "tool",
                    "content": str(message["content"]),
                }

                if "name" in message:
                    tool_message["tool_name"] = message["name"]

                result.append(tool_message)

            else:

                result.append(
                    {
                        "role": role,
                        "content": message.get("content", ""),
                    }
                )

        return result