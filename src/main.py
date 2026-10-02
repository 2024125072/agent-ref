from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agent import ProblemSolver
from llm.provider.openai import OpenAILLM


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(frozen=True)
class AgentApp:
    """OpenAI-compatible Provider와 ProblemSolver를 묶은 애플리케이션 런타임."""

    provider: OpenAILLM
    solver: ProblemSolver
    model: str


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise RuntimeError(
            "python-dotenv가 필요합니다. "
            "가상환경에서 `pip install python-dotenv`를 실행하세요."
        ) from exc

    load_dotenv(ENV_PATH)


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(
            f"{name}가 설정되어 있지 않습니다. "
            f"{ENV_PATH} 파일을 확인하세요."
        )
    return value.strip()


def create_app(*, model: str | None = None) -> AgentApp:
    """
    .env에서 OpenAI-compatible 연결 정보를 읽고 실제 ProblemSolver를 생성한다.

    필수 환경변수:
      OPENAI_BASE_URL
      KAU_API_KEY

    선택 환경변수:
      OPENAI_MODEL
        - 지정되어 있으면 해당 모델 사용
        - 없으면 Provider가 반환한 첫 번째 모델 사용
    """

    _load_env()

    base_url = _require_env("OPENAI_BASE_URL")
    api_key = _require_env("KAU_API_KEY")

    provider = OpenAILLM(
        base_url=base_url,
        api_key=api_key,
    )

    available_models = provider.get_available_models()
    if not available_models:
        raise RuntimeError(
            f"사용 가능한 모델이 없습니다: {base_url}"
        )

    requested_model = model or os.getenv("OPENAI_MODEL")
    if requested_model is not None:
        requested_model = requested_model.strip()

    selected_model = requested_model or available_models[0]

    if selected_model not in available_models:
        raise RuntimeError(
            f"요청한 모델 {selected_model!r}을 Provider에서 찾지 못했습니다.\n"
            f"사용 가능한 모델: {', '.join(available_models)}"
        )

    solver = ProblemSolver(provider)

    return AgentApp(
        provider=provider,
        solver=solver,
        model=selected_model,
    )


def main() -> None:
    """실제 프로그램 bootstrap 확인용 엔트리포인트."""

    app = create_app()
    print(f"[OPENAI] base_url={_require_env('OPENAI_BASE_URL')}")
    print(f"[OPENAI] model={app.model}")
    print("[READY] ProblemSolver initialized successfully.")


if __name__ == "__main__":
    main()
