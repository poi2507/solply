"""가맹점 그래프 상태.

내는 쪽의 판단에 필요한 것만 더한다 — 어느 지점인지, 검수가 맞는지,
낼 여력이 있는지, 그리고 못 낼 때 무엇을 제안했는지.
"""

from typing import Any

from app.agents.state import BaseState


class StoreState(BaseState, total=False):
    store_id: str
    verification: dict[str, Any]    # 검수 대조 결과 {match, discrepancies}
    x402_terms: list[dict]          # 402 챌린지의 accepts[] — 본사가 제시한 결제 조건들
    cashflow: dict[str, Any]        # 지불 여력 {sufficient, keeps_reserve, within_auto_limit, …}
    proposal: dict[str, Any]        # 본사에 낸 협상 제안

    # 지점 간 직거래 (P2P)
    trade_id: str
    trade: dict[str, Any]           # 직거래 문서 {sku, qty, price_usdc, buyer_id, seller_id, status}
    inventory: dict[str, Any]       # 재고 현황 (시드 + 확정 거래 반영)
    shortage: dict[str, Any]        # 안전재고 미달 품목 {sku, qty, safety, need}
    supply: dict[str, Any]          # 선택한 조달처 {store_id, name, surplus, unit_price_usdc}
