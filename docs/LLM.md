# LLM System Design

## 1. 목적

LLM 계층은 Agent가 특정 LLM 서비스나 SDK에 종속되지 않도록 하기 위한 추상화 계층이다.

지원 대상 예:

```text
Ollama

OpenAI-compatible
├─ vLLM
├─ OpenAI API
└─ 기타 OpenAI-compatible 서버

향후
├─ Anthropic
├─ Gemini
└─ 기타 Provider
```

Agent는 Provider별 구현 차이를 알 필요 없이 공통 인터페이스만 사용한다.

---

## 2. 디렉토리 구조

```text
src/
└─ llm/
   ├─ __init__.py
   ├─ base.py
   ├─ types.py
   ├─ registry.py
   │
   └─ provider/
      ├─ __init__.py
      ├─ ollama.py
      └─ openai.py
```

---

## 3. 핵심 설계 원칙

### Provider와 Model을 분리한다.

```text
Provider
= 어디에 요청을 보낼 것인가

Model
= 이번 요청에서 어떤 모델을 사용할 것인가
```

따라서 다음처럼 Provider 객체 생성 시 Model을 고정하지 않는다.

```python
provider = OllamaLLM(
    host="http://localhost:11434"
)
```

실제 Model은 `chat()` 호출마다 선택한다.

```python
provider.chat(
    model="qwen3:8b",
    ...
)
```

다음 요청에서는 같은 Provider 객체로 다른 모델을 사용할 수 있다.

```python
provider.chat(
    model="qwen3:30b",
    ...
)
```

이 구조를 통해 이후 Agent가 작업 난이도에 따라 모델을 동적으로 선택할 수 있다.

---

## 4. `types.py`

Provider 종류와 관계없이 Agent가 동일한 형식으로 결과를 받을 수 있도록 공통 자료형을 정의한다.

### ToolCall

```python
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = field(default_factory=lambda: uuid4().hex)
```

### ChatOptions

공통 옵션과 Provider 전용 옵션을 함께 지원한다.

```python
@dataclass
class ChatOptions:
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    stop: list[str] | None = None

    extra: dict[str, Any] = field(default_factory=dict)
```

공통 사용 예:

```python
ChatOptions(
    temperature=0.3,
    top_p=0.9,
    max_tokens=4096,
)
```

Provider별 특수 기능은 `extra`에 넣는다.

Ollama 예:

```python
ChatOptions(
    temperature=0.3,
    extra={
        "think": True,
        "keep_alive": "30m",
        "options": {
            "top_k": 40,
            "repeat_penalty": 1.1,
        },
    },
)
```

vLLM 예:

```python
ChatOptions(
    temperature=0.3,
    extra={
        "extra_body": {
            "top_k": 40,
        },
    },
)
```

### LLMResponse

```python
@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None

    def to_message(self) -> dict[str, Any]:
        message = {
            "role": "assistant",
            "content": self.content or "",
        }

        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
                for call in self.tool_calls
            ]

        return message
```

Agent는 Provider와 관계없이 다음만 사용하면 된다.

```python
response.content
response.tool_calls
```

---

## 5. `base.py`

모든 LLM Provider가 따라야 하는 공통 인터페이스를 정의한다.

```python
from abc import ABC, abstractmethod
from typing import Any

from .types import ChatOptions, LLMResponse


class BaseLLM(ABC):

    @abstractmethod
    def get_available_models(self) -> list[str]:
        pass

    @abstractmethod
    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        options: ChatOptions | None = None,
    ) -> LLMResponse:
        pass
```

### `get_available_models()`

현재 Provider 서버에서 실제로 사용 가능한 모델 목록을 반환한다.

예:

```python
models = provider.get_available_models()
```

결과:

```text
qwen3:8b
qwen3:30b
gemma3:12b
```

### `chat()`

Model은 요청마다 지정한다.

```python
response = provider.chat(
    model="qwen3:8b",
    messages=messages,
    tools=tools,
    options=options,
)
```

---

## 6. Tool schema 변환

`ToolRegistry.schemas()`가 반환하는 공통 Tool 형식을 Provider API가 사용하는 Function Tool 형식으로 변환한다.

```python
def build_function_tools(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:

    if not tools:
        return []

    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            },
        }
        for tool in tools
    ]
```

입력:

```python
{
    "name": "add",
    "description": "두 숫자를 더합니다.",
    "parameters": {...},
}
```

출력:

```python
{
    "type": "function",
    "function": {
        "name": "add",
        "description": "두 숫자를 더합니다.",
        "parameters": {...},
    },
}
```

---

## 7. `provider/ollama.py`

Ollama Provider 구현이다.

Provider 객체에는 Model이 아니라 연결 정보만 저장한다.

```python
provider = OllamaLLM(
    host="http://localhost:11434"
)
```

주요 기능:

```text
get_available_models()
chat()
message 변환
Tool Call 변환
ChatOptions → Ollama options 변환
```

### 모델 조회

```python
models = provider.get_available_models()
```

### 요청

```python
response = provider.chat(
    model="qwen3:8b",
    messages=messages,
    tools=tool_registry.schemas(),
    options=ChatOptions(
        temperature=0.2,
        max_tokens=4096,
    ),
)
```

### 공통 옵션 변환

예:

```text
ChatOptions.max_tokens
→ Ollama num_predict

ChatOptions.temperature
→ Ollama temperature
```

Ollama 전용 옵션은:

```python
options.extra
```

를 통해 전달한다.

---

## 8. `provider/openai.py`

OpenAI-compatible Provider 구현이다.

주 사용 대상:

