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


@pytest.fixture(autouse=True)
def _fresh_rate_buckets():
    """횟수 제한 버킷을 테스트마다 비운다 — 테스트끼리 창을 공유하면 순서에 따라 429가 샌다."""
    from app.api import guard

    guard._BUCKETS.clear()
    yield
    guard._BUCKETS.clear()

@pytest.fixture(autouse=True)
def _assistant_scope_is_hq():
    """어시스턴트 도구는 요청 범위(scope)를 주입받아야 데이터를 본다.

    주입이 없으면 아무것도 안 보이는 쪽으로 실패하도록 만들었으므로(fail-closed),
    범위를 따로 다루지 않는 테스트는 본사 관점으로 묶어둔다.
    """
    from app.assistant import scope

    token = scope.bind("hq")
    yield
    scope.reset(token)
