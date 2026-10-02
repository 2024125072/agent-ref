"""기존 LLM 인터페이스를 사용해 판단 한 번만 수행한다. 루프/도구 실행 없음."""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
from typing import Any, Callable, Protocol


class LLMProvider(Protocol):
    def chat(self, model: str, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]] | None = None,
             options: Any = None) -> Any: ...


class ToolRegistryLike(Protocol):
    def schemas(self) -> list[dict[str, Any]]: ...


class ToolExecutorLike(Protocol):
    def execute(self, name: str, arguments: dict[str, Any]) -> Any: ...


async def invoke(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """동기 I/O는 스레드로 분리한다. 스레드 강제 종료를 보장하지 않는다.

    async 함수 또는 sync 함수가 반환한 awaitable은 이벤트 루프에서 await한다.
    UI 스레드에 고정된 함수나 비협력적인 CPU 작업에는 별도 adapter가 필요하다.
    """
    if inspect.iscoroutinefunction(function):
        result = function(*args, **kwargs)
    else:
        result = await asyncio.to_thread(function, *args, **kwargs)
    return await result if inspect.isawaitable(result) else result


class AgentCore:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    async def step(self, *, model: str, messages: list[dict[str, Any]],
                   tools: list[dict[str, Any]], options: Any = None) -> Any:
        response = await invoke(
            self.provider.chat,
            model=model,
            messages=copy.deepcopy(messages),
            tools=copy.deepcopy(tools),
            options=copy.deepcopy(options),
        )
        # 기존 LLMResponse/ToolCall과 호환되는 구조만 요구한다.
        if not hasattr(response, "content") or not hasattr(response, "tool_calls"):
            raise TypeError("provider must return an LLMResponse-like object")
        if response.content is not None and not isinstance(response.content, str):
            raise TypeError("response.content must be str or None")
        if not isinstance(response.tool_calls, (list, tuple)):
            raise TypeError("response.tool_calls must be a sequence")
        ids: set[str] = set()
        for call in response.tool_calls:
            if not isinstance(call.id, str) or not call.id or call.id in ids:
                raise ValueError("tool call ids must be nonempty and unique in a response")
            ids.add(call.id)
            if not isinstance(call.name, str) or not call.name:
                raise ValueError("tool name must be a nonempty string")
            if not isinstance(call.arguments, dict):
                raise TypeError("tool arguments must be an object")
            if not all(isinstance(key, str) for key in call.arguments):
                raise TypeError("tool argument keys must be strings")
            json.dumps(call.arguments, allow_nan=False)
        return copy.deepcopy(response)
