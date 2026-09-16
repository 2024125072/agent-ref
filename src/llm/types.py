from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class ChatOptions:
    # Provider 공통 옵션
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    stop: list[str] | None = None

    # Provider 전용 옵션
    #
    # Ollama 예:
    # {
    #     "think": True,
    #     "keep_alive": "30m",
    #     "options": {
    #         "top_k": 40
    #     }
    # }
    #
    # OpenAI/vLLM 예:
    # {
    #     "extra_body": {
    #         "top_k": 40
    #     }
    # }
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None

    def to_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": self.content or "",
        }

        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                for call in self.tool_calls
            ]

        return message