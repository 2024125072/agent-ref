import json

def create_state():
    return {
        "turns": [],
        "summary": "",
        "candidates": [],
        "step": 0,
    }

  
def build_context(
    state,
    current_turn,
    recent_turns=None,
    use_summary=False
):

    # 이 엔드포인트는 맨 앞의 system 메시지 하나만 허용하므로
    # 여러 system 조각을 하나로 합친다.
    system_parts = [
        "너는 노트북 추천 Agent이다. "
        "검색 요청을 받으면 search_laptops tool을 사용한다. "
        "사용자가 말하지 않은 조건은 임의로 설정하지 않는다."
    ]

    if use_summary and state["summary"]:
        system_parts.append(
            "이전 대화의 Memory Summary:\n"
            + state["summary"]
        )

    if state["candidates"]:
        text = json.dumps(
            state["candidates"],
            ensure_ascii=False,
            indent=2
        )

        system_parts.append(
            f"현재 Agent State에 저장된 후보 노트북은 다음과 같다:\n{text}"
        )

    context = [
        {
            "role": "system",
            "content": "\n\n".join(system_parts)
        }
    ]

    if recent_turns is None:
        turns = state["turns"]
    else:
        turns = state["turns"][-recent_turns:]

    for turn in turns:
        context.extend(turn)

    context.extend(current_turn)

    return context


def build_summary_context(state, recent_turns=1):

    pass