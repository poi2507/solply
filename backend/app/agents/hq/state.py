"""본사 그래프 상태.

받는 쪽의 판단에 필요한 것만 더한다 — 무엇을 청구할지(delivery_id)와
협상 제안을 어떻게 심사했는지(decision).
"""

from typing import Any

from app.agents.state import BaseState


class HQState(BaseState, total=False):
    delivery_id: str                # 청구서를 만들 납품 건
    decision: dict[str, Any]        # 협상 심사 결과 {decision, reasoning, kind, …}
    trade_id: str                   # 심사·기록할 지점 간 직거래 건
    trade: dict[str, Any]
    # 협상 기록 문서 — 스키마에 없는 키는 LangGraph가 버려 A2A 응답에서 사라진다
    proposal: dict[str, Any]
