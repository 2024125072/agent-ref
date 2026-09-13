# Claude Code 소스 구조 분석서

## agent-ref 구현을 위한 정적 분석 레퍼런스

**문서 버전:** 1.0 · **분석 기준일:** 2026-09-09 · **분석 대상:** 사용자가 제공한 `claude-code-main.zip`

> **이 문서의 대상은 업로드된 소스 스냅샷이다.** 현재 배포 중인 Claude Code의 전체 구현이나 특정 공식 릴리스와 동일하다고 인증한 문서가 아니다. 핵심 실행 경로를 정적으로 추적했으며, 빌드·실행·성능 측정은 하지 않았다. 본문에서 “이 코드”, “스냅샷”은 모두 이 압축본을 가리킨다.

### 이 문서를 읽는 순서

전체 구조를 이해하려면 **1–5장 → 8–11장 → 15–18장** 순서가 좋다. 최소 에이전트 구현에 바로 연결하려면 **5장 공통 루프, 8장 Subagent 실행, 10장 Tool 계약, 11장 실행 파이프라인, 22장 적용 메모**를 먼저 읽는다. 원문을 다시 확인할 때는 본문의 **[Cxx] 근거 링크와 부록 A의 파일·줄 번호**를 사용한다.

표시의 의미는 다음과 같다. **관찰**은 실제 코드에서 확인한 내용, **해석**은 여러 코드의 책임을 묶어 설명한 내용, **조건부**는 기능 플래그·실행 모드에 따라 활성화되는 내용, **제안**은 우리 구현에 적용할 설계안이다. 의사 코드는 원문을 축약한 설명이며 그대로 실행하는 구현 코드가 아니다.

---

## 1. 가장 먼저 확정해야 할 결론