- vLLM
- 실제 OpenAI API
- 기타 OpenAI-compatible 서버

예:

```python
provider = OpenAILLM(
    base_url="http://localhost:8000/v1",
    api_key="EMPTY",
)
```

모델 조회:

```python
models = provider.get_available_models()
```

채팅:

```python
response = provider.chat(
    model=models[0],
    messages=messages,
    tools=tool_registry.schemas(),
)
```

vLLM 전용 옵션은 `extra_body`를 통해 전달할 수 있다.

```python
ChatOptions(
    extra={
        "extra_body": {
            "top_k": 40,
        }
    }
)
```

추가 OpenAI-compatible request argument가 필요하면:

```python
ChatOptions(
    extra={
        "request": {
            "frequency_penalty": 0.2,
        }
    }
)
```

형태로 전달할 수 있다.

---

## 9. Optional Dependency

모든 LLM SDK를 강제로 설치하지 않는다.

예:

```text
사용자 A
✓ ollama
✗ openai

사용자 B
✗ ollama
✓ openai
```

둘 다 프로그램이 정상 실행되어야 한다.

따라서 `llm/__init__.py`나 `provider/__init__.py`에서 모든 Provider를 미리 import하지 않는다.

외부 SDK도 Provider를 실제 생성할 때 import한다.

예:

```python
class OllamaLLM(BaseLLM):

    def __init__(self, host: str):
        from ollama import Client
```

이렇게 하면 Ollama Provider를 사용하지 않는 사용자는 `ollama` 패키지를 설치할 필요가 없다.

---

## 10. `registry.py`

사용할 수 있는 LLM Provider 목록을 관리한다.

### ProviderSpec

```python
from dataclasses import dataclass


@dataclass
class ProviderSpec:
    name: str
    display_name: str
    module: str
    class_name: str
    dependency: str | None = None
```

예:

```python
ProviderSpec(
    name="ollama",
    display_name="Ollama",
    module="src.llm.provider.ollama",
    class_name="OllamaLLM",
    dependency="ollama",
)
```

OpenAI-compatible:

```python
ProviderSpec(
    name="openai",
    display_name="OpenAI Compatible",
    module="src.llm.provider.openai",
    class_name="OpenAILLM",
    dependency="openai",
)
```

### LLMProviderRegistry

주요 기능:

```text
register()
unregister()
get()
all()
is_installed()
available()
create()
```

Provider 생성 시 실제 Provider 모듈을 동적으로 import한다.

```python
provider = registry.create(
    "ollama",
    host="http://localhost:11434",
)
```

---

## 11. 사용자 Provider 선택

UI 또는 CLI에서 다음처럼 보여줄 수 있다.

```text
LLM Provider

✓ Ollama
✓ OpenAI Compatible
✗ Anthropic
✗ Gemini
```

사용자가 Provider를 선택한다.

```text
사용자: Ollama
```

그때:

```python
provider = registry.create("ollama")
```

그리고 실제 서버에서 모델 목록을 조회한다.

```python
models = provider.get_available_models()
```

이후 사용자가 기본 모델을 선택하거나 Agent의 Model Router가 선택한다.

---

## 12. Provider와 Model 선택 흐름

```text
사용자 또는 Agent
 ↓
Provider 선택
 ↓
LLMProviderRegistry
 ↓
Provider Instance
 ↓
get_available_models()
 ↓
Model 선택
 ↓
chat(model=...)
```

Provider는 오래 유지할 수 있다.

Model은 요청마다 바꿀 수 있다.

---

## 13. 향후 Model Router

작업 난이도나 유형에 따라 Model을 자동 선택할 수 있다.

예:

```text
간단한 작업
→ Ollama / qwen3:8b

복잡한 작업
→ Ollama / qwen3:30b
```

Provider까지 바꿀 수도 있다.

```text
간단한 작업
→ Ollama / small model

복잡한 작업
→ vLLM / large model
```

개념적으로:

```python
route = model_router.select(task)

response = route.provider.chat(
    model=route.model,
    messages=messages,
    tools=tools,
)
```

Model Router는 Agent Loop 이후 단계에서 구현한다.

---

## 14. Agent와의 연결

Agent가 알아야 하는 LLM 인터페이스는 매우 단순하다.

```python
response = provider.chat(
    model=model,
    messages=messages,
    tools=tool_registry.schemas(),
    options=options,
)
```

Tool Call이 있으면:

```python
for call in response.tool_calls:
    result = tool_executor.execute(
        call.name,
        call.arguments,
    )
```

Tool Result를 messages에 추가한 뒤 다시 같은 Provider에 요청한다.

---

## 15. 전체 흐름

```text
User
 ↓
Agent Loop
 ↓
Provider 선택
 ↓
Model 선택
 ↓
provider.chat(...)
 ↓
LLM Response
 ↓
Tool Call 있음?
 ├─ NO → 최종 응답
 │
 └─ YES
      ↓
 ToolExecutor
      ↓
 Tool Result
      ↓
 messages 추가
      ↓
 provider.chat(...)
```

---

## 16. 현재 LLM 계층의 완료 상태

```text
✓ BaseLLM
✓ ToolCall
✓ LLMResponse
✓ ChatOptions
✓ Ollama Provider
✓ OpenAI-compatible Provider
✓ Provider Registry
✓ Optional Dependency 구조
✓ Provider 선택
✓ 모델 목록 조회
✓ 요청별 Model 선택
✓ 공통 생성 옵션
✓ Provider별 특수 옵션
✓ Tool Calling 변환 구조
```

다음 단계에서는 이 LLM 계층을 Agent Loop에 연결한다.
