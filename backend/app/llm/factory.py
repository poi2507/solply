"""LLM 모델 팩토리.

세 경로를 한 자리에서 고른다. 호출부는 provider를 알 필요가 없다.

  gemini  AI Studio 무료 티어 — 개발 기본값. 모델당 분당 요청 한도가 낮다.
  vertex  Vertex AI 경유 — GCP 프로젝트 기반. $300 크레딧이 적용되고 한도가 넉넉하다.
          GCP 결제가 풀리는 즉시 LLM_PROVIDER=vertex 로 전환한다.
  mock    LLM을 부르지 않고 규칙으로 판단 (app/llm/rules.py). 리허설·테스트용.
"""

from functools import lru_cache

from app import config


@lru_cache(maxsize=4)
def chat_model(model: str, temperature: float = 0.2):
    """LangChain BaseChatModel을 돌려준다. 같은 (모델, 온도)는 재사용한다."""
    if config.LLM_PROVIDER == "vertex":
        from langchain_google_vertexai import ChatVertexAI

        return ChatVertexAI(
            model=model,
            temperature=temperature,
            project=config.GOOGLE_CLOUD_PROJECT or None,
            location=config.GOOGLE_CLOUD_LOCATION,
        )

    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=config.GOOGLE_API_KEY,
    )


def model_for(agent: str) -> str:
    """에이전트별 모델. 무료 티어에서는 한도가 모델마다 따로 걸려 분산 효과가 있다."""
    return config.HQ_MODEL if agent == "hq" else config.STORE_MODEL


def is_mock() -> bool:
    return config.LLM_PROVIDER == "mock"
