"""LangGraph 상태 정의.

에이전트가 한 건의 청구서를 처리하는 동안 노드 사이로 흐르는 값.
노드는 이 상태를 읽고 부분 갱신본(dict)을 돌려주며, LangGraph가 병합한다.

두 에이전트가 같은 상태 타입을 쓰는 이유: 본사와 가맹점이 같은 청구서를 두고
번갈아 판단하므로, 한쪽이 남긴 판단 근거를 다른 쪽이 그대로 읽을 수 있어야 한다.
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


class AgentState(TypedDict, total=False):
    """에이전트 그래프의 작업 상태."""

    # ── 입력 ──
    actor: str                      # hq-agent | store-a-agent ...
    store_id: str                   # 가맹점 그래프에서만
    intent: str                     # 오케스트레이터가 준 지시 (invoice.issue, invoice.handle …)
    invoice_id: str
    delivery_id: str
    payload: dict[str, Any]         # 지시에 딸린 값 (제안 내용, 트랜잭션 서명 등)

    # ── 정책 (DB에서 로드) ──
    policy: dict[str, Any]

    # ── 판단 중간값 ──
    invoice: dict[str, Any]
    verification: dict[str, Any]    # 검수 대조 결과
    cashflow: dict[str, Any]        # 지불 여력
    proposal: dict[str, Any]        # 낸/받은 협상 제안
    decision: dict[str, Any]        # 심사 결정

    # ── 결과 ──
    outcome: Outcome
    tx_signature: str
    messages: Annotated[list[str], add]   # 사람이 읽는 진행 보고 (노드마다 append)
    reasoning: Annotated[list[str], add]  # 판단 근거 — 실행 증빙에 함께 남는다


def initial_state(actor: str, intent: str, **kwargs: Any) -> AgentState:
    """그래프 진입 상태를 만든다.

    `outcome`은 일부러 비워둔다 — 라우터가 "outcome이 noop이면 중단"으로 읽기 때문에,
    시작부터 채워두면 첫 분기에서 바로 끝나버린다. 결말은 노드가 정한다.
    """
    return AgentState(
        actor=actor,
        intent=intent,
        payload=kwargs.pop("payload", {}) or {},
        messages=[],
        reasoning=[],
        **kwargs,
    )
