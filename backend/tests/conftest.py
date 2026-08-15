"""테스트 공통 설정.

**판단은 기본적으로 규칙(mock)으로 돈다.** 개발 환경의 .env가 vertex를 가리키면
테스트가 실제 LLM을 호출해 느려지고(429 재시도) 결과가 흔들린다 — 같은 입력에
다른 답이 나오면 그건 더 이상 테스트가 아니다.

LLM 경로 자체를 보는 테스트는 각자 `is_mock`을 False로 돌려서 켠다.
"""

import pytest


@pytest.fixture(autouse=True)
def _judgment_is_deterministic(monkeypatch):
    monkeypatch.setattr("app.llm.factory.is_mock", lambda: True)
