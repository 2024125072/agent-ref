"""
agent_loop.py 에서 plan_step을 실행하는 부분을 가져온 파일
"""

from __future__ import annotations

import json
from typing import Any, Callable

from agent.core.state import AgentState, Message, PlanStep, StepResult
from agent.core.contexts import build_executor_context
from .common import (
    MAX_AGENT_LOOP_ITERATIONS,
    add_trace,
    assistant_message_to_dict,
    get_current_plan_step,
    show_context,
)


def execute_plan_step(
    client: Any,
    model: str,
    state: AgentState,
    debug: bool,
    *,
    tools: list[dict[str, Any]] | None = None,
    execute_tool: Callable[[str, dict[str, Any], AgentState, PlanStep], dict[str, Any]] | None = None,
    build_context: Callable[[AgentState, PlanStep], list[Message]] = build_executor_context,
) -> StepResult:
    """
    기존 executor 부분 코드와 동작은 동일한데, 하나의 파일을 모듈로 나누면서 호환성을 위해 일부 수정됨
    """
    if tools is None or execute_tool is None:
        # 도구 불러오기
        from agent.tools import TOOLS, execute_tool as default_execute_tool
        if tools is None:
            tools = TOOLS
        if execute_tool is None:
            execute_tool = default_execute_tool

    step = get_current_plan_step(state)
    if step is None:
        return {"status": "failed", "content": "No current plan step exists."}

    step["status"] = "in_progress"
    add_trace(
        state,
        "plan_step_started",
        plan_step_id=step["id"],
        instruction=step["instruction"],
        depends_on=step["depends_on"],
    )

    for iteration in range(1, MAX_AGENT_LOOP_ITERATIONS + 1):
        context = build_context(state, step)
        show_context(
            f"EXECUTOR / PLAN STEP {step['id']} / ITERATION {iteration}",
            context,
            debug,
        )
        response = client.chat.completions.create(
            model=model,
            messages=context,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
        assistant_message = response.choices[0].message
        step["messages"].append(assistant_message_to_dict(assistant_message))
        add_trace(
            state,
            "agent_loop_iteration",
            plan_step_id=step["id"],
            iteration=iteration,
            tool_call_count=len(assistant_message.tool_calls or []),
        )

        if not assistant_message.tool_calls:
            return {
                "status": "completed",
                "content": (assistant_message.content or "").strip(),
            }

        for tool_call in assistant_message.tool_calls:
            name = tool_call.function.name
            try:
                args = json.loads(tool_call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
                result = execute_tool(name, args, state, step)
                add_trace(
                    state,
                    "tool_called",
                    plan_step_id=step["id"],
                    tool=name,
                    arguments=args,
                    result_summary=result,
                )
            except Exception as error:
                result = {"status": "error", "message": str(error)}
                add_trace(
                    state,
                    "tool_error",
                    plan_step_id=step["id"],
                    tool=name,
                    message=str(error),
                )
            step["messages"].append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return {
        "status": "failed",
        "content": (
            "The plan-step executor exceeded "
            f"{MAX_AGENT_LOOP_ITERATIONS} agent loop iterations."
        ),
    }
