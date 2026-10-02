import os
import json

from dotenv import load_dotenv
from openai import OpenAI

from build_context import build_context, build_summary_context
from python_tools import TOOLS, execute_tool


# 한 사용자 입력을 처리하는 동안 허용되는 agent loop의 최대 반복 횟수.
# week_02의 MAX_ITERATIONS, week_06의 MAX_AGENT_LOOP_ITERATIONS와 같은 역할이다.
MAX_ITERATIONS = 8


def assistant_message_to_dict(message):
    """SDK 응답 객체를 표준 assistant 메시지 dict로 변환한다.

    model_dump()는 엔드포인트에 따라 비표준 필드(reasoning_content 등)까지
    담아 다음 요청 컨텍스트로 되돌려 보내므로, 표준 필드만 명시적으로 담는다.
    """
    result = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
            for tool_call in message.tool_calls
        ]
    return result


def ask_agent(
    client,
    model,
    state,
    user_text,
    recent_turns=None,
    use_summary=False,
    debug=False,
    max_iterations=MAX_ITERATIONS,
):

    current_turn = [
        {
            "role": "user",
            "content": user_text
        }
    ]

    # 상한에 걸리면 이 초기값이 그대로 결과가 된다
    status = "failed"
    answer = f"에이전트가 {max_iterations}회 반복 안에 답을 내지 못했다."

    # agent loop: LLM이 tool call을 멈출 때까지 반복하되 상한을 둔다
    for iteration in range(1, max_iterations + 1):

        state["step"] += 1

        context = build_context(
            state,
            current_turn,
            recent_turns,
            use_summary
        )

        if debug:
            print("\n===== LLM CONTEXT =====")
            for msg in context:
                print(
                    msg["role"],
                    ":",
                    msg.get("content", "")
                )

        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=context,
            tools=TOOLS,
        )

        message = response.choices[0].message
        current_turn.append(assistant_message_to_dict(message))

        # Tool Call이 없으면 이번 turn의 최종 답변
        if not message.tool_calls:
            status = "completed"
            answer = message.content
            break

        # Tool Call 실행
        for tool_call in message.tool_calls:

            name = tool_call.function.name

            try:
                args = json.loads(tool_call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("Tool arguments must be a JSON object")
                result = execute_tool(name, args)
            except Exception as error:
                # 오류는 크래시가 아니라 모델이 보고 복구할 관찰값이다
                result = {"status": "error", "message": str(error)}

            # 검색 결과를 State에 저장해 두면
            # 이후 turn이 잘려나가도 후보 목록이 유지된다.
            if name == "search_laptops" and isinstance(result, list):
                state["candidates"] = result

            current_turn.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False)
            })

    # 완료 여부와 관계없이 이번 turn을 State에 기록한다
    state["turns"].append(
        current_turn
    )

    if (
        use_summary
        and recent_turns is not None
        and len(state["turns"]) > recent_turns
    ):
        # 여기서 summary_context를 만들고 LLM에게 요약을 요청한다.
        # summary_context는 agent state의 turns를 정보를 사용하여 요약을 생성하도록 구성된다.
        # recent_turns가 None이면 요약을 만들지 않는다.
        # recent_turns 만큼 truns에서 제외하고 summary_context를 만들고 LLM에게 요약을 요청한다.
        summary_context = build_summary_context(state, recent_turns)
        response = client.chat.completions.create(
            model=model,
            temperature=0.0,
            messages=summary_context
        )

        state["summary"] = (
            response.choices[0].message.content
        )

    return {
        "status": status,
        "content": answer,
        "iterations": iteration,
    }


def create_client():
    load_dotenv()
    return OpenAI(
        base_url=os.getenv("OPENAI_BASE_URL", "https://agent.kau.ac.kr/v1"),
        api_key=os.getenv("KAU_API_KEY", os.getenv("OPENAI_API_KEY", "EMPTY")),
        timeout=120.0,
    )


if __name__ == "__main__":
    client = create_client()
    model = os.getenv("MODEL_NAME") or client.models.list().data[0].id

    print(f"Using model: {model}")
