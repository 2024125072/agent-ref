"""기존 agent_loop.py 에서 progress_checker 역할을 분리한 부분"""

from __future__ import annotations

from typing import Any, Callable

from agent.core.state import AgentState, Message, PlanStep, ProgressResult, StepResult
from agent.core.contexts import build_progress_context
from .common import add_trace, call_json, get_current_plan_step, show_context



def validate_progress_output(output: dict[str, Any]) -> dict[str, str]:
    decision = output.get("decision")
    if decision not in {"continue", "replan", "finish"}:
        raise ValueError(f"Invalid progress decision: {decision}")
    reason = str(output.get("reason", "")).strip()
    if decision == "replan" and not reason:
        raise ValueError("Replan decision must include a reason.")
    return {"decision": decision, "reason": reason}


def check_progress(
    client: Any,
    model: str,
    state: AgentState,
    step_result: StepResult,
    debug: bool,
    *,
    build_context: Callable[[AgentState, PlanStep, StepResult], list[Message]] = build_progress_context,
) -> ProgressResult:
    """
    기존 prograss_checker랑 흐름은 같으나 내가 만든 ProgressResult를 반환하도록 수정
    """
    step = get_current_plan_step(state)
    if step is None:
        raise RuntimeError("Progress check requires a current plan step.")

    context = build_context(state, step, step_result)
    show_context("PROGRESS CHECKER", context, debug)
    result: ProgressResult = call_json(
        client, model, context, state, validate=validate_progress_output
    )
    add_trace(state, "progress_checked", plan_step_id=step["id"], **result)
    return result
