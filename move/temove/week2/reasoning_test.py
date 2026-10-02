import os
import json

from dotenv import load_dotenv
from openai import OpenAI


def create_client():
    load_dotenv()

    return OpenAI(
        base_url=os.getenv(
            "OPENAI_BASE_URL",
            "https://agent.kau.ac.kr/v1",
        ),
        api_key=os.getenv(
            "KAU_API_KEY",
            os.getenv("OPENAI_API_KEY", "EMPTY"),
        ),
        timeout=120.0,
    )


# ---------------------------------------------------------
# 테스트용 Tool 정의
# 실제로 실행하지 않고, 모델이 tool call을 생성하는지만 확인
# ---------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_price",
            "description": "상품의 현재 가격을 조회한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "product": {
                        "type": "string",
                        "description": "가격을 조회할 상품 이름",
                    }
                },
                "required": ["product"],
            },
        },
    }
]


def print_response(response):
    """
    OpenAI ChatCompletion 응답에서
    content / reasoning / tool_calls를 각각 출력한다.
    """

    message = response.choices[0].message

    print("\n" + "=" * 70)
    print("MODEL")
    print("=" * 70)
    print(response.model)

    print("\n" + "=" * 70)
    print("FINISH REASON")
    print("=" * 70)
    print(response.choices[0].finish_reason)

    print("\n" + "=" * 70)
    print("REASONING")
    print("=" * 70)

    reasoning = getattr(message, "reasoning", None)

    if reasoning:
        print(reasoning)
    else:
        print("[None]")

    print("\n" + "=" * 70)
    print("CONTENT")
    print("=" * 70)

    if message.content:
        print(message.content)
    else:
        print("[None]")

    print("\n" + "=" * 70)
    print("TOOL CALLS")
    print("=" * 70)

    if message.tool_calls:
        for i, tool_call in enumerate(message.tool_calls, start=1):
            print(f"\nTool #{i}")
            print("id       :", tool_call.id)
            print("name     :", tool_call.function.name)
            print("arguments:", tool_call.function.arguments)
    else:
        print("[None]")

    print("\n" + "=" * 70)
    print("RAW MESSAGE")
    print("=" * 70)

    # SDK가 실제로 어떤 필드를 받았는지 확인
    print(
        json.dumps(
            message.model_dump(),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )


def test_reasoning_only(client, model):
    """
    Tool 없이 순수 reasoning이 반환되는지 확인.
    """

    print("\n\n")
    print("#" * 70)
    print("# TEST 1 - REASONING ONLY")
    print("#" * 70)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    "다음 문제를 풀어줘.\n\n"
                    "1234567 × 891011의 값을 계산해.\n"
                    "충분히 생각해서 정확한 답을 구해."
                ),
            }
        ],
        max_tokens=2048,

        # Qwen thinking mode 활성화 요청
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": True,
            }
        },
    )

    print_response(response)

def test_reasoning_only_stream(client, model):
    print("\n\n")
    print("#" * 70)
    print("# TEST 1 - REASONING ONLY / STREAM")
    print("#" * 70)

    stream = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": "12345 × 6789를 계산해."
            }
        ],
        max_tokens=512,
        stream=True,
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": True,
            }
        },
    )

    reasoning_started = False
    content_started = False

    for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        reasoning = getattr(delta, "reasoning", None)
        content = getattr(delta, "content", None)

        if reasoning:
            if not reasoning_started:
                print("\n[REASONING]")
                reasoning_started = True

            print(reasoning, end="", flush=True)

        if content:
            if not content_started:
                print("\n\n[CONTENT]")
                content_started = True

            print(content, end="", flush=True)

    print("\n\n[DONE]")


def test_reasoning_with_tools(client, model):
    """
    Tool calling 상황에서도 reasoning이 반환되는지 확인.
    """

    print("\n\n")
    print("#" * 70)
    print("# TEST 2 - REASONING + TOOL CALLING")
    print("#" * 70)

    question = """
노트북 A 1대와 모니터 B 2대를 구입하려고 한다.

각 상품의 가격은 get_price 도구로 조회해야 한다.

전체 상품 가격을 더한 다음
전체 금액에서 10% 할인받으면
최종 결제 금액이 얼마인지 계산해줘.
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "필요한 경우 제공된 도구를 사용해 문제를 해결한다. "
                    "상품 가격을 임의로 추측하지 않는다."
                ),
            },
            {
                "role": "user",
                "content": question,
            },
        ],
        tools=TOOLS,
        max_tokens=2048,

        # Qwen thinking mode 활성화 요청
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": True,
            }
        },
    )

    print_response(response)


def test_reasoning_disabled(client, model):
    """
    비교용.
    enable_thinking=False일 때 어떻게 달라지는지 확인.
    """

    print("\n\n")
    print("#" * 70)
    print("# TEST 3 - THINKING DISABLED")
    print("#" * 70)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": (
                    "1234567 × 891011의 값을 계산해."
                ),
            }
        ],
        max_tokens=2048,
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": False,
            }
        },
    )

    print_response(response)


def main():
    client = create_client()

    # MODEL_NAME이 있으면 사용
    # 없으면 서버의 첫 번째 모델 사용
    model = os.getenv("MODEL_NAME")

    if not model:
        models = client.models.list()

        if not models.data:
            raise RuntimeError("서버에서 사용 가능한 모델을 찾지 못했습니다.")

        model = models.data[0].id

    print("=" * 70)
    print("TEST START")
    print("=" * 70)
    print("Base URL :", client.base_url)
    print("Model    :", model)

    # 1. Thinking 자체 테스트
    #test_reasoning_only(client, model)
    test_reasoning_only_stream(client, model)

    # 2. Thinking + Tool calling 테스트
    #test_reasoning_with_tools(client, model)

    # 3. Thinking OFF 비교 테스트
    #test_reasoning_disabled(client, model)


if __name__ == "__main__":
    main()