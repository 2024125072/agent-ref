"""agent_loop.py 에서 planer 부분을 분리한 부분"""

from __future__ import annotations

from typing import Any, Callable

from agent.core.state import AgentState, Message, PlanStep, create_plan_step
from agent.core.contexts import build_planner_context
from .common import MAX_PLAN_STEPS, add_trace, call_json, compact_plan, require_task, show_context


def normalize_initial_plan(raw_steps: Any) -> list[PlanStep]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("Planner output must contain a non-empty 'steps' list.")
    if len(raw_steps) > MAX_PLAN_STEPS:
        raise ValueError(
            f"Planner returned {len(raw_steps)} steps but at most "
            f"{MAX_PLAN_STEPS} are allowed. Merge related subtasks into "
            "fewer, self-contained steps."
        )

    normalized: list[PlanStep] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise ValueError("Each plan step must be a JSON object.")

        instruction = str(raw_step.get("instruction", "")).strip()
        depends_on = raw_step.get("depends_on", [])
        if not instruction:
            raise ValueError(f"Plan step {index} has no instruction.")
        if not isinstance(depends_on, list) or not all(
            isinstance(item, int) and 1 <= item < index for item in depends_on
        ):
            raise ValueError(f"Plan step {index} has invalid dependencies.")

        normalized.append(
            create_plan_step(index, instruction, sorted(set(depends_on)))
        )
    return normalized


def create_plan(
    client: Any,
    model: str,
    state: AgentState,
    current_turn: list[Message],
    recent_turns: int | None,
    use_summary: bool,
    debug: bool,
    *,
    build_context: Callable[[AgentState, list[Message], int | None, bool], list[Message]] = build_planner_context,
) -> None:
    task = require_task(state)
    context = build_context(state, current_turn, recent_turns, use_summary)
    show_context("PLANNER", context, debug)
    task["plan"] = call_json(
        client,
        model,
        context,
        state,
        validate=lambda output: normalize_initial_plan(output.get("steps")),
    )
    task["current_plan_step_id"] = task["plan"][0]["id"]
    add_trace(state, "plan_created", plan=compact_plan(state))
