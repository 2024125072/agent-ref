"""기존 agent_loop.py 에서 replan 부분을 분리한 부분"""

from __future__ import annotations

from typing import Any, Callable

from agent.core.state import AgentState, Message, PlanStep, create_plan_step
from agent.core.contexts import build_replanner_context
from .common import (
    MAX_REPLANS,
    MAX_PLAN_STEPS,
    add_trace,
    call_json,
    get_current_plan_step,
    require_task,
    show_context,
)



def resolve_replanned_dependencies(
    depends_on: Any,
    step_id: int,
    completed_ids: set[int],
    id_map: dict[int, int],
) -> list[int]:
    if not isinstance(depends_on, list):
        raise ValueError(f"Replanned step {step_id} has invalid dependencies.")

    resolved: set[int] = set()
    for dependency in depends_on:
        if isinstance(dependency, int) and dependency in completed_ids:
            resolved.add(dependency)
        elif (
            isinstance(dependency, int)
            and dependency in id_map
            and id_map[dependency] < step_id
        ):
            resolved.add(id_map[dependency])
        else:
            raise ValueError(
                f"Replanned step {step_id} has invalid dependency "
                f"{dependency!r}. Dependencies must be completed step IDs "
                "or IDs of earlier new steps."
            )
    return sorted(resolved)


def normalize_replanned_steps(
    raw_steps: Any,
    state: AgentState,
) -> list[PlanStep]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("Replanner must return non-empty 'remaining_steps'.")
    if len(raw_steps) > MAX_PLAN_STEPS:
        raise ValueError(
            f"Replanner returned {len(raw_steps)} steps but at most "
            f"{MAX_PLAN_STEPS} are allowed. Merge related subtasks into "
            "fewer, self-contained steps."
        )
    if not all(isinstance(raw_step, dict) for raw_step in raw_steps):
        raise ValueError("Each replanned step must be a JSON object.")

    plan = require_task(state)["plan"]
    completed_ids = {step["id"] for step in plan if step["status"] == "completed"}
    first_id = max((step["id"] for step in plan), default=0) + 1

    # IDs suggested by the LLM are advisory.  Assign unique sequential IDs.
    id_map = {
        raw_step["id"]: first_id + offset
        for offset, raw_step in enumerate(raw_steps)
        if isinstance(raw_step.get("id"), int)
        and raw_step["id"] not in completed_ids
    }

    normalized: list[PlanStep] = []
    for step_id, raw_step in enumerate(raw_steps, start=first_id):
        instruction = str(raw_step.get("instruction", "")).strip()
        if not instruction:
            raise ValueError(f"Replanned step {step_id} has no instruction.")
        dependencies = resolve_replanned_dependencies(
            raw_step.get("depends_on", []), step_id, completed_ids, id_map
        )
        normalized.append(create_plan_step(step_id, instruction, dependencies))
    return normalized


def replan(
    client: Any,
    model: str,
    state: AgentState,
    reason: str,
    debug: bool,
    *,
    build_context: Callable[[AgentState, PlanStep, str], list[Message]] = build_replanner_context,
) -> None:
    """
    기존 코드에서 내 버전으로 replan 부분을 분리하면서 호환성만 수정함
    """
    task = require_task(state)
    if task["replan_count"] >= MAX_REPLANS:
        raise RuntimeError("The turn exceeded MAX_REPLANS.")
    
    failed_step = get_current_plan_step(state)
    if failed_step is None:
        raise RuntimeError("Replanning requires a current plan step.")

    context = build_context(state, failed_step, reason)
    show_context("REPLANNER", context, debug)
    new_steps = call_json(
        client,
        model,
        context,
        state,
        validate=lambda output: normalize_replanned_steps(
            output.get("remaining_steps"), state
        ),
    )

    failed_step["status"] = "replaced"
    for step in task["plan"]:
        if step["status"] == "pending":
            step["status"] = "replaced"

    task["plan"].extend(new_steps)
    task["current_plan_step_id"] = new_steps[0]["id"]
    task["plan_revision"] += 1
    task["replan_count"] += 1
    add_trace(
        state,
        "plan_revised",
        reason=reason,
        new_steps=[
            {
                "id": step["id"],
                "instruction": step["instruction"],
                "depends_on": step["depends_on"],
            }
            for step in new_steps
        ],
    )
