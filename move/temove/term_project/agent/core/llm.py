from openai import OpenAI
import dotenv
import os

dotenv.load_dotenv()

# 기본 클라이언트
def create_client():
    return OpenAI(
        base_url=os.getenv(
            "OPENAI_BASE_URL",
            "https://agent.kau.ac.kr/v1"
        ),
        api_key=os.getenv("KAU_API_KEY", ""),
        timeout=120.0,
    )