from openai import OpenAI

import dotenv
import os

dotenv.load_dotenv()

client = OpenAI(
    base_url=os.getenv("OPENAI_BASE_URL", "https://agent.kau.ac.kr/v1"),
    api_key=os.getenv("KAU_API_KEY", ""),
    timeout=120.0,
)


model = os.getenv("MODEL_NAME") or client.models.list().data[0].id

print(model)

question = (
    "2026년 해외 출장의 숙박비와 식비 한도, 그리고 출발 전 승인 요건을 "
    "근거 문서와 함께 정리해줘."
)

context = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": question},
]

response = client.chat.completions.create(
    model=model,
    messages=context,
    temperature=0,
)

print(response.choices[0].message.content)