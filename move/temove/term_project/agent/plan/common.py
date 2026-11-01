"""
agent_loop.py에서 분리한 여러 공용 함수를 모아둔 파일
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from agent.core.state import AgentState, PlanStep
from agent.core.contexts import MAX_PLAN_STEPS

RECENT_TURNS = 2
MAX_REPLANS = 2
MAX_AGENT_LOOP_ITERATIONS = 6
MAX_TOTAL_LLM_CALLS = 30
MAX_JSON_ATTEMPTS = 3


class TurnBudgetExceeded(RuntimeError):
    """이 턴에 허용된 LLM 호출 예산을 다 썼다.

    run_turn이 잡아서 크래시 대신 '지금까지의 증거로 답하는' 경로로 강등한다.
    """


def require_task(state: AgentState):
    task = state["current_task"]
    if task is None:
        raise ValueError("current_task must be initialized before planning.")
    return task


def add_trace(state: AgentState, event: str, **details: Any) -> None:
    require_task(state)["trace"].append({"event": event, **details})


def get_plan_step(state: AgentState, plan_step_id: int) -> PlanStep | None:
    for step in require_task(state)["plan"]:
        if step["id"] == plan_step_id:
            return step
    return None


def get_current_plan_step(state: AgentState) -> PlanStep | None:
    step_id = require_task(state)["current_plan_step_id"]
    return None if step_id is None else get_plan_step(state, step_id)


def next_pending_plan_step(state: AgentState) -> PlanStep | None:
    return next((step for step in require_task(state)["plan"] if step["status"] == "pending"), None)


def compact_plan(state: AgentState) -> list[dict[str, Any]]:
    return [
        {
            "id": step["id"],
            "instruction": step["instruction"],
            "depends_on": step["depends_on"],
            "status": step["status"],
        }
        for step in require_task(state)["plan"]
    ]


def count_llm_call(state: AgentState) -> None:
    task = require_task(state)
    task["llm_call_count"] += 1
    if task["llm_call_count"] > MAX_TOTAL_LLM_CALLS:
        raise TurnBudgetExceeded("The turn exceeded MAX_TOTAL_LLM_CALLS.")


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("The model must return one JSON object.")
    return value


def call_json(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    state: AgentState,
    validate: Callable[[dict[str, Any]], Any] | None = None,
) -> Any:
    conversation = list(messages)
    last_error: Exception | None = None

    for _ in range(MAX_JSON_ATTEMPTS):
        count_llm_call(state)
        response = client.chat.completions.create(
            model=model,
            messages=conversation,
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        try:
            output = parse_json_object(content)
            return validate(output) if validate else output
        except (json.JSONDecodeError, ValueError) as error:
            last_error = error
            conversation += [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        f"Your previous output was invalid: {error} "
                        "Return corrected JSON only, following the required schema."
                    ),
                },
            ]

    raise ValueError(
        f"Invalid JSON output after {MAX_JSON_ATTEMPTS} attempts: {last_error}"
    )


def assistant_message_to_dict(message: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]
    return result


def show_context(
    label: str, 
    context: list[dict[str, Any]], 
    debug: bool
) -> None:

    if not debug:
        return
    print(f"\n===== {label} CONTEXT =====")
    for message in context:
        print(message["role"], ":", message.get("content", ""))
