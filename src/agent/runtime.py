"""단일 문제해결 루프. Host 통신, Task memory, context compaction을 조율한다."""
from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import asdict
from typing import Any, Awaitable, Callable
from uuid import uuid4

from .context import (build_context_messages, build_summary_messages,
                      choose_compaction_upto, estimate_context_chars)
from .core import AgentCore, ToolExecutorLike, ToolRegistryLike
from .session import TaskSession
from .tools import SessionTools
from .types import (AgentLimits, HostCommand, TaskMemory, TaskRequest,
                    TaskResult, TaskStatus, WorkingMemory)


class _HostTimeout(Exception):
    pass


class TaskRuntime:
    def __init__(self, *, session: TaskSession, core: AgentCore,
                 request: TaskRequest, registry: ToolRegistryLike,
                 executor: ToolExecutorLike, model: str,
                 limits: AgentLimits, options: Any = None,
                 model_selector: Callable[[int], str] | None = None):
        self.session = session
        self.core = core
        self.request = request
        self.model = model
        self.model_selector = model_selector
        self.options = copy.deepcopy(options)
        self.limits = limits
        self.memory = WorkingMemory() # what if change its name to state?
        self.cancel_requested = False
        self._question: tuple[str, asyncio.Future[str]] | None = None
        self._active_tool_call_id: str | None = None
        self.tools = SessionTools(
            registry, executor, self._ask_host, self._write_memory,
            self._search_conversation, self._read_conversation,
        )
        self.memory.messages = [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": request.instruction},
        ]
        for context in request.context:
            self.memory.messages.append({"role": "user", "content": f"Host context:\n{context}"})

    async def run(self) -> TaskResult:
        self.session._set_status(TaskStatus.RUNNING)
        try:
            return await self._loop()
        except asyncio.CancelledError:
            # public cancel()은 Task.cancel()을 쓰지 않는다. 여기로 오면 이벤트 루프 종료 등이다.
            self._finish(TaskStatus.CANCELLED, "runtime_cancelled", "")
            raise
        except Exception as exc:
            status = TaskStatus.CANCELLED if self.cancel_requested else TaskStatus.FAILED
            reason = "host_cancelled" if self.cancel_requested else "runtime_error"
            return self._finish(status, reason, "", (f"{type(exc).__name__}: {exc}",))

    async def _loop(self) -> TaskResult:
        # start loop
        while True:
            self._drain_commands()
            self._apply_instructions()

            # check limits and cancel
            if self.cancel_requested:
                return self._finish(TaskStatus.CANCELLED, "host_cancelled", "")
            if self.memory.steps >= self.limits.max_steps:
                return self._finish(TaskStatus.LIMIT_REACHED, "max_steps", "")

            step_number = self.memory.steps + 1
            # select model for this step.
            model = self.model_selector(step_number) if self.model_selector else self.model
            if not isinstance(model, str) or not model.strip():
                raise ValueError("model selector must return a nonempty model name")

            # 오래된 context를 먼저 압축한다. 요약 호출 자체는 problem-solving step에 포함하지 않는다.
            schemas = self.tools.schemas()
            await self._compact_context_if_needed(model, schemas)
            self._drain_commands()
            self._apply_instructions()
            if self.cancel_requested:
                return self._finish(TaskStatus.CANCELLED, "host_cancelled", "")

            # compaction 동안 Registry나 Host instruction이 변했을 수 있으므로 안전 지점에서 다시 읽는다.
            schemas = self.tools.schemas()
            offered = {schema["name"]: schema for schema in schemas}
            registry_version = self.tools.version
            revision = self.memory.revision
            context_messages = build_context_messages(self.memory)

            self.memory.steps = step_number
            self.session._emit("step_started", {
                "step": step_number,
                "model": model,
                "context_chars": estimate_context_chars(context_messages, schemas),
                "context_compactions": self.memory.context_compactions,
            })
            response = await self._wait_operation(lambda: self.core.step(
                model=model, messages=context_messages, tools=schemas, options=self.options,
            ))
            self._drain_commands()
            if self.cancel_requested:
                return self._finish(TaskStatus.CANCELLED, "host_cancelled", "")
            if revision != self.memory.revision:
                # 이전 문맥으로 생성된 답변/도구 요청은 기록에도 넣지 않는다.
                self.session._emit("response_discarded", {
                    "step": step_number, "reason": "new_host_instruction",
                })
                continue

            finish_reason = getattr(response, "finish_reason", None)
            if finish_reason in {"length", "max_tokens", "content_filter"}:
                return self._finish(TaskStatus.INCOMPLETE, str(finish_reason),
                                    response.content or "")
            if not response.tool_calls:
                if not response.content or not response.content.strip():
                    return self._finish(TaskStatus.FAILED, "empty_response", "")
                self.memory.messages.append({"role": "assistant", "content": response.content})
                return self._finish(TaskStatus.COMPLETED, "final_answer", response.content)

            # 공통 LLMResponse.to_message()와 같은 flat tool_calls 형식.
            # Provider adapter가 자신의 SDK 형식으로 변환한다.
            self.memory.messages.append({
                "role": "assistant", "content": response.content or "",
                "tool_calls": [{"id": c.id, "name": c.name,
                                "arguments": copy.deepcopy(c.arguments)}
                               for c in response.tool_calls],
            })
            if response.content:
                self.session._emit("message", {"content": response.content})

            terminal_reason: str | None = None
            for call in response.tool_calls:
                self._drain_commands()
                if terminal_reason:
                    result = self._error("not_executed", terminal_reason)
                elif self.cancel_requested:
                    result = self._error("not_executed", "host_cancelled")
                elif revision != self.memory.revision:
                    result = self._error("not_executed", "superseded_by_host_instruction")
                elif self.memory.tool_calls >= self.limits.max_tool_calls:
                    terminal_reason = "max_tool_calls"
                    result = self._error("not_executed", terminal_reason)
                else:
                    try:
                        result = await self._wait_operation(
                            lambda c=call: self._execute_tool(c, offered, revision, registry_version),
                            cancel_wait=call.name == "host_ask",
                        )
                    except _HostTimeout:
                        terminal_reason = "host_response_timeout"
                        result = self._error("host_response_timeout", "Host did not answer in time")

                content = self._serialize_result(result)
                self.memory.messages.append({
                    "role": "tool", "name": call.name, "tool_call_id": call.id,
                    "content": content,
                })
                decoded = json.loads(content)
                if not decoded.get("ok", False):
                    self.memory.tool_errors += 1
                self.session._emit("tool_finished", {
                    "tool_call_id": call.id, "name": call.name,
                    "result": decoded,
                })
            # 모든 tool_call에 대응하는 결과를 붙인 뒤 Host 지시를 추가한다.
            self._drain_commands()
            self._apply_instructions()
            if self.cancel_requested:
                return self._finish(TaskStatus.CANCELLED, "host_cancelled", "")
            if terminal_reason == "host_response_timeout":
                return self._finish(TaskStatus.INCOMPLETE, terminal_reason, "")
            if terminal_reason:
                return self._finish(TaskStatus.LIMIT_REACHED, terminal_reason, "")

    async def _compact_context_if_needed(self, model: str,
                                         schemas: list[dict[str, Any]]) -> None:
        threshold = self.limits.context_compact_threshold_chars
        if threshold is None:
            return
        current_view = build_context_messages(self.memory)
        before_chars = estimate_context_chars(current_view, schemas)
        if before_chars <= threshold:
            return

        start = max(2, self.memory.summarized_upto)
        upto = choose_compaction_upto(
            self.memory.messages,
            start=start,
            keep_recent_messages=self.limits.context_keep_recent_messages,
        )
        if upto <= start:
            # 아직 안전하게 접을 수 있는 오래된 group이 없다. 최근 raw context를 우선 보존한다.
            return

        fold = copy.deepcopy(self.memory.messages[start:upto])
        summary_messages = build_summary_messages(self.memory.context_summary, fold)
        self.session._emit("context_compaction_started", {
            "from_message": start,
            "to_message": upto,
            "folded_messages": len(fold),
            "context_chars_before": before_chars,
        })
        response = await self._wait_operation(lambda: self.core.step(
            model=model, messages=summary_messages, tools=[], options=self.options,
        ))
        if getattr(response, "finish_reason", None) in {"length", "max_tokens", "content_filter"}:
            raise RuntimeError(f"context summary incomplete: {response.finish_reason}")
        if response.tool_calls:
            raise RuntimeError("context summarizer returned tool calls")
        if not response.content or not response.content.strip():
            raise RuntimeError("context summarizer returned an empty summary")

        summary = response.content.strip()
        max_chars = self.limits.context_summary_max_chars
        truncated = False
        if len(summary) > max_chars:
            suffix = "\n[summary truncated by runtime]"
            summary = summary[:max(1, max_chars - len(suffix))].rstrip() + suffix
            truncated = True

        self.memory.context_summary = summary
        self.memory.summarized_upto = upto
        self.memory.context_compactions += 1
        after_chars = estimate_context_chars(build_context_messages(self.memory), schemas)
        self.session._emit("context_compacted", {
            "folded_messages": len(fold),
            "summarized_upto": upto,
            "summary_chars": len(summary),
            "summary_truncated": truncated,
            "context_chars_before": before_chars,
            "context_chars_after": after_chars,
        })

    async def _execute_tool(self, call: Any, offered: dict[str, Any], revision: int,
                            registry_version: int | None) -> dict[str, Any]:
        # 별도 실행 task가 시작되기 직전에 접수된 명령도 확인한다.
        self._drain_commands()
        if self.cancel_requested or revision != self.memory.revision:
            return self._error("not_executed", "task_cancelled_or_superseded")
        current = {s["name"]: s for s in self.tools.schemas()}
        if call.name not in offered:
            return self._error("unknown_tool", f"Tool was not offered: {call.name}")
        if (call.name not in current or current[call.name] != offered[call.name]
                or (registry_version is not None and self.tools.version != registry_version)):
            return self._error("tool_changed", f"Tool registry changed after planning: {call.name}")
        self.memory.tool_calls += 1
        self.session._emit("tool_started", {"tool_call_id": call.id, "name": call.name})
        self._active_tool_call_id = call.id
        try:
            result = await self.tools.execute(call.name, call.arguments)
            return {"ok": True, "output": result}
        except _HostTimeout:
            raise
        except asyncio.CancelledError:
            if self.cancel_requested:
                return self._error("cancelled", "Host cancelled the question wait")
            return self._error("tool_cancelled", "Tool raised CancelledError")
        except Exception as exc:
            return self._error(type(exc).__name__, str(exc))
        finally:
            self._active_tool_call_id = None

    async def _wait_operation(self, factory: Callable[[], Awaitable[Any]], *,
                              cancel_wait: bool = False) -> Any:
        """외부 호출이 진행 중이어도 Host 명령은 수신/처리한다.

        기본 취소는 현재 호출 종료를 기다린다. Runtime 소유의 질문 대기만 즉시 취소한다.
        일반 sync 함수를 취소했다고 주장하면서 남은 스레드를 방치하지 않는다.
        """
        operation = asyncio.create_task(factory())
        wake: asyncio.Task[bool] | None = None
        cancel_sent = False
        try:
            while not operation.done():
                self._drain_commands()
                if self.cancel_requested and cancel_wait and not cancel_sent:
                    operation.cancel()
                    cancel_sent = True
                wake = asyncio.create_task(self.session._inbox_ready.wait())
                await asyncio.wait({operation, wake}, return_when=asyncio.FIRST_COMPLETED)
                wake.cancel()
                await asyncio.gather(wake, return_exceptions=True)
                wake = None
            self._drain_commands()
            try:
                return await operation
            except asyncio.CancelledError:
                if self.cancel_requested and cancel_wait:
                    return self._error("cancelled", "Host cancelled the question wait")
                raise
        finally:
            if wake is not None:
                wake.cancel()
                await asyncio.gather(wake, return_exceptions=True)
            if not operation.done():
                # 비정상적인 외부 Runtime Task 취소에 대한 정리. to_thread 강제 중단은 불가능.
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)

    def _drain_commands(self) -> None:
        while self.session._commands:
            command = self.session._commands.popleft()
            if command.type == "cancel":
                self.cancel_requested = True
                self.session._set_status(TaskStatus.CANCELLING)
                self._ack(command, "command_applied")
            elif self.cancel_requested:
                self._ack(command, "command_rejected", "task_is_cancelling")
            elif command.type == "instruction":
                self.memory.revision += 1
                self.memory.pending_instructions.append(command)
            elif command.type == "answer":
                question = self._question
                if (question is None or command.payload["request_id"] != question[0]
                        or question[1].done()):
                    self._ack(command, "command_rejected", "no_matching_pending_question")
                else:
                    question[1].set_result(command.payload["content"])
                    self._ack(command, "command_applied")
            else:
                self._ack(command, "command_rejected", "unsupported_command")
        self.session._inbox_ready.clear()

    def _apply_instructions(self) -> None:
        for command in self.memory.pending_instructions:
            self.memory.messages.append({
                "role": "user", "content": command.payload["content"],
            })
            self._ack(command, "command_applied")
        self.memory.pending_instructions.clear()

    def _ack(self, command: HostCommand, kind: str, reason: str | None = None) -> None:
        payload: dict[str, Any] = {"message_id": command.message_id, "command_type": command.type}
        if reason:
            payload["reason"] = reason
        self.session._emit(kind, payload)

    async def _ask_host(self, question: str, context: str = "") -> str:
        TaskSession._nonempty(question, "question")
        if not isinstance(context, str):
            raise TypeError("context must be a string")
        request_id = uuid4().hex
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._question = (request_id, future)
        self.session._set_status(TaskStatus.WAITING_FOR_HOST)
        self.session._emit("question", {"request_id": request_id, "question": question,
                                        "context": context})
        try:
            return await asyncio.wait_for(asyncio.shield(future), self.limits.host_response_timeout)
        except asyncio.TimeoutError as exc:
            raise _HostTimeout() from exc
        finally:
            if not future.done():
                future.cancel()
            self._question = None
            self.session._emit("question_closed", {"request_id": request_id})
            if not self.cancel_requested:
                self.session._set_status(TaskStatus.RUNNING)

    async def _write_memory(self, content: str, kind: str,
                            source_refs: list[str] | None = None) -> dict[str, Any]:
        for name, value in (("content", content), ("kind", kind)):
            TaskSession._nonempty(value, name)
        if source_refs is not None and (
            not isinstance(source_refs, list) or not all(isinstance(x, str) for x in source_refs)
        ):
            raise TypeError("source_refs must be a list of strings")
        if len(content) > self.limits.max_memory_item_chars:
            raise ValueError(
                f"memory content exceeds max_memory_item_chars={self.limits.max_memory_item_chars}"
            )
        current_chars = sum(len(item.content) for item in self.memory.task_memory)
        if current_chars + len(content) > self.limits.max_task_memory_chars:
            raise ValueError(
                f"task memory exceeds max_task_memory_chars={self.limits.max_task_memory_chars}"
            )
        item = TaskMemory(
            memory_id=uuid4().hex,
            task_id=self.session.task_id,
            content=content,
            kind=kind,
            source_refs=tuple(source_refs or ()),
            created_step=self.memory.steps,
        )
        self.memory.task_memory.append(item)
        self.session._emit("task_memory_written", asdict(item))
        return {"memory_id": item.memory_id, "available_in_context": True}

    def _current_tool_invocation_index(self) -> int | None:
        call_id = self._active_tool_call_id
        if call_id is None:
            return None
        for index in range(len(self.memory.messages) - 1, -1, -1):
            message = self.memory.messages[index]
            if message.get("role") != "assistant":
                continue
            for call in message.get("tool_calls", ()):
                if call.get("id") == call_id:
                    return index
        return None

    @staticmethod
    def _transcript_text(message: dict[str, Any]) -> str:
        return json.dumps(message, ensure_ascii=False, allow_nan=False, default=repr)

    async def _search_conversation(self, query: str, limit: int = 8) -> dict[str, Any]:
        TaskSession._nonempty(query, "query")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be an integer")
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        limit = min(limit, self.limits.conversation_search_max_results)

        needle = query.casefold().strip()
        terms = [term for term in needle.split() if term]
        matches: list[tuple[int, int, dict[str, Any]]] = []
        excluded = self._current_tool_invocation_index()
        snippet_chars = self.limits.conversation_search_snippet_chars

        for index, message in enumerate(self.memory.messages):
            if index == excluded:
                continue
            text = self._transcript_text(message)
            folded = text.casefold()
            phrase_pos = folded.find(needle)
            if phrase_pos >= 0:
                score = 1000 + folded.count(needle)
                match_pos = phrase_pos
            elif terms and all(term in folded for term in terms):
                score = 100 + sum(folded.count(term) for term in terms)
                match_pos = min(folded.find(term) for term in terms)
            else:
                continue

            half = max(1, snippet_chars // 2)
            snippet_start = max(0, match_pos - half)
            snippet_end = min(len(text), snippet_start + snippet_chars)
            if snippet_end - snippet_start < snippet_chars and snippet_start > 0:
                snippet_start = max(0, snippet_end - snippet_chars)
            snippet = text[snippet_start:snippet_end]
            if snippet_start > 0:
                snippet = "…" + snippet
            if snippet_end < len(text):
                snippet += "…"
            item = {
                "message_index": index,
                "role": message.get("role"),
                "name": message.get("name"),
                "match_offset": match_pos,
                "snippet": snippet,
            }
            matches.append((score, index, item))

        matches.sort(key=lambda item: (-item[0], -item[1]))
        selected = [item[2] for item in matches[:limit]]
        return {
            "query": query,
            "matches": selected,
            "total_matches": len(matches),
            "searched_messages": len(self.memory.messages) - (1 if excluded is not None else 0),
            "transcript_messages": len(self.memory.messages),
            "original_transcript_preserved": True,
            "hint": "Use conversation_read(message_index=...) to inspect an exact original message.",
        }

    async def _read_conversation(self, message_index: int, char_offset: int = 0,
                                 max_chars: int | None = None) -> dict[str, Any]:
        for name, value in (("message_index", message_index), ("char_offset", char_offset)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if max_chars is None:
            max_chars = self.limits.conversation_read_max_chars
        if isinstance(max_chars, bool) or not isinstance(max_chars, int):
            raise TypeError("max_chars must be an integer")
        if max_chars < 256 or max_chars > 6000:
            raise ValueError("max_chars must be between 256 and 6000")
        max_chars = min(max_chars, self.limits.conversation_read_max_chars)

        if message_index >= len(self.memory.messages):
            raise IndexError(
                f"message_index {message_index} is not available; readable range is "
                f"0..{max(0, len(self.memory.messages) - 1)}"
            )
        excluded = self._current_tool_invocation_index()
        if message_index == excluded:
            raise ValueError("cannot read the currently executing transcript tool invocation")
        message = self.memory.messages[message_index]
        text = self._transcript_text(message)
        if char_offset > len(text):
            raise ValueError(f"char_offset exceeds message length {len(text)}")
        stop = min(len(text), char_offset + max_chars)
        next_offset = stop if stop < len(text) else None
        return {
            "message_index": message_index,
            "role": message.get("role"),
            "name": message.get("name"),
            "char_offset": char_offset,
            "next_char_offset": next_offset,
            "total_chars": len(text),
            "eof": next_offset is None,
            "serialized_message_chunk": text[char_offset:stop],
        }

    @staticmethod
    def _error(kind: str, message: str) -> dict[str, Any]:
        return {"ok": False, "error": {"type": kind, "message": message}}

    def _serialize_result(self, result: dict[str, Any]) -> str:
        try:
            text = json.dumps(result, ensure_ascii=False, allow_nan=False, default=repr)
        except (TypeError, ValueError, RecursionError) as exc:
            text = json.dumps(self._error("serialization_error", str(exc)), ensure_ascii=False)
        limit = self.limits.max_tool_output_chars
        if len(text) > limit:
            # 바깥 JSON과 escaping 증가분까지 포함해 실제 문맥 길이를 제한한다.
            envelope = {"ok": json.loads(text).get("ok", False), "truncated": True,
                        "original_chars": len(text), "preview": text[:max(0, limit - 128)]}
            text = json.dumps(envelope, ensure_ascii=False)
            while len(text) > limit:
                excess = len(text) - limit
                envelope["preview"] = envelope["preview"][:-max(1, excess)]
                text = json.dumps(envelope, ensure_ascii=False)
        return text

    def _finish(self, status: TaskStatus, reason: str, output: str,
                warnings: tuple[str, ...] = ()) -> TaskResult:
        self._drain_commands()
        self._apply_instructions()
        result = TaskResult(
            task_id=self.session.task_id,
            status=status,
            output=output,
            stop_reason=reason,
            steps=self.memory.steps,
            tool_calls=self.memory.tool_calls,
            tool_errors=self.memory.tool_errors,
            memory=tuple(self.memory.task_memory),
            messages=tuple(copy.deepcopy(self.memory.messages)),
            context_summary=self.memory.context_summary,
            context_compactions=self.memory.context_compactions,
            warnings=warnings,
        )
        self.session._set_status(status)
        self.session._closed = True
        self.session._emit("finished", {
            "status": status.value,
            "stop_reason": reason,
            "output": output,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "memory_items": len(result.memory),
            "context_compactions": result.context_compactions,
        })
        return result
