"""Host가 사용하는 진입점. 작업/사용자 간 영구 상태를 소유하지 않는다."""
from __future__ import annotations

from typing import Any, Callable

from .core import AgentCore, LLMProvider, ToolExecutorLike, ToolRegistryLike
from .runtime import TaskRuntime
from .session import TaskSession
from .types import AgentLimits, TaskRequest


class ProblemSolver:
    def __init__(self, provider: LLMProvider):
        self.core = AgentCore(provider)

    def create_task(self, *, request: TaskRequest, model: str,
                    registry: ToolRegistryLike, executor: ToolExecutorLike,
                    limits: AgentLimits | None = None, options: Any = None,
                    model_selector: Callable[[int], str] | None = None) -> TaskSession:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a nonempty string")
        if not isinstance(request, TaskRequest):
            raise TypeError("request must be TaskRequest")
        session = TaskSession()
        session._runtime = TaskRuntime(
            session=session, core=self.core, request=request, registry=registry,
            executor=executor, model=model, limits=limits or AgentLimits(),
            options=options, model_selector=model_selector,
        )
        return session
