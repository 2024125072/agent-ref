"""세션 도구 뷰: 기존 Registry의 실시간 조회 + 작업 전용 도구.

외부 도구는 항상 기존 ToolExecutor로 실행한다. Host의 Registry는 수정하지 않는다.
"""
from __future__ import annotations

import copy
from typing import Any, Awaitable, Callable

from .core import ToolExecutorLike, ToolRegistryLike, invoke

HOST_ASK_SCHEMA = {
    "name": "host_ask",
    "description": "Ask the host for a required decision and wait for its answer.",
    "parameters": {
        "type": "object",
        "properties": {"question": {"type": "string"}, "context": {"type": "string"}},
        "required": ["question"], "additionalProperties": False,
    },
}
MEMORY_WRITE_SCHEMA = {
    "name": "memory_write",
    "description": (
        "Write concise task-local memory that remains available during this task and is returned "
        "to the host with the final result. Use for durable facts, decisions, constraints, and "
        "important discoveries; do not store transient chatter."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "kind": {"type": "string"},
            "source_refs": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["content", "kind"], "additionalProperties": False,
    },
}
CONVERSATION_SEARCH_SCHEMA = {
    "name": "conversation_search",
    "description": (
        "Search the append-only original transcript of this task, including older messages hidden "
        "from the current prompt by context compaction. Returns stable message_index references and "
        "snippets. Use this when an exact older detail may be missing from the summary."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["query"], "additionalProperties": False,
    },
}
CONVERSATION_READ_SCHEMA = {
    "name": "conversation_read",
    "description": (
        "Read an exact chunk of one message from the append-only original task transcript by the "
        "message_index returned from conversation_search. Increase char_offset to continue reading "
        "a long message."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message_index": {"type": "integer", "minimum": 0},
            "char_offset": {"type": "integer", "minimum": 0},
            "max_chars": {"type": "integer", "minimum": 256, "maximum": 6000},
        },
        "required": ["message_index"], "additionalProperties": False,
    },
}


class SessionTools:
    def __init__(self, registry: ToolRegistryLike, executor: ToolExecutorLike,
                 host_ask: Callable[..., Awaitable[Any]],
                 memory_write: Callable[..., Awaitable[Any]],
                 conversation_search: Callable[..., Awaitable[Any]],
                 conversation_read: Callable[..., Awaitable[Any]]):
        self.registry = registry
        self.executor = executor
        self._local = {
            "host_ask": (HOST_ASK_SCHEMA, host_ask),
            "memory_write": (MEMORY_WRITE_SCHEMA, memory_write),
            "conversation_search": (CONVERSATION_SEARCH_SCHEMA, conversation_search),
            "conversation_read": (CONVERSATION_READ_SCHEMA, conversation_read),
        }
        self.schemas()  # 예약 이름 충돌은 실행 전에 검출한다.

    @property
    def version(self) -> int | None:
        return getattr(self.registry, "version", None)

    def schemas(self) -> list[dict[str, Any]]:
        schemas = copy.deepcopy(self.registry.schemas())
        names: set[str] = set()
        for schema in schemas:
            name = schema["name"]
            if name in names or name in self._local:
                raise ValueError(f"duplicate or reserved tool name: {name}")
            names.add(name)
        return schemas + [copy.deepcopy(x[0]) for x in self._local.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name in self._local:
            return await self._local[name][1](**arguments)
        return await invoke(self.executor.execute, name=name, arguments=copy.deepcopy(arguments))