이 소스에서 에이전트의 중심은 거대한 `Agent` 클래스가 아니라 **공통 비동기 생성기 `query()`와 그 실행에 필요한 context**다. 메인 대화와 일반 Subagent는 서로 다른 추론 엔진을 쓰지 않는다. `AgentTool`이 선택한 정의로 실행 환경을 준비하고, `runAgent()`가 다시 `query()`를 호출한다. [C02](#source-c02) [C03](#source-c03) [C12](#source-c12)

다만 다음 네 가지는 분리해서 이해해야 한다.

| 구분 | 실제 의미 | 혼동하면 생기는 문제 |
|---|---|---|
| Agent 정의 | 역할·모델·도구·프롬프트 등 실행 설정 | 정의 하나를 영구 실행 객체로 취급하게 됨 |
| Agent 실행 | context, 메시지, 취소, task, transcript로 구성된 실행 상태 | 하나의 클래스에 모든 수명과 상태를 몰아넣게 됨 |
| Tool 노출 | LLM에 어떤 호출 인터페이스를 보여 주는지 | 목록에 있으면 무조건 허용된다고 오해함 |
| Tool 실행 권한·격리 | 요청 허용 여부와 실제 프로세스의 자원 접근 범위 | permission, subprocess, venv, sandbox를 같은 것으로 취급함 |

이 문서에서 사용하는 **`AgentRun`은 분석을 위한 개념적 이름**이다. 실제 스냅샷에 그 이름의 단일 핵심 실행 클래스가 있다는 뜻이 아니다. 실행 책임은 `runAgent`, `ToolUseContext`, `LocalAgentTaskState`, `sessionStorage` 등에 나뉘어 있다. [C11](#source-c11) [C12](#source-c12) [C22](#source-c22) [C24](#source-c24) [C27](#source-c27)

### 1.1 앞선 설명에서 바로잡아야 할 부분

| 이전에 단순화해서 설명한 내용 | 실제 코드 기준의 정확한 설명 |
|---|---|
| “Claude Code 공식 핵심 소스다.” | 비공식 미러라고 스스로 설명하는 소스 스냅샷이다. 공식 릴리스와의 동일성은 검증하지 못했다. |
| “Main Agent가 새 Agent 정의를 만든다.” | 일반 `AgentTool`은 **이미 로드된 정의를 선택해 실행을 시작**한다. 임의의 새 역할 정의를 영구 등록하는 기능과는 다르다. |
| “Main/Subagent는 계속 재귀적으로 생성할 수 있다.” | 같은 엔진을 재사용하지만 일반 외부 사용자 Subagent의 도구 목록에서는 `Agent`가 기본적으로 제외된다. |
| “모든 대화가 QueryEngine을 거친다.” | headless 경로는 `QueryEngine`을 사용하지만 REPL 화면은 `query()`를 직접 순회하는 경로가 있다. |
| “Plugin은 MCP 서버로만 실행된다.” | MCP 외에 command hook 프로세스, LSP 설정, agent 정의, skill/command 프롬프트 등 여러 구성요소를 제공한다. |
| “ToolExecutor가 모든 Tool을 Sandbox에 넣는다.” | 공통 실행기는 검증·권한·hook·결과를 처리한다. OS sandbox 래핑은 조사한 코드에서 주로 shell 실행 경로에 있다. |
| “TaskManager라는 한 객체가 Agent 상태를 관리한다.” | 실행 task의 공통 함수와 타입별 구현으로 책임이 분산돼 있다. LLM 작업 목록용 Task도 별도로 존재한다. |
| “대화 venv 대신 plugin별 venv를 써야 한다.” | 이 코드에서 그렇게 결론낼 수 없다. Python 환경 구성은 우리 요구사항에 맞춰 별도로 설계할 부분이다. |

각 항목의 근거는 뒤의 해당 장에서 설명한다. 이 정정이 중요한 이유는 **구현 아이디어를 추출하는 것과 소스에 없는 추상화를 실제 구현이라고 설명하는 것을 구분해야 하기 때문**이다.

---

## 2. 분석 대상, 출처, 검증 범위

### 2.1 압축본 식별

| 항목 | 확인값 |
|---|---|
| 원본 파일 | `claude-code-main.zip` |
| ZIP SHA-256 | `cced6861b653ed5ca2ffa7bfc0010f76244930eea3781cb0da3e8d219190b0bb` |
| ZIP 내부 엔트리 | 2,205개 — 디렉터리 포함 |
| 실제 파일 | 1,903개 |
| `src/` 아래 파일 | 1,902개 |
| 확장자별 파일 | `.ts` 1,332 / `.tsx` 552 / `.js` 18 / `.md` 1 |
| 전체 텍스트 줄 | 513,517줄 — README 포함, `splitlines()` 기준 |
| `src/` 텍스트 줄 | 513,237줄 |
| 압축 해제된 파일 크기 합계 | 30,393,663 bytes |

위 수치는 업로드 파일을 직접 열어 계산한 목록 통계다. 주석·빈 줄·UI 코드까지 포함하므로 **순수 에이전트 로직 규모나 실행 가능한 코드 줄 수로 해석하면 안 된다.** 재검증을 위한 파일별 해시와 근거 범위는 함께 제공하는 `claude-code-reference-evidence.json`에 기록했다.

### 2.2 출처에 대해 말할 수 있는 것과 없는 것

README는 2026년 3월 31일 npm 배포의 source map 노출에서 얻어진 소스를 미러링했으며, 공식 Anthropic 저장소가 아니라고 설명한다. 이것은 **README 작성자의 주장**으로만 확인했다. 원본 npm artifact와 대조하거나 공식 서명·커밋으로 인증하지 않았다. [C01](#source-c01)

루트에는 README와 `src/`가 있지만 `package.json`, lockfile, `tsconfig`, 빌드 설정, Git 이력, LICENSE 파일은 없다. `.test.` 또는 `.spec.` 이름의 테스트 파일도 발견하지 못했다. 따라서 정확한 의존성 버전, 실제 빌드 플래그, 테스트 통과 여부, 실행 성능은 이 분석으로 확정할 수 없다. **공개 열람 가능 여부와 재사용 허가 여부도 동일시하지 않는다.**

README 일부 표기는 실제 소스와 맞지 않는다. 예를 들어 거대 파일의 규모를 설명한 부분과 달리 실제 `QueryEngine.ts`는 1,295줄, `Tool.ts`는 792줄이다. 이 문서는 README의 요약 수치를 재인용하지 않고 실제 파일과 함수 호출을 기준으로 작성했다. [C01](#source-c01)

### 2.3 분석 범위

전체 파일 목록을 조사하고 다음 경로를 집중 추적했다: 세션 진입점, 공통 query loop, Agent 정의 로딩·선택·실행, context 분리, Tool 계약·등록·실행·병렬화, 실행 task·메시지·재개, Plugin 로딩·ZIP 캐시·MCP·hook, shell sandbox, coordinator 모드.

반면 모든 UI 컴포넌트, 인증·결제·원격 제어, 모든 개별 Tool의 세부 알고리즘, 전체 권한 엔진의 모든 분기, 외부 sandbox 패키지 내부를 완전 감사한 것은 아니다. 특히 **파일이 존재한다는 것, 기능 플래그 코드가 있다는 것, 사용자에게 활성화돼 있다는 것은 서로 다른 주장**이다.

---

## 3. 전체 계층과 실제 제어 흐름

### 3.1 주요 계층

```text
사용자 입력 / SDK 입력
        │
        ├── Interactive REPL ──────────────────────┐
        │                                         │
        └── print / headless → ask()                 │
                                  │               │
                           submitMessage()        │
                                  └──────┬────────┘
                                         ▼
                                  query(params)
                                         │
                       context 정리 → 모델 streaming 호출
                                         │
                  ┌──────────────────────┴───────────────────┐
                  │                                          │
             일반 응답                                  tool_use
                  │                                          │
          stop hook / 종료 판단                     Tool orchestration
                                                             │
                                             검증 → hook → 권한 → call
                                                             │
                  ┌──────────────────┬───────────────────────┼───────────┐
                  │                  │                       │           │
             Built-in Tool      AgentTool                MCP Tool    SkillTool
                  │                  │                       │           │
            파일 / shell      정의 선택 + 실행 준비     로컬/원격 서버  프롬프트 삽입
                                     │                                   또는 fork
                                  runAgent()
                                     │
                            child context + 같은 query()
                                     │
                       결과 / 실행 task / sidechain transcript
                                     │
                             부모 도구 결과·알림으로 복귀
```

이 그림은 호출 관계를 중심으로 재구성한 것이다. 별도의 프로세스 경계를 그린 그림이 아니다. **일반 local Subagent는 동일 프로세스 안의 비동기 실행일 수 있으며, AgentTool 호출 자체가 새로운 OS 프로세스를 뜻하지 않는다.** MCP와 shell은 별도의 실행 경계를 가질 수 있다. [C02](#source-c02) [C10](#source-c10) [C12](#source-c12) [C36](#source-c36) [C39](#source-c39)

### 3.2 실제 디렉터리에서 볼 곳

```text
src/
├── query.ts                         # 공통 agentic loop
├── QueryEngine.ts                   # headless 세션 wrapper
├── Tool.ts                          # Tool / ToolUseContext / ToolResult 계약
├── tools.ts                         # 기본 도구·MCP 도구 pool 구성
├── Task.ts                          # 실행 task 공통 타입
├── screens/REPL.tsx                 # 대화형 화면과 query 호출
├── cli/print.ts                     # headless 입력·출력 경로
├── query/deps.ts                    # 모델 호출·압축 의존성 주입 경계
├── services/tools/
│   ├── toolExecution.ts            # 검증·권한·hook·실제 호출
│   ├── toolHooks.ts                # hook와 권한 판정의 결합
│   ├── toolOrchestration.ts        # 비-streaming batch 실행
│   └── StreamingToolExecutor.ts    # streaming 중 도구 스케줄링
├── tools/AgentTool/
│   ├── AgentTool.tsx               # LLM에 노출되는 실행 시작 도구
│   ├── runAgent.ts                 # child context와 공통 루프 연결
│   ├── loadAgentsDir.ts            # 정의 스키마·로딩·우선순위
│   ├── agentToolUtils.ts           # 도구 해석·결과·비동기 수명
│   └── resumeAgent.ts              # transcript 기반 재개
├── tasks/LocalAgentTask/LocalAgentTask.tsx
├── utils/
│   ├── forkedAgent.ts              # child context 생성
│   ├── sessionStorage.ts           # 세션·sidechain 저장
│   ├── tasks.ts                    # 별도의 LLM 작업 목록
│   ├── task/framework.ts           # 실행 task 공통 관리
│   ├── plugins/                    # Plugin loader와 구성요소 통합
│   └── sandbox/sandbox-adapter.ts  # 외부 sandbox runtime 연결
└── coordinator/coordinatorMode.ts  # 조건부 coordinator 정책
```

이 구조는 참고할 책임 경계를 보여 주지만 디렉터리 배치를 그대로 복사해야 한다는 뜻은 아니다. 특히 이름이 `utils`여도 실제로는 중요한 상태·수명·권한 로직을 소유한다. [C03](#source-c03)–[C41](#source-c41)

---

## 4. Session, Turn, Agent, Task를 구분하기

| 개념 | 이 코드에서의 대응 | 수명과 역할 |
|---|---|---|
| Session | QueryEngine의 메시지·상태, REPL 상태, sessionStorage | 여러 사용자 입력과 복수 Agent 실행을 포함할 수 있는 대화 단위 |
| 사용자 입력 처리 | `submitMessage()` 또는 REPL 입력 경로 | 명령·첨부·프롬프트를 준비하고 query 실행을 시작 |
| Query 실행 | `query()` / `queryLoop()` | 모델 호출과 Tool 결과 반영을 반복하다 종료 사유를 반환 |
| 모델 호출 1회 | `deps.callModel()` | 다음 응답 또는 Tool 요청을 얻는 추론 단계 |
| AgentDefinition | `loadAgentsDir.ts`의 정의 타입 | 역할·모델·도구·설정 |
| Agent 실행 | `runAgent` + child context + task + transcript | 정의를 사용해 수행하는 실제 작업 |
| 실행 Task | `src/Task.ts`, LocalAgentTask 등 | 실행 중·완료·실패·중단 상태와 출력·취소 관리 |
| 작업 목록 Task | `src/utils/tasks.ts` | 제목, 담당자, 선행 작업 등 LLM이 관리하는 업무 항목 |

소스의 `turnCount`는 query 내부 제어를 위한 카운터다. 사용자 대화 턴, 모델 API 요청 수, Tool 호출 수와 모두 동일한 값이 아니다. 복구 분기에서 같은 턴으로 다시 추론할 수 있으므로 `maxTurns` 하나를 **전체 비용·요청 횟수·실행 시간의 완전한 상한**으로 해석하면 안 된다. [C03](#source-c03) [C05](#source-c05) [C22](#source-c22) [C23](#source-c23)

---

## 5. 공통 Agent Loop: `query()`

### 5.1 진입점의 역할 분리

`QueryEngine`은 메시지 배열, AbortController, 권한 거절 정보, usage, 파일 상태 등을 가진 세션 wrapper다. `submitMessage()`에서 입력을 처리하고 `query()`를 순회한다. `ask()`는 이 엔진을 만들어 사용하는 headless 인터페이스다. 반면 `REPL.tsx`에는 `query()`를 직접 순회하는 호출이 있다. 따라서 **세션 wrapper와 추론 루프는 다른 계층**으로 읽어야 한다. [C02](#source-c02)

`query()`는 `queryLoop()`를 감싼 async generator다. 메시지뿐 아니라 stream event, request-start event, tombstone, 도구 요약 등을 yield하고, 마지막에는 Terminal 결과를 return한다. **최종 return과 중간 yield는 서로 다른 채널**이다. 일반 `for await` 소비자는 종료 반환값을 자동으로 최종 업무 결과로 처리하지 않는다. [C03](#source-c03)

### 5.2 입력 계약

핵심 입력은 `messages`, `systemPrompt`, `userContext`, `systemContext`, `canUseTool`, `toolUseContext`, `querySource`다. 선택적으로 모델 fallback, 출력 토큰 override, maxTurns, task budget, deps 등을 받는다. 즉 루프가 Agent 정의 파일을 직접 해석하는 것이 아니라 **이미 구성된 실행 문맥을 받아 작동**한다. [C03](#source-c03)

`query/deps.ts`는 모델 호출, microcompact, autocompact, UUID 생성 같은 일부 의존성을 교체할 수 있게 한다. 모델 호출의 실제 기본 구현은 `queryModelWithStreaming`으로 연결된다. 이것은 테스트 가능한 좁은 경계이지만 query 전체가 외부 상태와 완전히 분리된 순수 함수라는 뜻은 아니다. [C06](#source-c06)

### 5.3 정상 실행 흐름

```python
# 개념을 보여 주는 의사 코드. 원문을 축약했으며 실행용 구현이 아니다.
async def query_loop(state, deps):
    while True:
        state = await prepare_context_and_budgets(state)
        assistant_messages = []
        pending_tool_uses = []

        async for event in deps.call_model(state):
            yield event
            collect_messages(event, assistant_messages)
            collect_tool_uses(event, pending_tool_uses)
            maybe_start_streaming_tools(event)

        if not pending_tool_uses:
            decision = await evaluate_stop_hooks_and_recovery(state)
            if decision.continue_query:
                state = decision.next_state
                continue
            return decision.terminal

        tool_results, new_context = await drain_or_run_tools()
        state = next_state(
            messages=state.messages + assistant_messages + tool_results,
            context=new_context,
        )
```

도구 실행 결과를 받은 뒤에는 새 메시지와 context를 다음 State에 반영한다. [C42](#source-c42)

핵심은 **실제 응답에 `tool_use` 블록이 들어왔는지**로 다음 도구 실행 필요를 판단한다는 점이다. 단순히 모델의 `stop_reason` 문자열만 검사하는 구현이 아니다. streaming executor가 활성화된 경우, 모델 응답 전체가 끝나기 전에 인식된 Tool 호출의 실행을 시작할 수 있다. [C04](#source-c04)

### 5.4 매 반복에서 준비하는 것

문맥 준비에는 도구 결과의 크기 예산 조정, microcompact, autocompact, 조건부 context collapse 등이 포함된다. 이후 현재 메시지와 user/system context, system prompt, 도구 목록, thinking 설정, AbortSignal을 모델 호출에 전달한다. 이 때문에 “메시지 리스트를 그대로 API에 보내는 10줄 loop”와 본질은 같지만 **문맥을 유지하고 실패를 복구하는 책임**이 크게 추가돼 있다. [C04](#source-c04) [C05](#source-c05)

`State`에는 메시지와 context 외에 자동 압축 추적, 출력 토큰 복구 횟수, reactive compact 재시도 여부, 진행 중 도구 요약, stopHookActive, turnCount, 직전 continue 사유가 들어간다. 반복문 밖의 임의 전역 변수가 아니라 **이어지는 실행 단계의 상태를 명시적으로 모은 형태**라는 점이 참고할 만하다. [C03](#source-c03)

### 5.5 정상 종료만 있는 것이 아니다

| 분기 | 관찰한 처리 | 구현 시 읽어야 할 의미 |
|---|---|---|
| Tool 요청 존재 | 도구 실행·결과 수집 후 메시지와 context 갱신 | 재추론은 Tool 결과를 받은 다음 수행 |
| 출력 토큰 제한 | 출력 한도 조정 또는 continuation 복구 | 응답 잘림을 무조건 최종 실패로 처리하지 않음 |
| prompt too long | 조건부 압축·재시도, 재시도 가드 | 복구도 무한하지 않도록 추적 필요 |
| stop hook의 차단 오류 | 오류를 문맥에 넣고 다시 실행 | 일반 텍스트가 나왔어도 항상 끝나지 않음 |
| 중단 | 남은 Tool 결과를 정리하거나 오류 결과 보충 | 프로토콜상 짝이 맞지 않는 대화를 남기지 않음 |
| 모델 오류·한도 | 사유별 Terminal 또는 예외 경로 | 종료 이유와 사용자 목표 달성은 별도 |

특히 어떤 API 오류 분기는 마지막 오류 메시지를 남긴 뒤 Terminal reason을 `completed`로 반환한다. 따라서 여기의 **`completed`를 “사용자가 요청한 업무가 성공적으로 끝났다”는 증명으로 사용하면 안 된다.** 완료·오류 판단은 메시지 내용, 상위 실행 결과, 검증 정책을 함께 봐야 한다. [C05](#source-c05)

### 5.6 가장 중요한 프로토콜 불변식

Tool 호출 ID와 결과 ID의 대응을 유지해야 한다. 중단·fallback 과정에서 이전 시도의 Tool 결과가 새 응답에 섞이지 않아야 하며, 미완료 Tool 호출은 다음 모델 요청 전에 정리해야 한다. `yieldMissingToolResultBlocks`, executor discard, 불완전 Tool 호출 필터링이 이 목적에 관여한다. **재시도 시 결과를 버리는 것과 이미 실행된 외부 부작용을 되돌리는 것은 전혀 다르다.** [C04](#source-c04) [C21](#source-c21) [C28](#source-c28)

---

## 6. AgentDefinition: 역할 정의를 로드하는 방식

### 6.1 실제 정의의 구성

`AgentDefinition` 계열 타입은 `agentType`, `whenToUse`, 도구 허용·제외 목록, 모델, effort, 권한 모드, maxTurns, skills, MCP 서버, hooks, memory, background, isolation 등을 갖는다. built-in 정의는 함수형 `getSystemPrompt()`와 선택적 callback을 가질 수 있고, 사용자·Plugin 정의는 로딩한 프롬프트를 closure로 제공한다. [C07](#source-c07)

```text
AgentDefinition
├── identity: agentType, source, plugin/파일 출처
├── selection: whenToUse
├── instructions: getSystemPrompt(), initialPrompt
├── model: model, effort
├── capability: tools, disallowedTools, skills, mcpServers
├── execution policy: permissionMode, maxTurns, background
└── environment: memory, isolation, baseDir, 기타 옵션
```

여기서 도구 목록과 권한 모드는 같은 필드가 아니다. 어떤 Tool을 프롬프트에 제공하더라도 실제 인자에 대한 실행 허가는 나중에 판정된다. 또 스키마에 필드가 있다고 모든 source에서 그대로 허용되는 것도 아니다. Plugin agent의 일부 frontmatter는 별도로 무시한다. [C07](#source-c07) [C14](#source-c14) [C34](#source-c34)

### 6.2 로딩과 우선순위

정의 로더는 built-in, Markdown 기반 agent 파일, Plugin agent, 명령행 정의 등 여러 출처를 모으고, 동일 `agentType`을 Map에 순서대로 넣어 최종 활성 정의를 정한다. 이 스냅샷의 **낮은 우선순위 → 높은 우선순위**는 다음과 같다. [C08](#source-c08)

```text
built-in → plugin → userSettings → projectSettings → flagSettings → policySettings
```

`allAgents`와 `activeAgents`를 구분하므로 “모든 정의를 보관”하는 것과 “이번 실행에서 선택할 정의”를 분리할 수 있다. 필수 MCP 서버 충족 여부나 허용된 agent type, deny rule도 별도로 작용한다. built-in 목록조차 실행 모드·기능 플래그에 따라 달라진다. Explore·Plan·verification·coordinator worker가 모두 무조건 활성화된다고 가정하면 안 된다. [C08](#source-c08) [C09](#source-c09)

### 6.3 모델 결정 순서

`getAgentModel()`에서는 환경 변수 `CLAUDE_CODE_SUBAGENT_MODEL`이 우선하며, 그다음 Tool 호출 override, 그다음 정의의 모델 또는 inherit 경로를 사용한다. 모델 별칭과 부모의 실제 모델, 제공자별 모델 ID 처리도 개입한다. “정의 파일에 model 하나 쓰면 항상 그것을 쓴다”는 구조가 아니다. [C14](#source-c14)

이 동작은 **해당 스냅샷 기준**이다. 현재 공식 문서의 기본값·버전별 정책으로 이 코드의 분기를 덮어 설명하지 않는다.

---

## 7. `AgentTool`: 새 정의가 아니라 실행을 시작하는 도구

### 7.1 LLM에 보이는 인터페이스

이 Tool은 설명과 작업 프롬프트를 받고, 선택적으로 `subagent_type`, model, background 실행, isolation 등을 받는다. team이나 특정 내부 모드 관련 필드는 조건부로 스키마에 포함된다. 일반적인 사용은 다음처럼 해석할 수 있다. [C09](#source-c09)

```json
{
  "description": "인증 관련 코드 조사",
  "prompt": "인증 진입점과 세션 검증 흐름을 찾아 파일 위치와 함께 설명해라.",
  "subagent_type": "general-purpose",
  "run_in_background": false
}
```

이는 설명용 입력 예시다. 실제 사용 가능한 agent type과 노출되는 필드는 그 실행의 활성 정의와 플래그에 따라 달라진다.

### 7.2 선택 규칙

명시적 `subagent_type`이 있으면 해당 활성 정의를 찾는다. 생략되면 fork 기능이 켜진 경로에서는 fork agent, 그렇지 않은 일반 경로에서는 general-purpose가 선택된다. 허용 목록과 deny rule에서 제외되면 실행하지 않는다. 따라서 **Main Agent가 필요할 때 실행 인스턴스를 동적으로 만드는 구조**는 맞지만, **매 호출마다 새로운 AgentDefinition을 창작·등록하는 구조**는 아니다. [C09](#source-c09)

우리에게 중요한 구분은 다음과 같다.

```text
정의 등록: "researcher라는 역할을 앞으로 사용할 수 있게 만든다"
실행 시작: "researcher 정의로 이번 문서 조사 작업을 수행한다"
```

첫 번째는 profile/definition 관리이고, 두 번째가 일반 `AgentTool`의 핵심이다.

### 7.3 실행 준비 순서

`AgentTool.call()`은 agent type 선택, 프롬프트 구성, foreground/background 결정, worker tool pool 구성, ID 할당, 선택적 worktree 생성, 실행 task 등록, `runAgent()` 호출까지 연결한다. background이면 즉시 사용할 수 있는 agentId와 출력 경로 등을 반환하고, 별도 수명 함수가 결과를 모아 알림을 보낸다. [C10](#source-c10)

순서를 개념적으로 정리하면 다음과 같다.

```text
입력 확인
  → 사용 가능한 AgentDefinition 선택
  → ordinary / fork / teammate 등 실행 경로 구분
  → 모델·프롬프트·Tool pool·권한 전달 정보 준비
  → agentId 할당
  → 선택적 worktree / cwd 결정
  → 실행 task 등록
  → runAgent()
  → foreground 결과 반환 또는 background 실행 정보 반환
```

`AgentTool`이 정의하는 `isConcurrencySafe()`는 true다. 이는 부모 실행기에서 AgentTool들을 겹쳐 실행할 수 있게 하지만, 자식들이 수정하는 파일까지 자동으로 충돌 제어한다는 뜻은 아니다. [C10](#source-c10) [C41](#source-c41)

---

## 8. `runAgent()`: 같은 루프에 다른 실행 문맥을 넣기

### 8.1 핵심 단계

`runAgent()`는 선택한 정의와 부모 ToolUseContext, availableTools, permission callback, 비동기 여부, override 등을 받는다. 내부에서 모델, 메시지, user/system context, 도구, AbortController, hook·skill·MCP 구성을 준비하고, child ToolUseContext를 만든 뒤 **같은 `query()`를 호출**한다. [C11](#source-c11) [C12](#source-c12)

```text
runAgent(definition, parentContext, ...)
  ├── 모델과 agentId 결정
  ├── 초기 메시지 / fork 메시지 구성
  ├── 권한 상태를 읽는 getAppState wrapper 구성
  ├── 정의의 tools / disallowedTools 적용
  ├── system prompt 구성
  ├── 취소 controller 선택
  ├── SubagentStart hook 결과 삽입
  ├── 지정 skills 내용 사전 로드
  ├── agent 전용 MCP 연결 + tool 병합
  ├── createSubagentContext(...)
  ├── sidechain transcript / metadata 시작
  └── query(childParams)
        ├── 메시지·진행 이벤트 yield
        ├── 기록 가능한 메시지 저장
        └── 종료 후 cleanup
```

이것이 가장 직접적인 구현 레퍼런스다. ResearchAgent, CodingAgent마다 별도 loop를 만들지 않고 **정의와 실행 문맥을 바꿔 같은 엔진을 사용**한다.

### 8.2 부모 문맥을 전부 공유하는가?

아니다. 일반 실행과 fork 실행, foreground와 background에서 다르게 처리한다. [C11](#source-c11) [C12](#source-c12) [C13](#source-c13)

| 항목 | 일반 Subagent에서 관찰한 처리 | fork 또는 조건부 차이 |
|---|---|---|
| 대화 메시지 | 작업용 초기 메시지를 구성 | 부모 transcript를 가져오고 미완료 Tool 호출 정리 |
| system prompt | 정의에 맞춰 생성 | 부모 prompt와 정확한 tool 집합을 맞추는 경로 |
| 파일 읽기 상태 | 독립 상태를 준비 | 부모 상태를 복제해 문맥·cache 일관성 유지 |
| 내용 대체·예산 상태 | 자식 상태로 분리·복제 | 부모 prefix와 동일한 결정 유지가 중요 |
| 임시 집합 | nested memory/skill discovery 등을 자식별 생성 | 기본적으로 부모의 가변 집합 공유를 피함 |
| AppState 조회 | 부모 최신 상태를 읽되 권한 등을 wrapper로 조정 | 상태 전체를 스냅샷 복사하는 것과 다름 |
| 일반 AppState 변경 | background에서는 no-op 경로 | 공유가 필요한 실행만 명시적으로 허용 |
| 실행 task 상태 변경 | root store에 도달하는 별도 setter 유지 | background shell 등록·중단도 이 통로 필요 |
| UI callback | 기본적으로 부모 UI 제어 기능 제거 | 명시적 공유 옵션은 별도 |
| 취소 | 동기 실행은 부모 controller 공유 | 비동기 실행은 기본적으로 독립 controller |
| 실제 파일시스템 | 같은 작업 디렉터리를 쓸 수 있음 | worktree 옵션이 있으면 checkout 분리 가능 |

특히 `createSubagentContext()`의 일반 기본값과 `runAgent()`가 넘기는 명시적 override를 구분해야 한다. helper는 새 child AbortController를 만들 수 있지만, `runAgent()`는 동기·비동기 정책에 맞춘 controller를 명시적으로 선택한다. **helper 한 함수만 읽고 전체 취소 정책을 추론하면 틀릴 수 있다.** [C11](#source-c11) [C13](#source-c13)

### 8.3 권한의 상속은 단순 복사가 아니다

자식의 `getAppState()`는 부모 최신 권한 상태를 참고하면서 정의의 permissionMode, 비동기 prompt 회피 정책 등을 적용한다. 부모의 특정 권한 모드는 자식 설정보다 우선한다. 명시적인 `allowedTools`가 전달된 경우 부모의 session-level allow를 그대로 누적하지 않고 주어진 목록으로 바꾸되, SDK 명령행 allow 규칙을 보존하는 경로가 있다. [C11](#source-c11)

또한 `AgentTool`에서 만드는 worker tool pool은 부모가 현재 보는 제한된 도구 목록과 별도로 조립될 수 있다. 예를 들어 coordinator의 도구가 좁더라도 worker는 업무에 필요한 도구 pool을 갖는다. **도구 pool 조립에 사용한 모드와 실제 호출 허가 결정을 동일시하면 안 된다.** [C10](#source-c10) [C11](#source-c11)

### 8.4 종료 시 정리하는 것

`finally`에서는 agent 전용 MCP, session hooks, prompt-cache 추적, 파일 상태 cache, 초기 fork 메시지, 추적 registry, transcript subdir mapping, agent별 todo 항목, agent가 생성한 background shell 작업 등을 정리한다. 이것은 “LLM 호출이 끝났다”와 “그 실행이 소유한 자원을 다 정리했다”를 구분하는 사례다. [C12](#source-c12)

다만 `finally`가 있다는 사실만으로 cleanup의 모든 하위 함수가 실패·정지해도 항상 뒤 작업까지 실행된다는 보장을 얻을 수는 없다. 우리 구현에서는 cleanup 단계별 오류 정책과 timeout을 별도로 설계할 필요가 있다. **이 문장은 개선 제안이며, 이 코드의 장애 재현 결과가 아니다.**

---

## 9. 일반 Subagent, fork, background, teammate는 다르다

| 경로 | 주요 특징 | 반드시 구분할 점 |
|---|---|---|
| 일반 Subagent | 선택한 정의와 작업 중심 문맥으로 실행 | 부모 대화 전체를 무조건 전달하지 않음 |
| Fork agent | 부모 메시지·프롬프트·Tool prefix를 유지하는 조건부 경로 | OS fork가 아니며 문맥 재사용 전략 |
| Background agent | task에 등록되고 비동기로 진행·통지 | 별도의 정의 종류라기보다 실행 수명 정책 |
| Teammate | team/메시지/별도 runner 등의 추가 경로 | 일반 subagent와 동일한 무제한 트리로 보면 안 됨 |
| Worktree agent | 다른 checkout/cwd에서 실행 | 프로세스·패키지·보안 격리와는 별개 |

일반 외부 사용자 경로에서 `ALL_AGENT_DISALLOWED_TOOLS`는 `Agent`를 포함한다. 내부 사용자 조건에서는 달라질 수 있고, fork에는 별도 재귀 방지 판단이 있다. teammate도 team 생성에 관한 평면 구조 제약을 둔다. **엔진이 재사용 가능하다는 사실과 재귀 생성이 정책적으로 허용된다는 사실은 다르다.** [C09](#source-c09) [C14](#source-c14)

우리 구현에서 다단계 Agent 트리를 허용하려면 depth, 실행 수, 전체 비용, 순환 위임, 부모 종료 정책을 새로 정의해야 한다. 이 스냅샷을 그대로 읽으면 무제한 재귀 멀티에이전트가 자동으로 완성된다는 결론은 나오지 않는다.

---

## 10. Tool 계약과 Registry

### 10.1 Tool은 함수만이 아니라 실행 계약이다

`Tool.ts`의 Tool은 TypeScript의 구조적 타입이다. 반드시 공통 부모 클래스를 상속하는 구조는 아니다. `buildTool()`은 기본 동작을 채워 정의를 만드는 helper다. 실제 계산은 `call()`이 하지만, 호출 가능 여부·입력·권한·동시성·결과 표현은 별도 계약으로 제공된다. [C15](#source-c15)

| 계약 영역 | 대표 항목 | 의미 |
|---|---|---|
| 식별·발견 | name, aliases, description, prompt, searchHint | 모델·사용자가 도구를 알아보는 정보 |
| 입력·출력 | inputSchema, inputJSONSchema, outputSchema | 검증과 모델 노출 형식 |
| 실행 | call, onProgress | 실제 작업과 중간 진행 정보 |
| 실행 정책 | isConcurrencySafe, isReadOnly, isDestructive, interruptBehavior | 스케줄러·권한·중단 판단의 재료 |
| 권한 | checkPermissions, validateInput | Tool 고유 검증·정책 판단 |
| 결과 | mapToolResultToToolResultBlockParam, maxResultSizeChars | 모델용 결과 변환과 큰 결과 처리 |
| 부가 효과 | newMessages, contextModifier | 프롬프트·실행 문맥 갱신 |
| UI | 여러 render 계열 함수 | terminal UI와 결합된 표시 계약 |

`buildTool()`의 기본값은 concurrency-safe false, read-only false, destructive false 등이다. 기본 `checkPermissions`가 allow를 반환하는 경우도 있지만 이것은 **전체 플랫폼의 모든 요청이 무조건 허용된다는 뜻이 아니다.** 일반 정책·deny rule·상위 permission callback과 함께 읽어야 한다. [C15](#source-c15) [C18](#source-c18)

### 10.2 ToolResult는 문자열보다 넓다

결과에는 실제 `data` 외에 추가 메시지 `newMessages`, context 변경 함수, MCP metadata가 포함될 수 있다. SkillTool처럼 “도구 실행 성공”뿐 아니라 다음 모델 호출의 프롬프트·권한 문맥을 바꾸는 Tool이 있기 때문이다. 그래서 실행기의 반환값을 문자열로 평탄화하면 실제 계약 일부를 잃는다. [C15](#source-c15) [C38](#source-c38)

### 10.3 Registry는 이번 실행의 Tool pool을 만든다

`getAllBaseTools()`는 기본 도구 후보를 모으고, `getTools()`는 모드·deny rule·isEnabled 등을 반영한다. `assembleToolPool()`은 기본 도구와 MCP 도구를 병합하고 이름 중복을 처리하며 안정적인 순서를 만든다. 기본 도구와 MCP 도구를 구획별 정렬하는 것은 도구 schema prefix의 불필요한 변화를 줄이기 위한 구조다. [C16](#source-c16)

같은 파일의 `getMergedTools()`는 단순 병합 성격이므로 모든 helper가 같은 필터·중복 제거·정렬 보장을 준다고 가정하지 않는다. “Registry”라는 이름 하나보다 **어느 함수가 완성된 실행용 pool을 소유하는지**가 중요하다. [C16](#source-c16)

---

## 11. Tool 실행 파이프라인

### 11.1 모델 출력에서 실제 실행까지

```text
model의 tool_use(name, id, input)
   │
   ├─ 현재 tool pool에서 이름/alias 확인
   ├─ 중단 여부 확인
   ├─ schema.safeParse(input)
   ├─ Tool.validateInput(input)
   ├─ 관찰용 입력 복제 / backfill
   ├─ PreToolUse hooks
   ├─ hook decision + 일반 권한 규칙 결합
   ├─ 허용된 최종 입력 확정
   ├─ tool.call(input, context, ...)
   ├─ 결과 직렬화 / 큰 결과 저장
   ├─ post hooks / 실패 hooks / 진행 이벤트
   └─ tool_result 및 추가 context/messages → query loop
```

이 순서는 개념적인 요약이다. 실제 구현은 async generator를 사용해 중간 hook 진행 정보나 Tool 결과를 먼저 내보낼 수 있으므로 “post hook이 끝나기 전까지 어떤 결과도 보이지 않는다”는 보장은 아니다. [C17](#source-c17) [C19](#source-c19)

### 11.2 잘못된 호출은 대화에서 사라지지 않는다

이름을 찾을 수 없거나 schema·Tool 고유 검증이 실패하거나 권한이 거절되면, 실행기는 오류 Tool 결과를 구성해 모델에 돌려준다. 이렇게 해야 모델이 인자나 행동을 수정할 수 있고, Tool call/result 대응도 유지된다. unknown tool을 Python 예외로 던진 뒤 전체 대화를 잃는 구현과 다르다. [C17](#source-c17)

단, 모든 예외를 무조건 삼킨다는 뜻은 아니다. 취소·API 오류·상위 generator 종료는 별도의 처리 경로가 있다. 문서에서 “Tool 오류는 결과로 돌아온다”는 말은 **일반적인 실행 실패 변환 경로**를 가리킨다.

### 11.3 입력 원본과 관찰용 입력을 구분한다

코드는 실제 호출용 입력과 UI·hook·관찰용 입력의 복제본을 구분하고, backfill 때문에 모델이 생성한 기존 메시지 prefix가 바뀌지 않게 한다. 프롬프트 cache와 transcript 일관성까지 영향을 주므로 “편의를 위해 Tool 입력 객체에 절대 경로를 덮어쓰기” 같은 수정도 실행기 수준의 책임이 된다. [C17](#source-c17)

Hook은 updatedInput을 전달할 수 있고 권한 판정도 이를 반영한다. 따라서 감사·추적 설계에서는 **모델이 제안한 인자와 실제 승인·실행된 인자**를 구분해 기록하는 편이 낫다. 이는 이 구현을 참고한 설계 제안이다.

### 11.4 Hook의 allow가 모든 규칙을 이기는가?

아니다. `resolveHookPermissionDecision()`은 hook이 allow를 반환한 경우에도 deny/ask 규칙을 검사한다. deny는 그대로 거절하고, ask 규칙이나 상호작용이 필요한 Tool은 권한 callback으로 보낸다. hook deny는 거절이며, 별도 확정 결정을 내리지 않은 경우 일반 `canUseTool` 경로로 이어진다. [C18](#source-c18)

```text
PreToolUse: allow
      │
      ├── 일반 deny 일치 → 거절
      ├── ask / 별도 상호작용 요구 → 권한 확인 경로
      └── 허용 조건 충족 → 실행
```

이 점은 Plugin hook을 붙일 때 특히 중요하다. hook이 “허용”을 출력했다는 이유만으로 사용자의 deny 정책을 우회하게 만들면 안 된다.

### 11.5 Sandbox는 이 공통 파이프라인의 보편적 실행 단계가 아니다

실제 `tool.call()`이 파일 API를 쓸 수도, MCP 서버로 요청할 수도, shell을 실행할 수도 있다. 공통 실행기에서 모든 Tool을 하나의 OS sandbox 프로세스로 옮기는 구조는 확인되지 않았다. sandbox 적용 위치는 Tool의 실행 backend를 따라 추적해야 한다. [C19](#source-c19) [C36](#source-c36) [C39](#source-c39)

---

## 12. 병렬 실행: batch와 streaming 두 경로

### 12.1 비-streaming batch 실행

`toolOrchestration.ts`는 입력을 parse하고 `isConcurrencySafe(input)`을 평가해 연속된 안전 호출들을 batch로 묶는다. 안전하지 않은 호출은 직렬 구간을 형성한다. 안전 batch의 병렬 상한은 `CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY` 환경 변수 또는 기본값 10을 사용한다. [C20](#source-c20)

```text
도구 요청 순서:   Read A | Read B | Edit C | Read D | Read E
실행 batch:      [ A, B 병렬 ] → [ C 단독 ] → [ D, E 병렬 ]
```

이는 설명용 예시다. 실제 안전 여부는 도구명만이 아니라 해당 Tool이 정의한 입력 기반 predicate로 결정한다. **read-only와 concurrency-safe는 개념적으로 다른 속성**이다.

### 12.2 streaming 실행

`StreamingToolExecutor`는 `queued → executing → completed → yielded` 상태를 관리한다. 실행 중인 것이 없거나, 새 요청과 현재 실행 중인 요청 모두 concurrency-safe이면 시작할 수 있다. unsafe 요청은 순서 장벽이 된다. 모델 streaming과 Tool 실행이 겹치면서 진행·완료 결과를 수집한다. [C21](#source-c21)

조사한 streaming 스케줄러의 admission 조건에는 비-streaming과 같은 “기본 10개” 카운터 조건이 보이지 않는다. 따라서 **10개 상한을 전체 시스템의 공통 제한으로 적으면 부정확하다.** 별도의 병렬도 제한을 우리 실행기에 추가하는 것은 제안이며 이 코드의 보장을 그대로 옮긴 것이 아니다.

### 12.3 contextModifier 처리의 차이

batch orchestrator는 병렬 batch에서 수집한 context 변경을 Tool 요청 순서에 맞춰 적용하는 코드가 있다. 반면 streaming executor는 안전하지 않은 Tool의 contextModifier를 반영하는 경로를 사용한다. Tool 타입의 주석만 보고 모든 경로가 동일하다고 생각하면 안 된다. [C15](#source-c15) [C20](#source-c20) [C21](#source-c21)

우리 최소 구현에서는 **context를 수정하는 Tool은 직렬로 제한**하는 편이 이해하기 쉽다. 병렬 context 변경을 허용하려면 deterministic merge 규칙과 동일한 두 실행 경로의 의미를 먼저 정의해야 한다.

### 12.4 이 스케줄러가 해결하지 않는 것

부모별 Tool 실행 순서를 조정한다고 해서 서로 다른 Subagent의 파일 쓰기, 원격 서비스 상태 변경, GPU 자원 사용까지 전역 잠금으로 보호하는 것은 아니다. MCP의 read-only 힌트도 서버가 제공한 선언이다. **병렬 실행 가능 판정은 자원 충돌 검증이나 보안 증명이 아니다.** [C10](#source-c10) [C21](#source-c21) [C36](#source-c36)

---

## 13. 실행 Task와 작업 목록 Task

### 13.1 Runtime Task

`src/Task.ts`의 TaskType은 local_bash, local_agent, remote_agent, in_process_teammate 등의 실행 종류다. 공통 상태는 pending/running/completed/failed/killed이며 ID, 시작·종료 시간, outputFile, outputOffset, notified 등을 가진다. 타입별 `Task` 인터페이스의 공통 동작은 kill이다. **범용 TaskManager가 모든 spawn·render를 다형적으로 소유하는 구조는 아니다.** [C22](#source-c22)

`LocalAgentTaskState`에는 agentId, prompt, selectedAgent, model, abortController, result, progress, pendingMessages, isBackgrounded, messages, retain, diskLoaded 등이 추가된다. 같은 실행이 foreground인지 background인지, UI가 보관 중인지, 메시지가 disk에서 로드됐는지까지 수명 관리에 반영한다. [C24](#source-c24)

```text
생성(pending) → 실행(running) ─┬→ completed
                             ├→ failed
                             └→ killed

foreground / background: 실행 상태와 별도의 속성
UI retain / eviction:     업무 완료 여부와 별도의 보관 정책
```

### 13.2 LLM 작업 목록

`src/utils/tasks.ts`의 Task는 subject, description, owner, blocks, blockedBy, metadata를 갖고 상태는 pending/in_progress/completed다. 이것은 LLM이 계획·분담을 관리하는 업무 항목이다. 실행 task와 이름이 같지만 데이터 모델과 수명이 다르다. [C23](#source-c23)

```text
작업 항목: "API 인증 테스트 작성"
    ├── 선행 작업: "인증 정책 확인"
    └── 담당자: worker-A

실행 기록: worker-A가 시작한 agent 실행 1회
    ├── running / failed / completed
    ├── transcript와 출력
    └── 취소 controller
```

두 개념을 합치면 업무 항목을 다시 시도할 때 기존 실패 실행을 덮어쓰거나, 작업 목록의 completed를 실행 성공으로 오해하기 쉽다. 우리 구현에서도 필요하다면 `WorkItem`과 `RunTask`처럼 이름부터 구분하는 편이 낫다.

---

## 14. Background 수명, 알림, 중단

### 14.1 실행 등록과 결과 회수

비동기 실행은 `registerAsyncAgent()`로 root AppState의 task store에 등록된다. 출력 경로는 agent transcript를 가리키도록 준비하고, 기본적으로 부모와 연결되지 않은 AbortController를 쓴다. `runAsyncAgentLifecycle()`이 메시지를 순회하면서 진행률을 갱신하고 마지막 결과를 만든다. [C24](#source-c24) [C25](#source-c25)

특히 정상 경로는 **task를 completed로 먼저 전환한 다음**, 결과 분류·worktree 후처리·알림 부가 작업을 수행한다. 상태 전환을 부가 처리 뒤에 두면 TaskOutput 같은 대기자가 불필요하게 막힐 수 있기 때문이다. 이는 코드의 실제 순서에서 확인되는 설계다. [C25](#source-c25)

### 14.2 완료 알림은 일반 사용자 입력과 다르다

`enqueueAgentNotification()`은 task id, tool-use id, 상태, 요약, 결과, usage 등을 담은 task-notification을 큐에 넣는다. notified를 AppState에서 확인·갱신해 반복 통지를 방지한다. 완료 task의 메모리 제거도 notified, retain 등 상태와 결합된다. [C24](#source-c24) [C26](#source-c26)

이것은 프로세스 내부의 중복 방지이며, 영속 메시지 브로커의 트랜잭션이나 장애 복구를 포함한 exactly-once 전달 보장을 뜻하지 않는다. 알림과 task 저장이 어떤 장애에서도 원자적으로 보존된다고 가정해서는 안 된다.

### 14.3 foreground에서 background로 전환

AgentTool에는 foreground task를 먼저 등록하고, 메시지를 기다리는 동안 background 전환 신호와 경합하는 경로가 있다. 이미 진행 중인 iterator를 이어받아 계속 실행할 수 있도록 처리한다. 이는 “현재 작업을 취소한 뒤 처음부터 같은 작업을 다시 실행”하는 단순 구조와 다르다. [C10](#source-c10)

### 14.4 중단과 실패

AbortError는 killed, 일반 오류는 failed 경로로 분리한다. 중단된 실행도 지금까지 수집한 메시지로 부분 결과를 만들어 통지할 수 있다. 성공·실패·중단 뒤에는 skill/dump 상태 같은 실행별 자료를 정리한다. [C25](#source-c25)

우리 구현에 옮길 때는 “부모 취소가 모든 자식에게 전파되는가?”, “background 자식은 부모 턴이 끝나도 살아 있는가?”, “세션 종료에서는 어떤 자원까지 종료하는가?”를 서로 다른 정책으로 정의해야 한다. 하나의 global cancel flag로 해결하기 어렵다는 점이 이 코드에서 드러난다.

---

## 15. Transcript 저장과 Agent 재개

### 15.1 저장 단위

자식 대화는 세션 아래 sidechain transcript로 저장된다. 경로는 세션 프로젝트 디렉터리를 기준으로 다음 형태다. [C27](#source-c27)

```text
<session-project-dir>/
└── <sessionId>/
    └── subagents/
        └── [선택적 하위 디렉터리]/
            ├── agent-<agentId>.jsonl
            └── agent-<agentId>.meta.json
```

metadata에는 agentType, worktreePath, description 등이 들어간다. transcript는 기록 가능한 메시지를 정리해 부모 UUID와 연결된 message chain으로 저장한다. 이는 살아 있는 함수 stack이나 OS 프로세스 메모리를 dump하는 방식이 아니다.

초기 기록·metadata는 일부 best-effort 경로로 시작하고, 실행 중 메시지 기록도 오류를 로깅하는 처리가 있다. 따라서 이 코드만 보고 모든 메시지가 crash-safe하게 영속 저장된다고 보장할 수 없다. [C12](#source-c12) [C27](#source-c27)

### 15.2 실제 재개 인터페이스

이 스냅샷에서 AgentTool의 스키마에 일반적인 `resume` 인자를 넣는 형태는 확인되지 않았다. `SendMessageTool`이 대상 Agent를 확인하고, 실행 중이면 pendingMessages에 넣고, 종료됐거나 메모리에서 제거된 실행이면 `resumeAgentBackground()`를 호출하는 경로가 있다. [C09](#source-c09) [C29](#source-c29)

```text
SendMessage(to=agentId, message=...)
        │
        ├── 실행 중 → 메시지 queue에 추가
        └── 종료 / 메모리 제거됨
                 → transcript + metadata 로드
                 → 불완전 Tool 호출 / 부적절한 블록 정리
                 → 활성 정의와 Tool pool 재구성
                 → 새 메시지 추가
                 → 같은 agentId로 비동기 실행 재등록
                 → runAgent() → query()
```

### 15.3 재개는 프로세스 복원이 아니다

`resumeAgentBackground()`는 저장된 정의 ID를 바탕으로 **현재 활성 정의**를 다시 찾고, 없으면 general-purpose로 대체하는 경로가 있다. 이전 worktree가 사라졌다면 부모 cwd로 돌아가는 코드도 있다. 따라서 동일한 Agent ID라고 이전 실행의 정의·도구·작업 디렉터리가 바이트 단위로 동일하게 복원되는 것은 아니다. [C28](#source-c28)

이 차이는 우리에게 중요한 설계 선택이다. 재현성을 높이려면 definition version, plugin version, model 설정, workspace 정책을 실행 metadata에 고정할 수 있다. 기존 worktree가 없을 때 조용히 부모 폴더로 넘어가지 않고 실패시키는 선택도 가능하다. **이것은 우리 구현의 개선 제안이지 스냅샷의 기존 보장이 아니다.**

### 15.4 실행 완료와 작업 성공을 다시 구분하기

`finalizeAgentTool()`은 마지막 assistant 텍스트를 찾고, 마지막 메시지가 Tool 요청뿐이면 이전 assistant 텍스트를 사용할 수 있다. 이는 결과를 정리하는 로직이지 테스트 통과나 산출물 유효성을 독립 검증하는 시스템이 아니다. [C43](#source-c43)

따라서 우리 시스템의 최종 결과에는 적어도 “실행이 정상 종료했는가”와 “요청의 완료 조건을 충족했는가”를 별도로 표현할 여지가 필요하다. 예컨대 소스 분석 Agent가 텍스트를 반환했다고 코드 수정·테스트가 실제 완료된 것은 아니다.

---

## 16. Plugin: 패키지·설치·구성요소 로딩

### 16.1 Plugin의 구성요소

Plugin manifest는 commands, agents, skills, hooks, MCP 서버, LSP 서버, output styles, 일부 settings 등을 묶는다. 이 schema에서 임의의 Python 함수를 Core에 import하여 Tool 클래스로 등록하는 일반 인터페이스는 확인되지 않았다. **Plugin은 실행 엔진 하나가 아니라 여러 확장 기능을 배포하는 패키지 경계**다. [C30](#source-c30)

```text
plugin-root/
├── .claude-plugin/plugin.json      # manifest
├── agents/                        # agent 정의
├── commands/                      # 프롬프트 command
├── skills/                        # skill 설명과 부속 자원
├── hooks/                         # hook 설정·스크립트
├── .mcp.json                      # MCP 서버 설정의 한 경로
└── 기타 실행 파일 / 서버 코드 / 자원
```

이 트리는 대표적인 구성 예시이며 모든 항목이 필수인 것은 아니다. manifest에는 기본 위치 외 별도 경로를 지정할 수 있다. 더구나 조사한 loader에는 manifest가 없으면 최소 이름·설명을 만들어 사용하는 fallback도 있다. 따라서 “모든 Plugin에 manifest가 반드시 있어야 로딩된다”고 단정하면 이 코드와 맞지 않는다. [C30](#source-c30) [C31](#source-c31)

### 16.2 설치·로딩 흐름

`pluginLoader.ts`에는 npm, Git, GitHub, git subdirectory, local source 등의 캐시 경로가 있다. 버전별 cache로 복사한 후 manifest와 구성요소를 읽는다. 전체 로딩은 marketplace, session-only plugin, builtin을 모은 뒤 이름 우선순위·관리자 정책·의존성 확인을 거쳐 enabled/disabled/errors로 나눈다. [C31](#source-c31)

```text
패키지 출처 / 설치 설정
       ↓
캐시 확보: npm / Git / GitHub / local 등
       ↓
버전별 설치 위치
       ↓
manifest + 구성요소 경로 해석
       ↓
출처 병합 및 managed settings 적용
       ↓
Plugin 간 의존성 확인 / 비활성화
       ↓
Agent·Skill·Hook·MCP·LSP 등 각 Registry/설정으로 통합
```

session-only `--plugin-dir`는 일반적으로 같은 이름의 설치본을 우선하지만 managed settings에서 잠근 Plugin에는 예외가 있다. 로딩의 마지막 의존성 검사는 존재·활성 여부를 확인하는 것이어서 항상 위상 정렬된 실행 순서를 요구하는 것은 아니다. [C31](#source-c31) [C33](#source-c33)

### 16.3 두 가지 “의존성”을 구분해야 한다

`dependencyResolver.ts`는 **Plugin A가 Plugin B를 요구하는 관계**를 처리한다. 의존성 closure 계산에는 cycle, missing dependency, 허용되지 않은 cross-marketplace 자동 설치를 검출하는 경로가 있다. 로딩 후 missing/disabled dependency가 있으면 해당 실행 세션에서 Plugin을 disabled로 내리는 처리도 있다. [C33](#source-c33)

이것은 `numpy`, `torch`, `httpx` 같은 **Python package dependency 설치기**가 아니다. npm source 처리에서 `npm install --prefix ...`를 쓰는 경로는 있지만, 분석한 핵심 Plugin·MCP 경로에서는 대화별 Python venv를 만들고 필요한 pip 패키지를 자동 설치하는 일반 기능을 확인하지 못했다. [C31](#source-c31)

### 16.4 Plugin agent에는 별도의 신뢰 경계가 있다

Plugin agent는 이름을 namespace하고 설치 경로 변수를 프롬프트에 반영한다. 이 loader는 Plugin agent frontmatter의 `permissionMode`, `hooks`, `mcpServers`를 명시적으로 무시한다. Plugin이 몰래 정의 내부에서 권한·실행 hook·서버를 넣는 경로를 줄이고, manifest 수준의 선언 경로와 구분하려는 구조다. [C34](#source-c34)

이는 “Plugin은 신뢰했으니 내부의 모든 설정을 그대로 수용”하는 방식보다 세분된 정책이다. 우리 구현에서도 **배포 패키지 승인, Agent 정의 승인, 실제 Tool 실행 승인**을 다른 단계로 둘 수 있다.

---

## 17. ZIP cache와 우리의 배포 구상

### 17.1 실제로 ZIP 실행 경로가 있는가?

있다. `zipCache.ts`는 환경 변수로 켜는 ZIP cache 모드를 구현하고, versioned Plugin ZIP을 세션 임시 폴더에 풀어 사용하는 경로를 제공한다. 임시 extraction 경로 생성에는 동시 생성 경합을 피하는 공유 promise가 있고, 세션 종료 cleanup을 등록한다. [C32](#source-c32)

```text
공유 / 버전 cache
  marketplace/plugin/version.zip
                │
                ▼
       세션별 임시 extraction 위치
                │
                ▼
       일반 Plugin loader가 파일 경로로 소비
```

주석에는 headless 사용 등 적용 범위가 설명돼 있지만, 문서화된 모든 제한이 전체 코드에서 강제되는지까지 감사하지는 않았다. 따라서 이 모드를 **모든 Claude Code 시작 시 기본으로 실행되는 동작**으로 표현하면 안 된다.

### 17.2 사용자 구상과 닮은 점·다른 점

| 항목 | 사용자 구상 | 이 스냅샷에서 관찰한 것 |
|---|---|---|
| 공유 형식 | Plugin ZIP | 조건부 ZIP cache 지원 |
| 압축 해제 | 시작 시 `data/` 아래 설치 | ZIP 모드에서 세션 임시 디렉터리 추출 |
| Tool 코드 위치 | 설치된 Plugin 내부 | 스크립트·MCP 서버·hook 등이 설치 경로를 참조 가능 |
| 실행 dependency | 대화 runtime의 venv에 설치 | 일반적인 세션별 Python dependency 관리자는 확인 못 함 |
| 실행 격리 | 넓은 의미의 대화 runtime | context/worktree/process/shell sandbox 등 여러 경계가 별도 존재 |

따라서 **ZIP 배포 → 설치 경로 → 구성요소 발견 → 실행 경계 연결**이라는 흐름은 직접 참고할 수 있다. 반면 세션별 Python runtime은 이 코드를 복사하는 부분이 아니라 우리의 요구사항으로 추가하는 부분이다.

### 17.3 ZIP 보안에 대한 분석 한계

압축 해제 코드를 확인했다고 path traversal, symlink, archive bomb, 권한 보존 정책까지 완전 검증한 것은 아니다. 그 판단에는 하위 unzip 구현과 경로 검증을 더 추적해야 한다. 이 문서는 해당 ZIP loader에 취약점이 있다고 주장하지 않는다. 우리 installer를 작성할 때 이 항목들을 명시적인 테스트 대상으로 삼는 것은 별개의 설계 제안이다.

---

## 18. MCP, Skill, Hook: 실행 방식이 서로 다르다

### 18.1 MCP는 Tool 실행을 연결하는 프로토콜 경계

MCP client는 `tools/list` 결과를 내부 Tool 객체로 바꾸고, 호출 시 서버로 전달한다. 이름 namespace, 설명, input JSON schema, permission handling, 결과·metadata 변환이 adapter에 들어간다. LLM은 공통 Tool 인터페이스를 보고, 실제 실행은 MCP transport가 담당한다. [C36](#source-c36)

```text
ToolExecutor
    → MCP Tool adapter
        → MCP client / callTool
            ├── stdio: 서버 subprocess
            ├── HTTP / SSE: 외부 서버
            └── 일부 SDK/내부 경로: in-process 연결
```

따라서 **MCP = 항상 별도 프로세스**, **MCP = 보안 sandbox**, **MCP = dependency manager**라는 등식은 모두 성립하지 않는다.

Plugin의 MCP 통합은 기본 `.mcp.json`과 manifest 설정을 병합하고 서버명을 `plugin:<pluginName>:<server>`로 namespace한다. stdio 환경에는 설치 위치를 나타내는 `CLAUDE_PLUGIN_ROOT`와 데이터 위치를 나타내는 `CLAUDE_PLUGIN_DATA`를 넣는다. 설치 위치와 변경 가능한 데이터 위치를 구분한다는 점이 유용하다. [C35](#source-c35)

### 18.2 MCP metadata는 선언이지 검증 결과가 아니다

MCP adapter의 concurrency-safe와 read-only 판단은 서버의 `readOnlyHint`를 사용하며 기본값은 false다. destructiveHint 등도 사용한다. 즉 외부 도구가 제공한 annotation이 스케줄링·분류에 영향을 준다. **외부 서버가 읽기 전용이라고 선언했다는 사실과 실제로 부작용이 없다는 사실은 다르다.** [C36](#source-c36)

### 18.3 Skill은 대개 프롬프트 확장이다

`SkillTool`은 prompt slash command를 처리하고 추가 메시지와 contextModifier를 반환한다. allowedTools나 모델 설정을 문맥에 반영할 수 있으며, `context: fork`인 skill은 별도의 fork 실행 경로를 사용한다. 일반 skill이 곧 Python 함수라는 뜻은 아니다. [C38](#source-c38)

Skill 안에 스크립트가 있더라도 그 파일이 문서에 존재한다는 이유만으로 자동 실행되는 것은 아니다. 실제 실행은 shell·MCP 등 연결된 도구 호출 경로가 필요하다. 설계상 **절차 지식과 실행 능력**을 분리해서 읽어야 한다.

### 18.4 Hook은 실제 명령을 실행할 수 있다

`utils/hooks.ts`는 workspace 신뢰 확인과 Plugin 변수 치환 뒤 shell 또는 PowerShell을 통해 child process를 spawn하는 경로를 갖는다. 조사한 command hook spawn 경로는 BashTool의 sandbox 래퍼를 공통으로 통과하는 형태가 아니다. [C37](#source-c37)

따라서 Plugin 보안을 BashTool만 보고 평가할 수 없다. 실행 가능한 경계는 최소한 shell Tool, hook command, MCP stdio 서버, 원격 MCP 서버를 각각 봐야 한다. Plugin 자체가 ZIP이라는 사실은 실행 코드의 권한을 줄여 주지 않는다.

### 18.5 용어 한 줄 정리

| 용어 | 의미 |
|---|---|
| Tool | 검증 가능한 입력으로 호출하는 작업 인터페이스 |
| Skill | 모델이 따를 지식·절차·프롬프트 묶음 |
| Command | 사용자가 호출하는 명령 진입점; prompt형도 있음 |
| AgentDefinition | 별도 실행 문맥에서 사용할 역할 설정 |
| Hook | 수명·실행 이벤트에 연결되는 처리; 실제 명령 실행 가능 |
| MCP server | Tool·자원 등을 프로토콜로 제공하는 실행 주체 |
| Plugin | 위 구성요소를 배포·설치·활성화하는 패키지 |

---

## 19. Sandbox, venv, subprocess, worktree

### 19.1 이름이 비슷해도 격리하는 대상이 다르다

| 경계 | 분리하는 것 | 이것만으로 보장하지 않는 것 |
|---|---|---|
| Agent context | 메시지·일부 cache·UI callback·실행 상태 | OS 파일·네트워크 접근 차단 |
| Worktree / cwd | 수정할 checkout 또는 작업 위치 | 임의의 다른 파일 접근 금지 |
| Python venv | Python interpreter/package 환경 | 파일시스템·네트워크 보안 제한 |
| Subprocess | 프로세스 주소 공간·별도 수명 | 사용자 권한으로 접근 가능한 자원 차단 |
| OS sandbox | 설정된 파일·네트워크 등 접근 규칙 | Tool 업무 의미의 안전성·정답성 |
| Remote MCP | 원격 실행 위치와 API 경계 | 원격 서버 자체의 신뢰·보안 |

앞의 네 항목을 하나의 “sandbox”라고만 부르면 보안 범위가 모호해진다. 사용자 구상의 넓은 **Session Runtime** 안에 dependency 환경과 workspace를 포함하되, **Security Sandbox**는 별도 기능으로 명시하는 편이 좋다. Python venv가 package 환경을 분리한다는 점은 공식 Python 문서와도 일치한다. [C13](#source-c13) [C36](#source-c36) [C39](#source-c39) [C40](#source-c40) [W04](#web-w04)

### 19.2 실제 shell sandbox 적용 경로

BashTool은 입력과 설정을 바탕으로 sandbox 사용 여부를 판단해 shell 실행기에 전달한다. `Shell.ts`는 적용이 필요한 경우 `SandboxManager.wrapWithSandbox()`로 명령을 감싼 뒤 process를 spawn한다. `sandbox-adapter.ts`는 설정을 파일·네트워크 정책으로 바꾸고 외부 `@anthropic-ai/sandbox-runtime`에 연결한다. [C39](#source-c39) [C40](#source-c40)

```text
BashTool
  → shouldUseSandbox(...)
  → Shell.exec(...)
  → SandboxManager.wrapWithSandbox(...)   # 적용되는 경우
  → OS 프로세스 실행
```

외부 sandbox-runtime 패키지 내부는 이 ZIP에 포함돼 있지 않다. 따라서 여기서 확인한 것은 **설정→정책→wrapper 연결 방식**이며 OS enforcement 자체를 구현·감사한 결과가 아니다. 플랫폼 지원, dependency 설치 상태, 활성화 설정도 영향을 준다.

### 19.3 cwd를 전역 변경하지 않는 이유

`utils/cwd.ts`는 AsyncLocalStorage를 이용해 비동기 실행 흐름에 cwd override를 연결한다. `AgentTool`은 worktree나 별도 cwd 경로를 이 방식으로 감쌀 수 있다. 여러 Agent가 동시에 일할 때 프로세스 전역 `chdir()`로 서로 작업 위치를 바꾸지 않도록 하는 구조다. [C10](#source-c10) [C13](#source-c13)

이것은 안전한 context 전달 방식이지 OS 접근 제한이 아니다. 실제 Tool이 파일 경로를 어떻게 해석하고 검증하는지는 Tool backend와 permission policy의 책임으로 남는다.

---

## 20. Coordinator 모드와 Main Agent 설계

`coordinatorMode.ts`는 기능 플래그와 환경 변수 둘 다 확인하는 조건부 모드다. 단순히 “모든 메인 대화는 coordinator”라고 볼 수 없다. 활성화되면 coordinator prompt, 사용 가능한 Tool 필터, built-in worker 정의, 비동기 실행 정책 등이 함께 달라진다. [C41](#source-c41)

```text
Coordinator
  ├── 작업 분해와 위임
  ├── worker 결과 수집
  ├── 구현·검증 작업 조정
  └── 사용자에게 종합 결과 전달

Worker
  └── 일반 실행 문맥과 공통 query loop로 실제 작업 수행
```

여기서 참고할 점은 coordinator를 별도의 추론 엔진으로 만들지 않는다는 것이다. **역할 프롬프트 + tool 제한 + worker 정의 + 실행 정책**이 결합돼 coordination behavior를 구성한다. prompt만 넣고 끝내는 것도 아니고 완전히 다른 agent loop를 만드는 것도 아니다. [C08](#source-c08) [C10](#source-c10) [C16](#source-c16) [C41](#source-c41)

coordinator prompt에 작업 분담·검증·쓰기 조정 지침이 존재하더라도 그것은 자동 파일 잠금과 같지 않다. 같은 파일에 대한 수정 충돌을 확실히 막으려면 worktree, 자원 잠금, 변경 병합 등의 별도 장치가 필요하다. 해당 문장은 구현 선택에 대한 해석이며 충돌이 실제 재현됐다는 뜻은 아니다.

---

## 21. 실패 처리, 보장 범위, 검증 포인트

### 21.1 이 코드에서 직접 참고할 방어 구조

| 영역 | 관찰한 방어 구조 | 보장 범위 |
|---|---|---|
| 잘못된 Tool 입력 | schema·도구별 validation·오류 결과 | 유효하지 않은 요청을 실행 전에 처리하는 경로 |
| 권한 충돌 | hook allow보다 일반 deny/ask 검사 | hook만으로 상위 규칙을 우회하지 않음 |
| 중단·fallback | 누락 Tool 결과 보충, executor discard | 대화 프로토콜 일관성 유지 |
| 복구 반복 | compact 재시도·출력 복구 상태 추적 | 무조건 처음부터 같은 요청 반복하지 않음 |
| Agent 자원 | finally에서 MCP/hook/cache/shell 정리 | 정상·오류 종료를 공통 cleanup에 연결 |
| Background 완료 | 완료 상태를 부가 후처리보다 먼저 반영 | 결과 대기자의 불필요한 차단 줄임 |
| 통지 | notified 확인·갱신 | 프로세스 내 반복 통지 억제 |
| Plugin 의존성 | cycle·missing·cross-marketplace 검사 | 설치·활성화 관계 검증 |

근거: [C05](#source-c05) [C12](#source-c12) [C17](#source-c17) [C18](#source-c18) [C21](#source-c21) [C24](#source-c24) [C25](#source-c25) [C33](#source-c33)

### 21.2 이 분석으로 보장하지 않는 것

완전한 sandbox 격리, 모든 Tool의 실제 read-only 성질, 전역 파일 충돌 방지, transcript의 무손실 저장, 재개의 완전 재현성, 외부 부작용의 exactly-once 실행, 사용자 목표의 자동 성공 검증, 현재 배포판에서 모든 기능 활성화 여부는 이 분석의 보장 범위가 아니다.

특히 **`completed` 상태, 최종 텍스트 존재, Tool 호출 성공**은 서로 다른 신호다. 실제 구현 문서에서는 업무별 완료 조건과 검증 결과를 따로 정의해야 한다. 예를 들어 “코드 수정”이라면 변경 파일 존재만으로 충분한지, 테스트 실행과 통과까지 필요한지 계약으로 결정해야 한다.

### 21.3 우리 구현을 위한 테스트 제안

아래 표는 스냅샷의 테스트를 실행한 결과가 아니라, 관찰한 구조에서 도출한 **새 테스트 요구사항**이다.

| ID | 상황 | 기대 검증 |
|---|---|---|
| T01 | 모르는 Tool 이름 또는 잘못된 JSON 인자 | 부작용 없이 Tool 오류 결과 생성, call ID 유지 |
| T02 | Tool이 순차로 두 번 필요한 요청 | 각 결과가 messages에 반영된 뒤 다음 추론 |
| T03 | Tool call 수신 직후 사용자가 취소 | 미완료 결과 정리, 뒤 실행이 무단으로 시작되지 않음 |
| T04 | 모델 fallback 중 이전 Tool이 실행 중 | 시도 ID 분리, 오래된 결과가 새 대화에 섞이지 않음 |
| T05 | hook allow와 사용자 deny가 충돌 | deny 우선, 실행 함수 호출 횟수 0 |
| T06 | read 2개 뒤 write 1개 | 안전 batch·직렬 장벽 순서 검증 |
| T07 | 두 Agent가 서로 다른 cwd 사용 | 작업 경로가 전역 상태로 오염되지 않음 |
| T08 | foreground 취소와 background 유지 | 선택한 부모·자식 취소 정책 일치 |
| T09 | 완료 후 부가 알림 처리가 지연 | task 상태 조회는 이미 terminal을 반환 |
| T10 | 종료한 Agent에 새 메시지 전달 | transcript 복구·정의 버전 정책·추가 메시지 반영 |
| T11 | Plugin 두 개가 상충하는 dependency 요구 | 설치 전 충돌 감지 또는 명시적 실패 |
| T12 | ZIP 경로 탈출·비정상 archive 입력 | 설치 root 외 파일 생성 금지, 크기·개수 제한 |
| T13 | 세션 venv 생성·설치 중 동시 Tool 요청 | 환경 설치 잠금과 준비 상태 관리 |
| T14 | 작업 텍스트는 반환했지만 산출물 없음 | 실행 종료와 업무 완료를 구분한 결과 |

---

## 22. agent-ref 적용 메모 — 소스 사실과 분리한 제안

> 이 장은 Claude Code에 이미 구현된 Python 구조를 설명하는 것이 아니다. 사용자가 정한 **Main Agent의 동적 위임, `create_subagent` Tool, ZIP Plugin, `data/` 설치, 대화별 runtime/venv**를 유지하면서 이 소스의 경계를 우리 언어와 요구사항으로 옮기는 제안이다. 현재 agent-ref 저장소 자체를 검사한 결과도 아니다.

### 22.1 먼저 가져올 최소 경계

| 우리 개념 | Claude Code에서 참고할 곳 | 최소 책임 |
|---|---|---|
| AgentDefinition | loadAgentsDir | 역할·프롬프트·모델·허용 Tool |
| AgentRun | runAgent + child context + runtime task | run ID, parent ID, 상태, transcript, 취소 |
| QueryLoop | query | 모델 → Tool → 결과 반영 → 재추론 |
| ToolSpec / ToolHandler | Tool + buildTool | 호출 schema와 구현 함수 |
| ToolRegistry | tools / assembleToolPool | 이번 실행에서 보이는 Tool 집합 |
| ToolExecutor | toolExecution | validation·permission·실행·오류 결과 |
| create_subagent | AgentTool | 정의 선택 또는 전달받은 일회성 정의로 실행 시작 |
| RunTaskStore | LocalAgentTask / framework | 상태·진행·취소·알림 |
| SessionRuntime | 직접 대응되는 단일 객체 없음 | workspace·venv·실행 프로세스 수명 |
| PluginManager | pluginLoader / zipCache | ZIP 설치·manifest·구성요소 등록 |
| SecurityPolicy | permissions + sandbox adapter | runtime 환경과 별도의 보안 정책 |

`create_subagent`가 임의의 일회성 역할 정의까지 입력받게 할지는 별도 선택이다. Claude Code의 일반 AgentTool과 동일하게 시작하려면 **기존 정의 선택 + 작업 프롬프트 전달**로 구현하고, 정의 등록·영구 저장은 후속 기능으로 분리하는 편이 명확하다.

### 22.2 사용자의 `src/agent/tool` 방향을 유지한 작은 구조

```text
src/agent/
├── definition.py           # 역할 설정
├── context.py              # 실행 문맥
├── run.py                  # 실행 1회의 상태/수명
├── loop.py                 # 공통 추론 루프
└── tool/
    ├── spec.py             # 이름·schema·정책 metadata
    ├── registry.py         # 도구 조회 / 실행별 노출
    ├── executor.py         # 검증·권한·호출·결과
    └── builtin/
        └── create_subagent.py
```

여기에 처음부터 coordinator mode, teams, MCP 전체, streaming scheduler, prompt cache 복제, 자동 compaction을 모두 이식할 필요는 없다. 먼저 **일반 Tool 1회 → 연속 Tool → Subagent Tool → 자식도 같은 Loop → 부모가 결과 종합**이 실제로 동작하도록 만드는 것이 핵심이다.

### 22.3 대화별 venv 구상은 유지할 수 있다

```text
data/
├── plugins/
│   └── <plugin-id>/<version>/    # ZIP에서 설치된 Tool 코드와 자원
└── sessions/
    └── <session-id>/
        ├── workspace/
        ├── runtime/
        │   └── .venv/           # 이 대화에서 쓰는 Python dependency 환경
        ├── transcripts/
        └── outputs/
```

가능한 실행 경로는 다음과 같다.

```text
LLM tool call
  → ToolExecutor
  → Plugin Tool adapter
  → SessionRuntime의 python interpreter
  → data/plugins/...의 실제 handler 코드
  → 구조화 결과를 Core로 반환
```

예를 들어 Core가 session venv의 Python으로 `data/plugins/.../runner.py`를 subprocess 실행하고 stdin/stdout JSON 프로토콜로 인자와 결과를 주고받도록 만들 수 있다. 이 경우 Core 프로세스의 Python 패키지와 Plugin 실행 패키지를 분리할 수 있다. **구체적인 runner/protocol은 우리 구현에서 작성해야 하며, Claude Code가 이 Python 방식을 제공한다는 뜻은 아니다.**

대화 안의 Plugin끼리는 하나의 venv를 공유하므로 버전 충돌이 가능하다. 따라서 dependency 선언·lock, 설치 잠금, 설치 실패 상태, 신뢰되지 않은 설치 스크립트 처리, 장기 실행 서버의 재시작, 세션 종료 cleanup을 따로 정의해야 한다. plugin-version별 환경 cache는 향후 최적화 선택지일 뿐, 지금 대화별 환경 방향을 자동으로 대체하는 결정은 아니다.

### 22.4 초기 버전에서 먼저 명시할 불변식

**하나의 공통 loop**, **하나의 Tool 실행 진입점**, **실행 ID별 transcript**, **정의와 실행 상태 분리**, **Tool call/result ID 대응**, **부모·자식 취소 정책**, **dependency 환경과 보안 정책 분리**를 먼저 고정한다.

추가로 “LLM이 완료했다고 말했다”를 성공 판정으로 쓰지 않고, 실행 종료 이유와 업무 완료 검증을 결과에 나누어 담는다. Claude Code의 `completed`·finalize 경로를 그대로 업무 성공 판정으로 복사하지 않는 것이 중요하다.

### 22.5 후속 구현 문서로 넘길 결정 사항

이 분석 뒤에 작성할 우리 구현 명세에서는 `AgentDefinition`, `AgentRun`, `ToolCall`, `ToolResult`, `SessionRuntime`의 필드와 상태 전이를 확정하고, ZIP manifest·dependency 선언·runner protocol·권한 계약을 정의하면 된다. **아직 선택하지 않은 설계를 Claude Code의 사실로 채워 넣지 않는 것**이 이 문서와 구현 명세를 나누는 이유다.

---

## 23. 실제 코드를 읽는 추천 경로

### 경로 A — 가장 작은 Tool Loop

```text
query/deps.ts
 → query.ts: QueryParams / State / query / queryLoop
 → Tool.ts: Tool / ToolResult
 → tools.ts: assembleToolPool
 → services/tools/toolOrchestration.ts
 → services/tools/toolExecution.ts
```

먼저 recovery·telemetry·UI를 모두 따라가려 하지 말고 모델 호출, tool_use 수집, 실제 call, tool_result 추가, 다음 반복의 연결만 표시해 본다. 관련 근거: [C03](#source-c03)–[C06](#source-c06), [C15](#source-c15)–[C20](#source-c20).

### 경로 B — Subagent 하나 실행

```text
loadAgentsDir.ts: AgentDefinition
 → AgentTool.tsx: call / 정의 선택
 → agentToolUtils.ts: resolveAgentTools
 → runAgent.ts: context 구성
 → forkedAgent.ts: createSubagentContext
 → runAgent.ts: query 호출
 → agentToolUtils.ts: finalizeAgentTool
```

“자식 loop는 어디서 다시 호출되는가?”와 “무엇을 부모와 공유하는가?” 두 질문으로 읽으면 핵심이 보인다. 관련 근거: [C07](#source-c07)–[C14](#source-c14), [C43](#source-c43).

### 경로 C — Background와 재개

```text
AgentTool.tsx: registerAsyncAgent 연결
 → LocalAgentTask.tsx
 → agentToolUtils.ts: runAsyncAgentLifecycle
 → task/framework.ts
 → sessionStorage.ts
 → SendMessageTool.ts
 → resumeAgent.ts
```

상태 전이, 알림 시점, transcript 저장, 재개 시 재구성되는 것과 유지되는 것을 각각 적는다. 관련 근거: [C22](#source-c22)–[C29](#source-c29).

### 경로 D — ZIP Plugin에서 실제 실행까지

```text
plugins/schemas.ts
 → plugins/pluginLoader.ts
 → plugins/zipCache.ts
 → plugins/dependencyResolver.ts
 → plugins/mcpPluginIntegration.ts
 → services/mcp/client.ts

별도 실행 경로:
  plugins/loadPluginAgents.ts
  SkillTool.ts
  utils/hooks.ts
  Shell.ts → sandbox/sandbox-adapter.ts
```

Plugin 전체를 MCP 하나로 축약하지 말고, **구성요소별로 어디에 등록되고 어느 backend에서 실행되는지**를 연결한다. 관련 근거: [C30](#source-c30)–[C40](#source-c40).

---

## 24. 최종 요약

이 소스에서 우리에게 가장 유용한 것은 코드의 양이 아니라 **실행 책임을 나누는 방식**이다.

```text
AgentDefinition     = 역할과 실행 설정
Agent 실행          = context + task + transcript + 수명
QueryLoop           = 모든 Agent가 공유하는 추론·도구 반복
Tool 계약           = schema + metadata + handler
ToolExecutor        = 검증·권한·hook·실행·결과 정리
Plugin              = 확장 기능을 배포하는 패키지
실행 backend        = 직접 코드 / shell / MCP / 기타
Security Sandbox    = 해당 backend에 적용되는 별도 자원 제한
```

동시에 그대로 복사해서는 안 되는 부분도 분명하다. 기능 플래그가 많은 제품별 분기, UI와 결합된 거대한 context, 여러 경로에 분산된 수명 관리, 재개 시 fallback, 실행 완료와 업무 성공의 혼재는 **참고하면서 단순화하거나 우리 계약으로 명시할 대상**이다.

결론적으로 첫 구현의 중심은 **“Main과 Subagent가 같은 loop를 쓰고, Subagent 실행 시작 자체가 Tool이며, 모든 Tool 호출이 중앙 실행기를 통과한다”**는 세 가지다. 여기에 사용자가 구상한 ZIP Plugin과 대화별 runtime을 붙이되, dependency 환경과 OS 보안 격리는 별도 경계로 설계한다.

---

## 부록 A. 소스 근거 색인

아래 줄 번호는 업로드 ZIP의 파일을 그대로 압축 해제한 뒤 **1부터 세는 줄 번호**다. 다른 저장소나 최신 배포본에서는 위치가 달라질 수 있다. 원문에서 찾을 때는 파일 경로·함수명·파일 SHA-256을 함께 사용한다. 근거 범위는 해당 문단을 재검토할 출발점이며, 범위 안의 모든 분기를 완전 감사했다는 뜻은 아니다.

<a id="source-c01"></a>
### C01 · 업로드 스냅샷의 자체 설명

- `README.md:L1–L280`

<a id="source-c02"></a>
### C02 · REPL 진입점과 headless 세션 wrapper

- `src/screens/REPL.tsx:L2780–L2812`
- `src/cli/print.ts:L85–L95`
- `src/QueryEngine.ts:L130–L207`
- `src/QueryEngine.ts:L660–L708`
- `src/QueryEngine.ts:L1186–L1295`

<a id="source-c03"></a>
### C03 · query 입력·상태·공통 생성기

- `src/query.ts:L181–L335`

<a id="source-c04"></a>
### C04 · 모델 streaming·Tool 요청 수집·중단 정리

- `src/query.ts:L100–L147`
- `src/query.ts:L551–L568`
- `src/query.ts:L659–L708`
- `src/query.ts:L826–L860`
- `src/query.ts:L1000–L1052`

<a id="source-c05"></a>
### C05 · 문맥 압축·복구·stop hook·종료

- `src/query.ts:L370–L530`
- `src/query.ts:L1080–L1357`
- `src/query.ts:L1500–L1525`

<a id="source-c06"></a>
### C06 · 좁은 모델·압축 dependency injection

- `src/query/deps.ts:L1–L40`

<a id="source-c07"></a>
### C07 · AgentDefinition 스키마와 타입

- `src/tools/AgentTool/loadAgentsDir.ts:L74–L165`

<a id="source-c08"></a>
### C08 · Agent 정의 우선순위와 built-in 조건

- `src/tools/AgentTool/loadAgentsDir.ts:L186–L243`
- `src/tools/AgentTool/loadAgentsDir.ts:L296–L390`
- `src/tools/AgentTool/builtInAgents.ts:L1–L72`

<a id="source-c09"></a>
### C09 · AgentTool 스키마·정의 선택·재귀/팀 제약

- `src/tools/AgentTool/AgentTool.tsx:L80–L155`
- `src/tools/AgentTool/AgentTool.tsx:L240–L355`

<a id="source-c10"></a>
### C10 · AgentTool 실행 준비·worktree·background 전환

- `src/tools/AgentTool/AgentTool.tsx:L475–L775`
- `src/tools/AgentTool/AgentTool.tsx:L808–L846`
- `src/tools/AgentTool/AgentTool.tsx:L883–L1048`
- `src/tools/AgentTool/AgentTool.tsx:L1268–L1296`
- `src/tools/AgentTool/AgentTool.tsx:L1323–L1336`

<a id="source-c11"></a>
### C11 · runAgent 입력·메시지·권한·취소

- `src/tools/AgentTool/runAgent.ts:L248–L550`

<a id="source-c12"></a>
### C12 · runAgent의 skill/MCP·공통 query·저장·cleanup

- `src/tools/AgentTool/runAgent.ts:L550–L714`
- `src/tools/AgentTool/runAgent.ts:L732–L859`

<a id="source-c13"></a>
### C13 · 자식 context의 공유/복제와 async-local cwd

- `src/utils/forkedAgent.ts:L345–L465`
- `src/utils/cwd.ts:L1–L32`
- `src/utils/agentContext.ts:L85–L122`

<a id="source-c14"></a>
### C14 · 자식 도구 필터·재귀 제한·모델 선택

- `src/tools/AgentTool/agentToolUtils.ts:L62–L225`
- `src/constants/tools.ts:L36–L70`
- `src/utils/model/agent.ts:L21–L95`

<a id="source-c15"></a>
### C15 · Tool·ToolUseContext·ToolResult·기본값

- `src/Tool.ts:L158–L302`
- `src/Tool.ts:L321–L336`
- `src/Tool.ts:L362–L700`
- `src/Tool.ts:L743–L792`

<a id="source-c16"></a>
### C16 · 도구 pool 구성·정렬·모드 필터

- `src/tools.ts:L193–L389`
- `src/utils/toolPool.ts:L35–L79`

<a id="source-c17"></a>
### C17 · Tool lookup·validation·관찰용 입력·pre hook

- `src/services/tools/toolExecution.ts:L337–L431`
- `src/services/tools/toolExecution.ts:L599–L731`
- `src/services/tools/toolExecution.ts:L769–L856`
- `src/services/tools/toolExecution.ts:L916–L931`

<a id="source-c18"></a>
### C18 · hook 결정과 일반 deny/ask 규칙의 결합

- `src/services/tools/toolHooks.ts:L332–L433`

<a id="source-c19"></a>
### C19 · 실제 Tool call·결과 변환·post/failure hook

- `src/services/tools/toolExecution.ts:L1026–L1045`
- `src/services/tools/toolExecution.ts:L1125–L1143`
- `src/services/tools/toolExecution.ts:L1198–L1235`
- `src/services/tools/toolExecution.ts:L1280–L1302`
- `src/services/tools/toolExecution.ts:L1397–L1545`
- `src/services/tools/toolExecution.ts:L1696–L1728`

<a id="source-c20"></a>
### C20 · 비-streaming batch 병렬화와 context 변경

- `src/services/tools/toolOrchestration.ts:L1–L188`

<a id="source-c21"></a>
### C21 · StreamingToolExecutor 상태·스케줄링·결과

- `src/services/tools/StreamingToolExecutor.ts:L19–L156`
- `src/services/tools/StreamingToolExecutor.ts:L273–L440`
- `src/services/tools/StreamingToolExecutor.ts:L453–L487`

<a id="source-c22"></a>
### C22 · 실행 Task 공통 타입과 상태

- `src/Task.ts:L1–L76`
- `src/Task.ts:L108–L125`

<a id="source-c23"></a>
### C23 · 업무 목록용 Task 스키마

- `src/utils/tasks.ts:L69–L89`

<a id="source-c24"></a>
### C24 · LocalAgentTask 등록·중단·대기 메시지·알림

- `src/tasks/LocalAgentTask/LocalAgentTask.tsx:L116–L181`
- `src/tasks/LocalAgentTask/LocalAgentTask.tsx:L197–L307`
- `src/tasks/LocalAgentTask/LocalAgentTask.tsx:L412–L600`
- `src/tasks/LocalAgentTask/LocalAgentTask.tsx:L620–L657`

<a id="source-c25"></a>
### C25 · 비동기 Agent 공통 수명·완료 순서·부분 결과

- `src/tools/AgentTool/agentToolUtils.ts:L508–L686`

<a id="source-c26"></a>
### C26 · 실행 task 공통 상태 관리·eviction·알림 연결

- `src/utils/task/framework.ts:L48–L145`
- `src/utils/task/framework.ts:L156–L203`
- `src/utils/task/framework.ts:L245–L287`

<a id="source-c27"></a>
### C27 · Sidechain 경로·metadata·메시지 저장

- `src/utils/sessionStorage.ts:L247–L303`
- `src/utils/sessionStorage.ts:L1451–L1462`
- `src/utils/sessionStorage.ts:L4194–L4255`

<a id="source-c28"></a>
### C28 · 종료된 Agent의 transcript 기반 재개

- `src/tools/AgentTool/resumeAgent.ts:L42–L110`
- `src/tools/AgentTool/resumeAgent.ts:L158–L265`

<a id="source-c29"></a>
### C29 · SendMessage의 실행 중 전달/종료 후 재개

- `src/tools/SendMessageTool/SendMessageTool.ts:L800–L879`

<a id="source-c30"></a>
### C30 · Plugin manifest 구성요소 스키마

- `src/utils/plugins/schemas.ts:L429–L499`
- `src/utils/plugins/schemas.ts:L543–L571`
- `src/utils/plugins/schemas.ts:L857–L897`

<a id="source-c31"></a>
### C31 · Plugin 출처·캐시·manifest fallback·전체 로딩

- `src/utils/plugins/pluginLoader.ts:L126–L187`
- `src/utils/plugins/pluginLoader.ts:L365–L524`
- `src/utils/plugins/pluginLoader.ts:L534–L553`
- `src/utils/plugins/pluginLoader.ts:L645–L731`
- `src/utils/plugins/pluginLoader.ts:L856–L955`
- `src/utils/plugins/pluginLoader.ts:L1147–L1212`
- `src/utils/plugins/pluginLoader.ts:L1348–L1510`
- `src/utils/plugins/pluginLoader.ts:L3009–L3066`
- `src/utils/plugins/pluginLoader.ts:L3096–L3111`
- `src/utils/plugins/pluginLoader.ts:L3155–L3211`

<a id="source-c32"></a>
### C32 · ZIP cache·세션 추출 디렉터리·cleanup 등록

- `src/utils/plugins/zipCache.ts:L1–L67`
- `src/utils/plugins/zipCache.ts:L116–L161`
- `src/utils/plugins/zipCache.ts:L175–L242`
- `src/utils/plugins/zipCache.ts:L331–L359`
- `src/utils/plugins/headlessPluginInstall.ts:L145–L169`

<a id="source-c33"></a>
### C33 · Plugin 간 dependency closure·검증·비활성화

- `src/utils/plugins/dependencyResolver.ts:L1–L68`
- `src/utils/plugins/dependencyResolver.ts:L85–L174`
- `src/utils/plugins/dependencyResolver.ts:L177–L242`

<a id="source-c34"></a>
### C34 · Plugin agent namespace와 frontmatter 제한

- `src/utils/plugins/loadPluginAgents.ts:L78–L120`
- `src/utils/plugins/loadPluginAgents.ts:L145–L215`
- `src/utils/plugins/loadPluginAgents.ts:L231–L270`

<a id="source-c35"></a>
### C35 · Plugin MCP 설정 병합·namespace·환경 변수

- `src/utils/plugins/mcpPluginIntegration.ts:L131–L211`
- `src/utils/plugins/mcpPluginIntegration.ts:L341–L359`
- `src/utils/plugins/mcpPluginIntegration.ts:L465–L550`

<a id="source-c36"></a>
### C36 · MCP transport·Tool adapter·annotation·실제 호출

- `src/services/mcp/client.ts:L673–L718`
- `src/services/mcp/client.ts:L861–L911`
- `src/services/mcp/client.ts:L936–L960`
- `src/services/mcp/client.ts:L1743–L1835`
- `src/services/mcp/client.ts:L3070–L3121`

<a id="source-c37"></a>
### C37 · command hook의 신뢰·변수 치환·프로세스 실행

- `src/utils/hooks.ts:L270–L283`
- `src/utils/hooks.ts:L740–L770`
- `src/utils/hooks.ts:L818–L855`
- `src/utils/hooks.ts:L967–L986`

<a id="source-c38"></a>
### C38 · SkillTool의 fork·메시지·contextModifier

- `src/tools/SkillTool/SkillTool.ts:L122–L210`
- `src/tools/SkillTool/SkillTool.ts:L610–L652`
- `src/tools/SkillTool/SkillTool.ts:L733–L823`

<a id="source-c39"></a>
### C39 · BashTool에서 Shell·sandbox wrapper·spawn까지

- `src/tools/BashTool/BashTool.tsx:L235–L254`
- `src/tools/BashTool/BashTool.tsx:L875–L905`
- `src/utils/Shell.ts:L181–L226`
- `src/utils/Shell.ts:L256–L273`
- `src/utils/Shell.ts:L315–L337`

<a id="source-c40"></a>
### C40 · OS sandbox adapter와 외부 runtime 경계

- `src/utils/sandbox/sandbox-adapter.ts:L1–L25`
- `src/utils/sandbox/sandbox-adapter.ts:L172–L214`
- `src/utils/sandbox/sandbox-adapter.ts:L451–L466`
- `src/utils/sandbox/sandbox-adapter.ts:L532–L578`
- `src/utils/sandbox/sandbox-adapter.ts:L704–L742`
- `src/utils/sandbox/sandbox-adapter.ts:L927–L980`

<a id="source-c41"></a>
### C41 · 조건부 coordinator 모드·정책·도구 필터

- `src/coordinator/coordinatorMode.ts:L29–L41`
- `src/coordinator/coordinatorMode.ts:L111–L369`
- `src/utils/toolPool.ts:L35–L79`
- `src/tools/AgentTool/builtInAgents.ts:L32–L42`

<a id="source-c42"></a>
### C42 · query의 도구 결과 반영과 다음 상태 구성

- `src/query.ts:L1380–L1407`
- `src/query.ts:L1660–L1729`

<a id="source-c43"></a>
### C43 · Agent 결과 최종화와 마지막 텍스트 선택

- `src/tools/AgentTool/agentToolUtils.ts:L276–L359`


## 부록 B. 공식 문서 교차 확인

공식 문서는 **개념과 공개 인터페이스의 보조 확인**에만 사용했다. 업로드 소스의 진위나 특정 릴리스와의 동일성을 인증하는 근거로 쓰지 않았다. 특히 2026-09-09에 조회한 문서에는 스냅샷보다 후대의 버전별 변경 설명이 있으므로, 기본 모델·재귀 정책·Plugin dependency 처리 등을 역으로 소스에 덮어쓰지 않았다.

<a id="web-w01"></a>
**W01 · Claude Code — Subagents**  
https://code.claude.com/docs/en/sub-agents  
조회일: 2026-09-09. 별도 문맥과 도구·권한 구성이라는 공개 개념을 확인했다. 버전별 변경이 포함돼 있어 이 스냅샷의 조건·기본값은 코드 근거를 우선했다.

<a id="web-w02"></a>
**W02 · Claude Code — Plugins reference**  
https://code.claude.com/docs/en/plugins-reference  
조회일: 2026-09-09. Plugin 구성요소와 설치 경로·데이터 경로의 구분을 교차 확인했다. 현재 문서의 자동 dependency 설치 설명을 이 스냅샷의 구현으로 간주하지 않았다.

<a id="web-w03"></a>
**W03 · Claude Code — Sandboxing**  
https://code.claude.com/docs/en/sandboxing  
조회일: 2026-09-09. 권한 시스템과 shell sandbox 범위를 구분하는 설명을 확인했다. 이 문서의 실제 적용 경로 분석은 `Shell.ts`와 adapter 원문에 근거한다.

<a id="web-w04"></a>
**W04 · Python — venv**  
https://docs.python.org/3/library/venv.html  
조회일: 2026-09-09. Python 가상환경이 interpreter·package 환경을 구성하는 기능임을 확인했다. 이것을 파일·네트워크 보안 제한과 구별해 설명했다.

## 부록 C. 재검증 자료

함께 제공하는 `claude-code-reference-evidence.json`에는 ZIP 해시, 파일 통계, 파일별 줄 수·SHA-256, 본문 C01–C43 근거 범위, 선택된 짧은 코드 발췌가 들어 있다. `verify_reference.py`는 원본 ZIP 또는 압축 해제된 루트를 받아 이 목록과 일치하는지 점검한다.

```bash
python verify_reference.py /path/to/claude-code-main.zip
# 또는
python verify_reference.py /path/to/claude-code-main/
```

검증 스크립트는 소스 코드를 실행하지 않고 파일을 읽어 해시·목록·근거 범위만 점검한다. 이 검증이 통과해도 소스의 공식성, 런타임 동작, 제품 라이선스, OS sandbox 안전성까지 인증되는 것은 아니다.
