"""Context projection regression tests for the migrated Week 6 context module.

Run from app/: python -m unittest discover -s tests -p 'test_context.py' -v
"""
from __future__ import annotations

import json
import unittest
from copy import deepcopy
from types import SimpleNamespace

from agent.core.contexts import (
    MAX_PLAN_STEPS,
    build_executor_context,
    build_final_context,
    build_planner_context,
    build_progress_context,
    build_replanner_context,
    build_summary_context,
    dependency_closure,
)
from agent.core.state import create_plan_step, create_state, create_task_state
from agent.plan import create_plan, execute_plan_step


def sample_state():
    state = create_state()
    state["turns"] = [
        [{"role": "user", "content": "오래된 질문"}, {"role": "assistant", "content": "오래된 답"}],
        [{"role": "user", "content": "이전 질문"}, {"role": "assistant", "content": "이전 답"}],
    ]
    state["summary"] = "예전 대화 요약"
    state["current_turn"] = [{"role": "user", "content": "2026년 출장 규정 확인"}]
    task = create_task_state("2026년 출장 규정 확인")
    p1 = create_plan_step(1, "숙박 규정 확인", [])
    p2 = create_plan_step(2, "식비 규정 확인", [1])
    p3 = create_plan_step(3, "승인 규정 확인", [2])
    p4 = create_plan_step(4, "관련 없는 보안 규정 확인", [])
    p1["status"] = "completed"
    p1["result"] = "숙박비 220달러"
    p2["status"] = "completed"
    p2["result"] = "식비 60달러"
    p3["status"] = "in_progress"
    task["plan"] = [p1, p2, p3, p4]
    task["current_plan_step_id"] = 3
    task["retrieved_documents"] = {
        "lodging": {"id": "lodging", "text": "숙박비 220달러", "source": "travel_lodging_B.txt", "year": 2026, "status": "active", "retrieved_by_plan_steps": [1]},
        "meal": {"id": "meal", "text": "식비 60달러", "source": "meal_expense.txt", "year": 2026, "status": "active", "retrieved_by_plan_steps": [2]},
        "usb": {"id": "usb", "text": "개인 USB 금지", "source": "usb_security.txt", "year": 2026, "status": "active", "retrieved_by_plan_steps": [4]},
    }
    task["retrieved_memories"] = {
        "memory-1": {"id": "memory-1", "content": "출장 관련 개인 선호", "retrieved_by_plan_steps": [1]},
    }
    state["current_task"] = task
    return state


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.answers.pop(0), tool_calls=[]))])


class ContextTests(unittest.TestCase):
    def test_planner_conversation_and_summary_selection(self):
        state = sample_state()
        original = deepcopy(state)
        context = build_planner_context(state, state["current_turn"], 1, True)
        self.assertIn(f"at most {MAX_PLAN_STEPS}", context[0]["content"])
        self.assertIn("예전 대화 요약", context[0]["content"])
        self.assertEqual([m["content"] for m in context[1:]], ["이전 질문", "이전 답", "2026년 출장 규정 확인"])
        self.assertEqual(state, original)

    def test_executor_only_sees_its_transitive_dependencies(self):
        state = sample_state()
        step = state["current_task"]["plan"][2]
        self.assertEqual(dependency_closure(state, step), [1, 2])
        context = build_executor_context(state, step)
        system = context[0]["content"]
        self.assertIn("travel_lodging_B.txt", system)
        self.assertIn("meal_expense.txt", system)
        self.assertIn("숙박비 220달러", system)
        self.assertIn("식비 60달러", system)
        self.assertNotIn("usb_security.txt", system)
        self.assertNotIn("예전 대화 요약", system)
        self.assertNotIn("2026년 출장 규정 확인", system)
        self.assertEqual(context[-1]["role"], "user")

    def test_progress_replanner_and_final_context_select_evidence(self):
        state = sample_state()
        task = state["current_task"]
        step = task["plan"][2]
        progress = build_progress_context(state, step, {"status": "completed", "content": "승인 확인"})
        payload = json.loads(progress[1]["content"])
        self.assertEqual([r["id"] for r in payload["remaining_steps"]], [4])
        self.assertEqual({d["id"] for d in payload["relevant_documents"]}, {"lodging", "meal"})
        replanner = build_replanner_context(state, step, "증거 부족")
        replan_payload = json.loads(replanner[1]["content"])
        self.assertEqual([s["id"] for s in replan_payload["completed_steps"]], [1, 2])
        self.assertEqual(replan_payload["next_available_plan_step_id"], 5)
        task["aborted_reason"] = "검색 실패"
        step["status"] = "failed"
        final = build_final_context(state, state["current_turn"], 1, True)
        self.assertIn("task_aborted", final[0]["content"])
        self.assertIn("failed_plan_steps", final[0]["content"])
        self.assertIn("travel_lodging_B.txt", final[0]["content"])
        self.assertNotIn("usb_security.txt", final[0]["content"])

    def test_summary_only_summarizes_old_completed_turns(self):
        state = sample_state()
        context = build_summary_context(state, 1)
        self.assertIn("오래된 질문", context[1]["content"])
        self.assertNotIn("이전 질문", context[1]["content"])
        self.assertIsNone(build_summary_context(state, 2))

    def test_plan_functions_use_real_context_by_default(self):
        state = create_state()
        state["current_turn"] = [{"role": "user", "content": "회사 정책 알려줘"}]
        state["current_task"] = create_task_state("회사 정책 알려줘")
        client = FakeClient(['{"steps":[{"instruction":"출장 정책 조사","depends_on":[]}]}'])
        create_plan(client, "model", state, state["current_turn"], 2, True, False)
        self.assertIn("You are the Planner", client.requests[0]["messages"][0]["content"])
        self.assertEqual(state["current_task"]["plan"][0]["instruction"], "출장 정책 조사")
        exe_client = FakeClient(["조사 완료"])
        result = execute_plan_step(
            exe_client, "model", state, False,
            tools=[],
            execute_tool=lambda *args: self.fail("No tool calls expected"),
        )
        self.assertEqual(result, {"status": "completed", "content": "조사 완료"})
        self.assertIn("You are the Executor", exe_client.requests[0]["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
