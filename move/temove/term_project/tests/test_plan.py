"""Self-contained unit tests for the Week 6-derived plan package.

These tests use fake LLM responses and minimal context-builder stubs. They do
not connect to a live LLM, use tools, or require LangGraph.
From app/: python -m unittest discover -s tests -p test_plan.py -v
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from agent.core.state import create_plan_step, create_state, create_task_state
from agent.plan import (
    check_progress,
    create_plan,
    execute_plan_step,
    normalize_initial_plan,
    replan,
)
from agent.plan.common import get_current_plan_step

# Signatures match the original Week 6 context builders. The actual functions
# remain in agent/context and will be supplied at graph integration time.
build_planner_context = lambda state, current_turn, recent_turns, use_summary: [
    {"role": "user", "content": current_turn[-1]["content"]}
]
build_executor_context = lambda state, step: [
    {"role": "user", "content": step["instruction"]}
]
build_progress_context = lambda state, step, result: [
    {"role": "user", "content": result["content"]}
]
build_replanner_context = lambda state, step, reason: [
    {"role": "user", "content": reason}
]

class FakeClient:
    def __init__(self, messages):
        self.messages = list(messages)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if not self.messages:
            raise AssertionError("unexpected LLM request")
        return SimpleNamespace(choices=[SimpleNamespace(message=self.messages.pop(0))])


def fake_message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


def example_state():
    state = create_state()
    state["current_turn"] = [{"role": "user", "content": "회사 출장 규정을 알려줘."}]
    state["current_task"] = create_task_state("회사 출장 규정을 알려줘.")
    return state


class PlanTests(unittest.TestCase):
    def test_normalization_uses_existing_step_fields(self):
        plan = normalize_initial_plan([
            {"instruction": "  숙박비  ", "depends_on": []},
            {"instruction": "식비", "depends_on": [1, 1]},
        ])
        self.assertEqual([s["id"] for s in plan], [1, 2])
        self.assertEqual(plan[0]["instruction"], "숙박비")
        self.assertEqual(plan[1]["depends_on"], [1])
        self.assertEqual(plan[1]["status"], "pending")
        self.assertEqual(plan[1]["messages"], [{"role": "user", "content": "Execute the current plan step."}])
        with self.assertRaises(ValueError):
            normalize_initial_plan([{"instruction": "잘못된 의존", "depends_on": [1]}])

    def test_create_plan_calls_llm_and_saves_normalized_plan(self):
        state = example_state()
        response = '{"steps":[{"instruction":"숙박비 조회","depends_on":[]},' \
                   '{"instruction":"식비 조회","depends_on":[1]}]}'
        client = FakeClient([fake_message(response)])
        create_plan(
            client, "test-model", state, state["current_turn"], 2, True, False,
            build_context=build_planner_context,
        )
        task = state["current_task"]
        self.assertEqual(task["current_plan_step_id"], 1)
        self.assertEqual(len(task["plan"]), 2)
        self.assertEqual(task["llm_call_count"], 1)
        self.assertEqual(task["trace"][-1]["event"], "plan_created")
        self.assertEqual(client.requests[0]["response_format"], {"type": "json_object"})

    def test_create_plan_retries_bad_json(self):
        state = example_state()
        client = FakeClient([fake_message("bad json"), fake_message('{"steps":[{"instruction":"요약","depends_on":[]}]}')])
        create_plan(client, "m", state, state["current_turn"], 2, True, False, build_context=build_planner_context)
        self.assertEqual(state["current_task"]["llm_call_count"], 2)
        self.assertEqual(len(client.requests), 2)

    def test_executor_preserves_original_tool_call_loop(self):
        state = example_state()
        state["current_task"]["plan"] = [create_plan_step(1, "숙박비 조회", [])]
        state["current_task"]["current_plan_step_id"] = 1
        fake_tool_call = SimpleNamespace(id="call-1", function=SimpleNamespace(name="search_documents", arguments='{"query":"숙박비"}'))
        client = FakeClient([
            fake_message(None, [fake_tool_call]),
            fake_message("숙박비 규정을 확인했습니다."),
        ])
        invocations = []
        def tool_runner(name, args, state, step):
            invocations.append((name, args))
            step["document_ids"].append("travel_lodging_B")
            return {"status": "ok", "document_ids": ["travel_lodging_B"]}
        result = execute_plan_step(
            client, "m", state, False,
            build_context=build_executor_context,
            tools=[{"type": "function", "function": {"name": "search_documents"}}],
            execute_tool=tool_runner,
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(invocations, [("search_documents", {"query": "숙박비"})])
        self.assertEqual(get_current_plan_step(state)["status"], "in_progress")
        self.assertEqual(get_current_plan_step(state)["document_ids"], ["travel_lodging_B"])
        self.assertEqual([m["role"] for m in get_current_plan_step(state)["messages"]], ["user", "assistant", "tool", "assistant"])

    def test_progress_checker_returns_decision_without_advancing(self):
        state = example_state()
        state["current_task"]["plan"] = [create_plan_step(1, "숙박비 조회", [])]
        state["current_task"]["current_plan_step_id"] = 1
        client = FakeClient([fake_message('{"decision":"finish", "reason":"조회 완료"}')])
        result = check_progress(client, "m", state, {"status":"completed", "content":"완료"}, False, build_context=build_progress_context)
        self.assertEqual(result["decision"], "finish")
        self.assertEqual(state["current_task"]["plan"][0]["status"], "pending")
        self.assertEqual(state["current_task"]["trace"][-1]["event"], "progress_checked")

    def test_replan_preserves_finished_and_replaces_pending(self):
        state = example_state()
        p1 = create_plan_step(1, "완료된 일", [])
        p1["status"] = "completed"
        p1["result"] = "이미 확인"
        p2 = create_plan_step(2, "실패한 일", [1]); p2["status"] = "in_progress"
        p3 = create_plan_step(3, "기존 남은 일", [2])
        state["current_task"]["plan"] = [p1,p2,p3]
        state["current_task"]["current_plan_step_id"] = 2
        new_plan = '{"remaining_steps":[{"id":4,"instruction":"다른 방식으로 확인","depends_on":[1]}]}'
        client = FakeClient([fake_message(new_plan)])
        replan(client, "m", state, "자료 부족", False, build_context=build_replanner_context)
        self.assertEqual([s["status"] for s in state["current_task"]["plan"]], ["completed","replaced","replaced","pending"])
        self.assertEqual(state["current_task"]["current_plan_step_id"], 4)
        self.assertEqual(state["current_task"]["replan_count"], 1)
        self.assertEqual(state["current_task"]["plan"][3]["depends_on"], [1])


if __name__ == "__main__":
    unittest.main()
