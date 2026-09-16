# Tool System Design

## 1. 목적

Tool 시스템은 Agent가 실행할 수 있는 모든 기능을 공통된 방식으로 관리하기 위한 계층이다.

Tool의 출처는 중요하지 않다.

- Builtin Tool
- Plugin Tool
- Agent가 런타임 중 생성한 Tool

모든 Tool은 최종적으로 `ToolRegistry`에 등록되고, Agent는 Registry를 통해 현재 사용 가능한 Tool을 확인한다.

---

## 2. 디렉토리 구조

```text
src/
└─ tool/
   ├─ __init__.py
   ├─ model.py
   ├─ registry.py
   └─ executor.py
```

---

## 3. 핵심 개념

```text
ToolSpec
= LLM에게 보여줄 Tool 설명

Tool
= ToolSpec + 실제 실행 함수

ToolRegistry
= 현재 Runtime에서 사용할 수 있는 Tool 목록

ToolExecutor
= LLM의 Tool Call을 실제 함수 실행으로 연결
```

---

## 4. `model.py`

Tool의 공통 자료형을 정의한다.

### ToolSpec

LLM에게 전달되는 Tool 정보다.

```python
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
```

예:

```python
ToolSpec(
    name="add",
    description="두 숫자를 더합니다.",
    parameters={
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
    },
)
```

### Tool

실제 실행 함수까지 포함한다.

```python
@dataclass
class Tool:
    spec: ToolSpec
    handler: Callable[..., Any]
```

예:

```python
def add(a: int, b: int) -> int:
    return a + b


add_tool = Tool(
    spec=ToolSpec(
        name="add",
        description="두 숫자를 더합니다.",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        },
    ),
    handler=add,
)
```

---

## 5. `registry.py`

현재 Runtime에서 사용할 수 있는 Tool을 관리한다.

```python
from .model import Tool


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._version = 0

    def register(self, tool: Tool):
        self._tools[tool.spec.name] = tool
        self._version += 1

    def unregister(self, name: str):
        if name in self._tools:
            del self._tools[name]
            self._version += 1

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        return [
            {
                "name": tool.spec.name,
                "description": tool.spec.description,
                "parameters": tool.spec.parameters,
            }
            for tool in self._tools.values()
        ]

    @property
    def version(self) -> int:
        return self._version
```

### Registry의 역할

Tool 목록은 여러 곳에서 따로 관리하지 않는다.

```text
X Agent.tools
X PluginManager.tools
X Runtime.tools

O ToolRegistry
```

`ToolRegistry`가 Tool 목록의 Single Source of Truth가 된다.

Agent는 매 step 현재 Registry를 조회한다.

따라서 런타임 중:

```python
registry.register(new_tool)
```

하면 Agent를 재시작하지 않아도 다음 step부터 새로운 Tool을 사용할 수 있다.

---

## 6. `executor.py`

LLM이 Tool Call을 반환했을 때 실제 Python 함수를 실행한다.

```python
from typing import Any

from .registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:

        tool = self.registry.get(name)

        if tool is None:
            raise ValueError(f"Tool not found: {name}")

        return tool.handler(**arguments)
```

예를 들어 LLM이 다음 Tool Call을 반환하면:

```python
name = "add"

arguments = {
    "a": 10,
    "b": 20,
}
```

Agent는:

```python
result = executor.execute(
    name="add",
    arguments={
        "a": 10,
        "b": 20,
    },
)
```

를 호출한다.

내부적으로는:

```python
add(a=10, b=20)
```

가 실행된다.

---

## 7. 전체 실행 흐름

```text
LLM
 ↓
Tool Call

name="add"
args={"a": 10, "b": 20}

 ↓

Agent Loop
 ↓

ToolExecutor
 ↓

ToolRegistry.get("add")
 ↓

Tool.handler
 ↓

실제 Python 함수 실행
 ↓

30
 ↓

Agent가 Tool Result를 messages에 추가
 ↓

LLM 다시 호출
```

---

## 8. Plugin과의 연결

Plugin 자체가 Tool 실행을 담당하지 않는다.

Plugin Loader가 Plugin 내부 Tool을 읽고 `ToolRegistry`에 등록한다.

```text
Plugin
 ↓
PluginLoader
 ↓
Tool 생성
 ↓
ToolRegistry.register()
```

예:

```python
registry.register(plugin_tool)
```

Agent가 런타임 중 새로운 Tool을 직접 만든 경우도 동일하다.

```python
registry.register(created_tool)
```

Agent 입장에서는 Tool이 Builtin인지 Plugin에서 왔는지 알 필요가 없다.

---

## 9. 런타임 동적 업데이트

Tool 시스템은 Runtime 중 계속 변경될 수 있어야 한다.

```text
Agent 실행 중

ToolRegistry
├─ echo
├─ add
└─ file.read

      ↓ Plugin 설치

ToolRegistry
├─ echo
├─ add
├─ file.read
├─ calendar.create
└─ calendar.list
```

다음 Agent step부터 새 Tool이 자동으로 LLM에 제공된다.

`version`은 Tool 목록 변경 감지에 사용할 수 있다.

```python
registry.version
```

예를 들어 Context 또는 Tool schema cache가 있다면 Registry version이 변경됐을 때 다시 생성할 수 있다.

---

## 10. 향후 Sandbox

현재는 ToolExecutor가 직접 Python 함수를 실행한다.

```python
tool.handler(**arguments)
```

향후 Sandbox를 도입하면 Executor 내부만 변경할 수 있다.

```python
sandbox.execute(tool, arguments)
```

즉 다음 구조는 그대로 유지된다.

```text
Agent
 ↓
ToolExecutor
 ↓
ToolRegistry
```

실제 실행 방식만 Sandbox 기반으로 교체하면 된다.

---

## 11. 향후 확장 항목

현재 기본 구조에서는 필요하지 않지만 이후 추가할 수 있다.

- argument validation
- async tool
- timeout
- permission
- sandbox
- dependency management
- Tool metadata
- Tool category
- 실행 로그
- Tool 호출 횟수 제한

초기 버전에서는 복잡하게 만들지 않고 현재 구조만 유지한다.

---

## 12. 현재 Tool 계층의 완료 상태

```text
✓ ToolSpec
✓ Tool
✓ ToolRegistry
✓ ToolExecutor
✓ Runtime Tool 등록
✓ Runtime Tool 삭제
✓ LLM용 Tool schema 생성
✓ Plugin Tool 확장 가능 구조
✓ Agent 생성 Tool 확장 가능 구조
```

다음 단계에서는 Agent Loop가 `ToolRegistry.schemas()`와 `ToolExecutor.execute()`를 사용하도록 연결한다.
