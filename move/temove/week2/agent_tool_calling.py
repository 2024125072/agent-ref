import os
import json

from dotenv import load_dotenv
from openai import OpenAI

from python_tools import TOOLS, execute_tool


# 한 질문을 처리하는 동안 허용되는 agent loop의 최대 반복 횟수.
# week_06의 MAX_AGENT_LOOP_ITERATIONS로 이어진다.
MAX_ITERATIONS = 8

SYSTEM_PROMPT = """
당신은 상품 구매 계산을 돕는 에이전트다.
"""


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

def build_context(question):
    context = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    return context

def update_context(context, message):
    if message.role == "assistant":
        context.append(assistant_message_to_dict(message))
    else:
        context.append({"role": message.role, "content": message.content})
    return context

def run_agent(client, model, question, max_iterations=MAX_ITERATIONS):
    context = build_context(question)
    print(f"\n[question: {question}]")
    
    for i in range(max_iterations):
        print(f"\n[iteration {i + 1}]")
        # infer
        response = client.chat.completions.create(
            model=model,
            messages=context,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0
        )
        message = response.choices[0].message

        # check if finished
        if not message.tool_calls:
            print(context)
            return {
                "status": "success",
                "iterations": i + 1,
                "content": message.content,
            }

        # update context
        context = update_context(context, message)

        # run tool calls
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            result = execute_tool(tool_name, tool_args)
            context.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(result, ensure_ascii=False)})
            print(f"\n[tool call: {tool_name}({tool_args}) => {result}]")
    return {
        "status": "failed",
        "iterations": max_iterations,
        "content": "최대 반복횟수 내에 답변을 찾지 못했습니다.",
    }



def create_client():
    load_dotenv()
    return OpenAI(
        base_url=os.getenv("OPENAI_BASE_URL", "https://agent.kau.ac.kr/v1"),
        api_key=os.getenv("KAU_API_KEY", os.getenv("OPENAI_API_KEY", "EMPTY")),
        timeout=120.0,
    )


def test():
    client = create_client()
    model = os.getenv("MODEL_NAME") or client.models.list().data[0].id

    question = """
    노트북 A 1대와 모니터 B 2대를 구입하고
    전체 금액에서 10% 할인받으면
    최종 결제 금액은?
    """

    #outcome = run_agent(client, model, question)
    #print(f"\n[{outcome['status']} / {outcome['iterations']} iterations]")
    #print(outcome["content"])

    

"""
response = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},],
    tools=TOOLS,
    max_tokens=512,
)
print(f"\n[response: {response}]")

ChatCompletion(id='chatcmpl-93b6d67bdcc2426f',
 choices=[Choice(finish_reason='tool_calls',
 index=0, logprobs=None, 
 message=ChatCompletionMessage(content='학기, 먼저 노트북 A와 모니터 B의 현재 가격을 조회한 뒤, 할인 적용을 위한 계산식을 확인하겠습니다.', 
 refusal=None, role='assistant', 
 annotations=None, audio=None, 
 function_call=None, 
 tool_calls=[ChatCompletionMessageFunctionToolCall(id='chatcmpl-tool-81660a0d98869de5', function=Function(arguments='{"product": "노트북 A"}', name='get_price'), type='function'),
 ChatCompletionMessageFunctionToolCall(id='chatcmpl-tool-a735a7f8e1c8af5f', function=Function(arguments='{"product": "모니터 B"}', name='get_price'), type='function')], reasoning=None), stop_reason=None, token_ids=None, routed_experts=None)],
 created=1789377341, model='qwen3.5-9b', object='chat.completion', metadata=None,
 moderation=None, service_tier=None, system_fingerprint='vllm-0.24.0+092c4842.dev-87c572e0',
 usage=CompletionUsage(completion_tokens=81, prompt_tokens=406, total_tokens=487, completion_tokens_details=None, prompt_tokens_details=None),
 prompt_logprobs=None,
 prompt_token_ids=None,
 prompt_text=None,
 kv_transfer_params=None)
"""

def main():
    client = create_client()
    model = os.getenv("MODEL_NAME") or client.models.list().data[0].id

    question = """
    노트북 A 1대와 모니터 B 2대를 구입하고
    전체 금액에서 10% 할인받으면
    최종 결제 금액은?
    """

    outcome = run_agent(client, model, question)
    print(f"\n[{outcome['status']} / {outcome['iterations']} iterations]")
    print(outcome["content"])

    # 오류 복구 데모: '모니터B'는 카탈로그에 없으므로 not_found가 반환되고,
    # 모델이 available_products를 보고 '모니터 B'로 다시 시도한다.
    outcome = run_agent(client, model, "모니터B 3대 사면 얼마야?")
    print(f"\n[{outcome['status']} / {outcome['iterations']} iterations]")
    print(outcome["content"])

if __name__ == "__main__":
    #test()
    main()
