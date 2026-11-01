"""
# week 11 추가자료 참고함
AgentState
├── turns                    # 대화 기록
├── summary                  # 이전 대화 요약
│
├── current_turn             # 현재 대화 메시지
├── current_task: TaskState  # 현재 작업 상태
│   ├── goal                 # 현재 작업 목표
│   ├── plan: list[PlanStep] # 현재 작업 계획
│   │   ├── id                 # 계획 단계 ID
│   │   ├── instruction        # 계획 단계 지시문
│   │   ├── depends_on         # 의존하는 단계 ID 목록
│   │   ├── status             # 단계 상태
│   │   ├── result             # 단계 실행 결과
│   │   ├── messages           # 단계와 관련된 메시지들
│   │   ├── document_ids       # 조회된 문서 ID 목록
│   │   └── memory_ids         # 조회된 메모리 ID 목록
│   ├── current_plan_step_id # 현재 실행 중인 계획 단계 ID
│   ├── plan_revision        # 계획 수정 횟수
│   ├── replan_count         # 재계획 실행 횟수
│   ├── retrieved_documents  # 조회된 문서들
│   ├── retrieved_memories   # 조회된 메모리들
│   ├── llm_call_count       # LLM 호출 횟수
│   ├── aborted_reason       # 중단 이유
│   └── trace                # 이벤트 추적할때 사용
│
├── review_feedback          # 현재 계획의 피드백 (사용자가 계획 수정할때 사용)
├── step_result              # 최근 단계 실행 결과
├── progress                 # 진행 판단 결과
├── final_response           # 최종 답변
└── turn_status              # 현재 Turn 상태
  
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


Message = dict[str, Any]
TraceEvent = dict[str, Any]

PlanStepStatus = Literal[
    "pending", "in_progress", "completed", "failed", "replaced"
]
TurnStatus = Literal["idle", "running", "completed", "failed"]
ProgressDecision = Literal["continue", "replan", "finish"]


class PlanStep(TypedDict):
    id: int
    instruction: str
    depends_on: list[int]
    status: PlanStepStatus
    result: str | None
    messages: list[Message]
    document_ids: list[str]
    memory_ids: list[str]


class TaskState(TypedDict):
    goal: str
    plan: list[PlanStep]
    current_plan_step_id: int | None
    plan_revision: int
    replan_count: int
    retrieved_documents: dict[str, dict[str, Any]]
    retrieved_memories: dict[str, dict[str, Any]]
    llm_call_count: int
    aborted_reason: str | None
    trace: list[TraceEvent]


class StepResult(TypedDict):
    """Result returned by the existing execute_plan_step()."""

    status: Literal["completed", "failed"]
    content: str


class ProgressResult(TypedDict):
    """Decision returned by the existing check_progress()."""

    decision: ProgressDecision
    reason: str


class AgentState(TypedDict):
    """
    langgraph 에서 공유할 state임

    """

    # Conversation-level state
    turns: list[list[Message]]
    summary: str

    # Current-turn state.
    current_turn: list[Message]
    current_task: TaskState | None
    review_feedback: str | None  # 사용자 계획 수정 요청. 수정 Node가 처리하면 초기화
    step_result: StepResult | None
    progress: ProgressResult | None
    final_response: str | None
    turn_status: TurnStatus


def create_plan_step(
    plan_step_id: int,
    instruction: str,
    depends_on: list[int],
) -> PlanStep:
    """Create a plan step with the Week 6 initial tool-call message."""
    return {
        "id": plan_step_id,
        "instruction": instruction,
        "depends_on": list(depends_on),
        "status": "pending",
        "result": None,
        "messages": [{"role": "user", "content": "Execute the current plan step."}],
        "document_ids": [],
        "memory_ids": [],
    }


def create_task_state(goal: str) -> TaskState:
    """기본 task state 생성"""
    return {
        "goal": goal,
        "plan": [],
        "current_plan_step_id": None,
        "plan_revision": 0,
        "replan_count": 0,
        "retrieved_documents": {},
        "retrieved_memories": {},
        "llm_call_count": 0,
        "aborted_reason": None,
        "trace": [],
    }


def create_state() -> AgentState:
    """
    초기 state 생성 후 반환
    returns:
        AgentState: 초기 state
    """
    return {
        "turns": [],
        "summary": "",
        "current_turn": [],
        "current_task": None,
        "review_feedback": None,
        "step_result": None,
        "progress": None,
        "final_response": None,
        "turn_status": "idle",
    }
