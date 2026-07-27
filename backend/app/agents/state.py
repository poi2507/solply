"""두 에이전트가 공유하는 상태 베이스.

에이전트별 상태는 각자 폴더의 `state.py`가 이걸 상속해 자기 필드를 더한다.
여기 두는 건 "청구서 한 건을 처리한다"는 공통 맥락뿐이다.
"""

from operator import add
from typing import Annotated, Any, Literal, TypedDict

# 그래프가 끝난 뒤 오케스트레이터가 다음 상대에게 넘길 때 보는 결말
Outcome = Literal[
    "settled",        # 정산 확정
    "paid",           # 결제는 했고 상대 검증 대기
    "negotiating",    # 제안을 냈고 상대 응답 대기
    "scheduled",      # 유예·분할 합의됨
    "refused",        # 이상 청구 거부 (사람에게 넘김)
    "needs_human",    # 한도 초과 등으로 승인 필요
    "noop",           # 할 일 없음
]


class BaseState(TypedDict, total=False):
    """모든 에이전트 그래프가 공통으로 다루는 값."""

    # 입력
    actor: str                      # hq-agent | store-a-agent …
    intent: str                     # 오케스트레이터가 준 지시
    invoice_id: str
    payload: dict[str, Any]         # 지시에 딸린 값 (제안 내용, 트랜잭션 서명 등)

    # 맥락
    policy: dict[str, Any]          # DB에서 읽은 정책 (프롬프트 주입용)
    invoice: dict[str, Any]

    # 결과
    outcome: Outcome
    tx_signature: str
    messages: Annotated[list[str], add]   # 사람이 읽는 진행 보고 (노드마다 append)
    reasoning: Annotated[list[str], add]  # 판단 근거 — 실행 증빙에 함께 남는다


def initial_state(actor: str, intent: str, **kwargs: Any) -> dict[str, Any]:
    """그래프 진입 상태를 만든다.

    `outcome`은 일부러 비워둔다 — 라우터가 "outcome이 noop이면 중단"으로 읽기 때문에,
    시작부터 채워두면 첫 분기에서 바로 끝나버린다. 결말은 노드가 정한다.
    """
    return {
        "actor": actor,
        "intent": intent,
        "payload": kwargs.pop("payload", {}) or {},
        "messages": [],
        "reasoning": [],
        **kwargs,
    }
