""" 
이게 이번 과제의 핵심 파일.
기존 agent 를 langgraph 기반으로 바꾸는 부분.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from functools import partial
from typing import Any, Callable, Literal

from agent.core.contexts import build_final_context, build_summary_context
from agent.core.state import AgentState, create_state, create_task_state
from agent.plan.checker import check_progress
from agent.plan.common import (
    MAX_PLAN_STEPS,
    MAX_REPLANS,
    RECENT_TURNS,
    TurnBudgetExceeded,
    add_trace,
    call_json,
    compact_plan,
    get_current_plan_step,
    next_pending_plan_step,
    show_context,
)
from agent.plan.executor import execute_plan_step
from agent.plan.planner import create_plan, normalize_initial_plan
from agent.plan.replanner import replan


TURN_ERRORS = (TurnBudgetExceeded, ValueError, RuntimeError)


def create_turn_input(
    user_message: str, previous_state: AgentState | None = None
) -> AgentState:
    """
    새 turn을 시작하기 위한 입력 state를 생성. 이전 turn이 진행 중이면 오류 발생.
    """
    if not isinstance(user_message, str) or not user_message.strip():
        raise ValueError("user_message must be a non-empty string.")

    if previous_state is not None and previous_state.get("turn_status") == "running":
        raise ValueError("Finish or resume the current turn before starting another.")

    result = deepcopy(previous_state) if previous_state is not None else create_state()
    result["current_turn"] = [{"role": "user", "content": user_message}]
    result["current_task"] = None
    result["step_result"] = None
    result["progress"] = None
    result["final_response"] = None
    result["review_feedback"] = None
    result["turn_status"] = "idle"
    return result


def _task_failed(working: AgentState, error: Exception) -> None:
    """실패한 task를 기록하고 turn_status를 failed로 설정."""
    task = working["current_task"]
    if task is None:
        raise RuntimeError("Cannot report a task failure before task initialization.")
    task["aborted_reason"] = str(error)
    add_trace(working, "turn_aborted", reason=str(error))
    working["turn_status"] = "failed"


def planner_node(
    state: AgentState,
    *,
    client: Any,
    model: str,
    recent_turns: int | None,
    use_summary: bool,
    debug: bool,
) -> dict[str, Any]:
    """처음에 create_plan()을 호출하는 노드임"""
    working = deepcopy(state)
    users = [message for message in working["current_turn"] if message.get("role") == "user"]
    if not users or not isinstance(users[-1].get("content"), str):
        raise ValueError("current_turn must contain a user message.")
    goal = users[-1]["content"].strip()
    if not goal:
        raise ValueError("The user message must not be empty.")

    working["current_task"] = create_task_state(goal)
    working["turn_status"] = "running"
    add_trace(working, "turn_started", goal=goal)

    try:
        create_plan(
            client, model, working, working["current_turn"],
            recent_turns, use_summary, debug,
        )
    except TURN_ERRORS as error:
        _task_failed(working, error)

    return {
        "current_task": working["current_task"],
        "step_result": None,
        "progress": None,
        "final_response": None,
        "turn_status": working["turn_status"],
    }


def route_after_planner(state: AgentState) -> Literal["review", "finalizer"]:
    """플래닝 성공하면 plan_review로, 실패하면 finalizer로 이동"""
    return "finalizer" if state["turn_status"] == "failed" else "review"


def plan_review_node(state: AgentState) -> dict[str, Any]:
    """사용자 계획 검토 전용 노드. LLM 호출과 외부 부작용은 없음.

    Resume examples:
      - {"approved": True}                          : 승인
      - {"approved": False, "feedback": "..."}      : 자연어 수정 요청
      - {"approved": False, "steps": [...]}         : 이전 JSON 수정 방식(호환용)
    """
    from langgraph.types import interrupt

    task = state["current_task"]
    if task is None or not task["plan"]:
        raise ValueError("Plan review requires a generated plan.")

    # 사용자에게 보여줄 값은 최소한으로 제한한다. 내부 상태의 status/id는 그대로 유지.
    decision = interrupt({
        "goal": task["goal"],
        "question": "이 계획을 승인하거나 수정할 내용을 입력하세요.",
        "plan": [
            {"instruction": step["instruction"], "depends_on": step["depends_on"]}
            for step in task["plan"]
        ],
    })
    if isinstance(decision, str):
        # CLI/다른 클라이언트가 문자열을 바로 넘겨도 지원한다.
        decision = {"approved": False, "feedback": decision} if decision.strip() else {"approved": True}
    if not isinstance(decision, dict):
        raise ValueError("Plan review response must be an object or text feedback.")

    working = deepcopy(state)
    revised_task = working["current_task"]
    assert revised_task is not None

    if decision.get("approved") is True:
        add_trace(working, "plan_approved")
        return {"current_task": revised_task, "review_feedback": None}

    if decision.get("approved") is False:
        # 기존 JSON 직접 수정 방식은 호환을 위해 보존한다.
        if "steps" in decision:
            old_plan = compact_plan(working)
            new_plan = normalize_initial_plan(decision["steps"])
            revised_task["plan"] = new_plan
            revised_task["current_plan_step_id"] = new_plan[0]["id"]
            revised_task["plan_revision"] += 1
            add_trace(working, "plan_edited", previous_plan=old_plan, new_plan=compact_plan(working))
            return {"current_task": revised_task, "review_feedback": None}

        feedback = decision.get("feedback")
        if not isinstance(feedback, str) or not feedback.strip():
            raise ValueError("Natural-language plan revision requires non-empty 'feedback'.")
        feedback = feedback.strip()
        add_trace(working, "plan_revision_requested", feedback=feedback)
        return {"current_task": revised_task, "review_feedback": feedback}

    raise ValueError('Plan review expects {"approved": true} or {"approved": false, "feedback": "..."}.')


def route_after_plan_review(state: AgentState) -> Literal["plan_editor", "executor"]:
    """Plan 수정 요청이면 수정 노드로, 승인된 경우 Executor로 진행한다."""
    return "plan_editor" if state.get("review_feedback") else "executor"


def plan_editor_node(
    state: AgentState, *, client: Any, model: str, debug: bool
) -> dict[str, Any]:
    """피드백을 바탕으로 계획을 새로 작성하는 노드"""
    working = deepcopy(state)
    task = working["current_task"]
    feedback = working.get("review_feedback")
    if task is None or not isinstance(feedback, str) or not feedback.strip():
        raise ValueError("Plan editor requires a task and natural-language feedback.")

    original_plan = compact_plan(working)
    context = [
        {
            "role": "system",
            "content": (
                "You revise an unexecuted Plan & Execute plan based on user feedback. "
                "Keep the user's original goal, but apply their requested changes. "
                f"Return a JSON object with 'steps' containing 1 to {MAX_PLAN_STEPS} items. "
                "Each item has only 'instruction' (nonempty string) and 'depends_on' "
                "(list of earlier 1-based step indexes). "
                "Do not fabricate document references or claim execution has occurred. "
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({
                "goal": task["goal"],
                "current_plan": original_plan,
                "revision_request": feedback,
            }, ensure_ascii=False),
        },
    ]
    show_context("PLAN EDITOR", context, debug)
    try:
        new_plan = call_json(
            client, model, context, working,
            validate=lambda output: normalize_initial_plan(output.get("steps")),
        )
        task["plan"] = new_plan
        task["current_plan_step_id"] = new_plan[0]["id"]
        task["plan_revision"] += 1
        add_trace(
            working, "plan_edited", previous_plan=original_plan,
            new_plan=compact_plan(working), feedback=feedback,
        )
    except TURN_ERRORS as error:
        _task_failed(working, error)

    return {
        "current_task": task,
        "review_feedback": None,
        "turn_status": working["turn_status"],
    }


def route_after_plan_editor(state: AgentState) -> Literal["plan_review", "finalizer"]:
    """LLM 수정 실패는 기존 실패 종료로, 성공하면 다시 사용자 승인을 요청한다."""
    return "finalizer" if state["turn_status"] == "failed" else "plan_review"


def executor_node(
    state: AgentState,
    *,
    client: Any,
    model: str,
    debug: bool,
    tools: list[dict[str, Any]] | None,
    tool_executor: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    """plan에서 현재 step을 실행하고 step_result를 반환. 실패하면 turn_status를 failed로 설정."""
    working = deepcopy(state)
    task = working["current_task"]
    if task is None:
        raise ValueError("Executor requires current_task.")
    step = get_current_plan_step(working)
    if step is None:
        return {"step_result": None, "current_task": task}

    try:
        step_result = execute_plan_step(
            client, model, working, debug,
            tools=tools, execute_tool=tool_executor,
        )

        step["result"] = step_result["content"]
        if step_result["status"] == "failed" and task["replan_count"] >= MAX_REPLANS:
            step["status"] = "failed"
            task["aborted_reason"] = step_result["content"]
            working["turn_status"] = "failed"
            add_trace(working, "replan_budget_exhausted", reason=step_result["content"])
    except TURN_ERRORS as error:
        _task_failed(working, error)
        step_result = {"status": "failed", "content": str(error)}
        step["result"] = str(error)

    return {
        "current_task": task,
        "step_result": step_result,
        "progress": None,
        "turn_status": working["turn_status"],
    }


def route_after_executor(state: AgentState) -> Literal["checker", "replanner", "finalizer"]:
    """executor 노드의 결과에 따라 다음 노드를 결정."""
    if state["turn_status"] == "failed" or state["step_result"] is None:
        return "finalizer"

    # 스텝 실패시 replanner로 이동, 성공시 checker로 이동
    if state["step_result"]["status"] == "failed":
        return "replanner"
    return "checker"


def checker_node(
    state: AgentState, *, client: Any, model: str, debug: bool
) -> dict[str, Any]:
    """plan에서 현재 step의 결과를 평가하고 progress를 반환. 실패하면 turn_status를 failed로 설정."""
    working = deepcopy(state)
    task = working["current_task"]
    result = working["step_result"]
    if task is None or result is None or result["status"] != "completed":
        raise ValueError("Checker requires a completed step_result.")
    step = get_current_plan_step(working)
    if step is None:
        raise ValueError("Checker requires a current plan step.")

    try:
        progress = check_progress(client, model, working, result, debug)
        if progress["decision"] == "replan":
            # replan 많이 하면 실패로 간주
            if task["replan_count"] >= MAX_REPLANS:
                step["status"] = "failed"
                working["turn_status"] = "failed"
                add_trace(working, "replan_budget_exhausted", reason=progress["reason"])
        else:
            step["status"] = "completed"
            if progress["decision"] == "finish":
                task["current_plan_step_id"] = None
            else:
                pending = next_pending_plan_step(working)
                task["current_plan_step_id"] = pending["id"] if pending else None
    except TURN_ERRORS as error:
        _task_failed(working, error)
        progress = None

    return {
        "current_task": task,
        "progress": progress,
        "turn_status": working["turn_status"],
    }


def route_after_checker(state: AgentState) -> Literal["executor", "replanner", "finalizer"]:
    """checker 노드의 결과에 따라 다음 노드를 결정."""
    if state["turn_status"] == "failed" or state["progress"] is None:
        return "finalizer"
    
    decision = state["progress"]["decision"]
    if decision == "replan":
        return "replanner"
    
    task = state["current_task"]
    if decision == "finish" or (task is not None and task["current_plan_step_id"] is None):
        return "finalizer"

    # step이 완료되었고 다음 step이 남아있으면 executor로 이동
    return "executor"


def replanner_node(
    state: AgentState, *, client: Any, model: str, debug: bool
) -> dict[str, Any]:
    """replan 하는 노드. 실패하면 turn_status를 failed로 설정."""
    working = deepcopy(state)
    task = working["current_task"]
    if task is None:
        raise ValueError("Replanner requires current_task.")
    reason = (
        working["step_result"]["content"]
        if working["step_result"] is not None and working["step_result"]["status"] == "failed"
        else (working["progress"] or {}).get("reason", "재계획 요청")
    )
    try:
        replan(client, model, working, reason, debug)
    except TURN_ERRORS as error:
        _task_failed(working, error)
    return {
        "current_task": task,
        "step_result": None,
        "progress": None,
        "turn_status": working["turn_status"],
    }


def route_after_replanner(state: AgentState) -> Literal["executor", "finalizer"]:
    """replanner 노드의 결과에 따라 다음 노드를 결정."""
    return "finalizer" if state["turn_status"] == "failed" else "executor"


def finalizer_node(
    state: AgentState,
    *,
    client: Any,
    model: str,
    recent_turns: int | None,
    use_summary: bool,
    debug: bool,
) -> dict[str, Any]:
    """마지막 turn에서 최종 답변을 생성하고, turn_status를 completed 또는 failed로 설정."""
    working = deepcopy(state)
    task = working["current_task"]
    if task is None:
        raise ValueError("Finalizer requires current_task.")

    context = build_final_context(working, working["current_turn"], recent_turns, use_summary)
    show_context("FINAL ANSWER", context, debug)
    # In Week 6 the final answer is excluded from llm_call_count.
    response = client.chat.completions.create(model=model, messages=context, temperature=0)
    final_answer = (response.choices[0].message.content or "").strip()

    current_turn = deepcopy(working["current_turn"])
    current_turn.append({"role": "assistant", "content": final_answer})
    add_trace(working, "turn_completed", status="failed" if working["turn_status"] == "failed" else "completed")
    completed_turns = deepcopy(working["turns"])
    completed_turns.append(deepcopy(current_turn))
    working["turns"] = completed_turns

    summary = working["summary"]
    if use_summary and recent_turns is not None:
        summary_context = build_summary_context(working, recent_turns)
        if summary_context is not None:
            summary_response = client.chat.completions.create(
                model=model, messages=summary_context, temperature=0,
            )
            summary = (summary_response.choices[0].message.content or "").strip()

    return {
        "current_task": task,
        "current_turn": current_turn,
        "turns": completed_turns,
        "summary": summary,
        "final_response": final_answer,
        "turn_status": "failed" if working["turn_status"] == "failed" else "completed",
    }


def build_graph(
    client: Any | None = None,
    model: str | None = None,
    *,
    recent_turns: int | None = RECENT_TURNS,
    use_summary: bool = True,
    debug: bool = False,
    tools: list[dict[str, Any]] | None = None,
    tool_executor: Callable[..., dict[str, Any]] | None = None,
    checkpointer: Any | None = None,
):
    """
    여기가 이번 과제의 핵심.
    실제 에이전트 루프를 그래프로 만드는 부분임
    """
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    # llm 클라이언트 정의
    if client is None:
        from agent.core.llm import create_client
        client = create_client()
    if model is None:
        model = os.getenv("MODEL_NAME") or client.models.list().data[0].id

    # 그래프 빌드 시작
    builder = StateGraph(AgentState)
    # 플래너 노드 정의
    builder.add_node("planner", partial(
        planner_node, client=client, model=model,
        recent_turns=recent_turns, use_summary=use_summary, debug=debug,
    ))
    # 계획 검토 노드 정의
    builder.add_node("plan_review", plan_review_node)
    # 계획 수정 노드 정의
    builder.add_node("plan_editor", partial(
        plan_editor_node, client=client, model=model, debug=debug,
    ))
    # 실행 노드 정의
    builder.add_node("executor", partial(
        executor_node, client=client, model=model, debug=debug,
        tools=tools, tool_executor=tool_executor,
    ))
    # 진행 체크 노드 정의
    builder.add_node("checker", partial(
        checker_node, client=client, model=model, debug=debug,
    ))
    # 재계획 노드 정의
    builder.add_node("replanner", partial(
        replanner_node, client=client, model=model, debug=debug,
    ))
    # 최종 답변 노드 정의
    builder.add_node("finalizer", partial(
        finalizer_node, client=client, model=model,
        recent_turns=recent_turns, use_summary=use_summary, debug=debug,
    ))

    # 노드 연결 정의
    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", route_after_planner,
                                  {"review": "plan_review", "finalizer": "finalizer"})
    builder.add_conditional_edges("plan_review", route_after_plan_review,
                                  {"plan_editor": "plan_editor", "executor": "executor"})
    builder.add_conditional_edges("plan_editor", route_after_plan_editor,
                                  {"plan_review": "plan_review", "finalizer": "finalizer"})
    builder.add_conditional_edges("executor", route_after_executor,
                                  {"checker": "checker", "replanner": "replanner", "finalizer": "finalizer"})
    builder.add_conditional_edges("checker", route_after_checker,
                                  {"executor": "executor", "replanner": "replanner", "finalizer": "finalizer"})
    builder.add_conditional_edges("replanner", route_after_replanner,
                                  {"executor": "executor", "finalizer": "finalizer"})
    builder.add_edge("finalizer", END)

    return builder.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())


if __name__ == "__main__":
    """
    테스트 코드임
    실행:
        python -m agent.core.graph
    """
    from langgraph.types import Command

    question = (
        "2026년 해외 출장의 숙박비와 식비 한도, 그리고 출발 전 승인 요건을 "
        "근거 문서와 함께 정리해줘."
    )
    app = build_graph()
    config = {"configurable": {"thread_id": "term-agent"}, "recursion_limit": 100}
    first = app.invoke(create_turn_input(question), config=config)
    # 자연어 수정 후 다시 interrupt 되므로 if가 아니라 while이어야 한다.
    while "__interrupt__" in first:
        review = first["__interrupt__"][0].value
        print("\n[계획 검토]")
        print(f"목표: {review['goal']}")
        print(f"질문: {review['question']}")
        for index, step in enumerate(review["plan"], start=1):
            print(f"{index}. {step['instruction']}")
            print(f"   depends_on: {step['depends_on']}")

        answer = input("\n승인= Enter, 수정= 피드백 입력: ").strip()
        decision = {"approved": True} if not answer else {"approved": False, "feedback": answer}
        first = app.invoke(Command(resume=decision), config=config)

    print("\n[최종 답변]")
    print(first["final_response"])
    print(f"\n[Turn status] {first['turn_status']}")
    task = first["current_task"]

    print("\n[실행 정보]")
    print("실패 이유:", task["aborted_reason"])
    print("재계획 횟수:", task["replan_count"])
    print("LLM 호출 횟수:", task["llm_call_count"])
    print("마지막 진행 판단:", first["progress"])

    print("\n[PlanStep 상태]")
    for step in task["plan"]:
        print(
            f"Step {step['id']}: {step['status']}",
            f"| result: {str(step['result'])[:200]}"
        )

    print("\n[실행 Trace]")
    for event in task["trace"]:
        print(json.dumps(event, ensure_ascii=False))
