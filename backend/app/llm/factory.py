"""LLM 모델 팩토리.

세 경로를 한 자리에서 고른다. 호출부는 provider를 알 필요가 없다.

  gemini  AI Studio 무료 티어 — 개발 기본값. 모델당 분당 요청 한도가 낮다.
  vertex  Vertex AI 경유 — GCP 프로젝트 기반. $300 크레딧이 적용되고 한도가 넉넉하다.
          `make vertex-check`로 준비 상태를 확인한 뒤 LLM_PROVIDER=vertex 로 전환한다.
  mock    LLM을 부르지 않고 규칙으로 판단 (app/llm/rules.py). 리허설·테스트용.

Vertex 모델 이름은 AI Studio와 다를 수 있어 VERTEX_HQ_MODEL/VERTEX_STORE_MODEL로
따로 지정할 수 있게 열어뒀다.
"""

from functools import lru_cache

from app import config


class ProviderNotReady(RuntimeError):
    """설정이 덜 된 채로 provider를 쓰려 할 때 — 원인을 바로 알려준다."""


@lru_cache(maxsize=4)
def chat_model(model: str, temperature: float = 0.2):
    """LangChain BaseChatModel을 돌려준다. 같은 (모델, 온도)는 재사용한다."""
    if config.LLM_PROVIDER == "vertex":
        return _vertex(model, temperature)
    return _ai_studio(model, temperature)


def _vertex(model: str, temperature: float):
    if not config.GOOGLE_CLOUD_PROJECT:
        raise ProviderNotReady(
            "LLM_PROVIDER=vertex 인데 GOOGLE_CLOUD_PROJECT가 비어 있습니다. "
            "backend/.env에 프로젝트 ID를 넣거나 `make vertex-check`로 상태를 확인하세요."
        )
    try:
        from langchain_google_vertexai import ChatVertexAI
    except ImportError as exc:  # pragma: no cover — 설치 안내
        raise ProviderNotReady(
            "langchain-google-vertexai가 설치되지 않았습니다. `uv add langchain-google-vertexai`"
        ) from exc

    return ChatVertexAI(
        model=model,
        temperature=temperature,
        project=config.GOOGLE_CLOUD_PROJECT,
        location=config.GOOGLE_CLOUD_LOCATION,
    )


def _ai_studio(model: str, temperature: float):
    if not config.GOOGLE_API_KEY:
        raise ProviderNotReady(
            "GOOGLE_API_KEY가 비어 있습니다. https://aistudio.google.com/apikey 에서 발급해 "
            "backend/.env에 넣으세요. (LLM 없이 돌리려면 LLM_PROVIDER=mock)"
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=config.GOOGLE_API_KEY,
    )


def model_for(agent: str) -> str:
    """에이전트별 모델.

    무료 티어에서는 한도가 모델마다 따로 걸려 분산 효과가 있다.
    Vertex는 모델 이름 체계가 달라 별도 환경변수로 덮어쓸 수 있다.
    """
    if config.LLM_PROVIDER == "vertex":
        return config.VERTEX_HQ_MODEL if agent == "hq" else config.VERTEX_STORE_MODEL
    return config.HQ_MODEL if agent == "hq" else config.STORE_MODEL


def is_mock() -> bool:
    return config.LLM_PROVIDER == "mock"


def describe() -> dict:
    """현재 LLM 설정 — 헬스체크와 대시보드가 보여준다."""
    return {
        "provider": config.LLM_PROVIDER,
        "hq_model": model_for("hq") if not is_mock() else None,
        "store_model": model_for("store") if not is_mock() else None,
        "project": config.GOOGLE_CLOUD_PROJECT or None,
        "ready": is_mock()
        or (
            bool(config.GOOGLE_CLOUD_PROJECT)
            if config.LLM_PROVIDER == "vertex"
            else bool(config.GOOGLE_API_KEY)
        ),
    }
