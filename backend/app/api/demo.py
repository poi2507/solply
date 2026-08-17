"""무대 트리거 — 발표 중 "지금 실시간으로"를 위한 협상 재생.

시나리오를 목업으로 그리는 게 아니다: 지점 잔액으로 감당 못 할 청구서를
실제로 발행하고, 실제 A2A 3라운드 협상이 라이브 규칙 그대로 돈다.
리허설과 데모데이에서 3시간 스케줄을 기다리지 않기 위한 장치다.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.a2a import client as a2a
from app.agents.hq import tools as hq_tools
from app.api import guard
from app.core import economy, fixtures
from app.core import policy as policy_mod
from app.db import store as db
from app.solana import payments

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/negotiate", dependencies=[Depends(guard.require_admin)])
async def replay_negotiation(store_id: str | None = None) -> dict:
    """협상 한 판을 그 자리에서 발화시킨다.

    조건: 청구액이 자동결제 상한 안(권한 통과)이면서 잔액-하한보다 커야(능력 부족)
    유예 제안이 나온다. 잔액이 가장 얇은 지점을 골라 조건을 만든다.
    """
    stores = list(fixtures.load()["stores"])
    if store_id is None:
        store_id = min(stores, key=lambda s: payments.balance(s)["usdc"])
    elif store_id not in stores:
        raise HTTPException(404, f"없는 지점: {store_id}")

    wallet = payments.balance(store_id)["usdc"]
    pol = policy_mod.get(store_id)
    amount = round(pol.auto_pay_limit_usdc - 0.5, 2)  # 권한은 통과, 능력은 시험
    if amount <= wallet - pol.min_reserve_usdc + 0.05:
        raise HTTPException(
            409,
            f"{store_id} 잔액 {wallet} USDC가 넉넉해 협상 조건이 안 만들어집니다 — "
            f"잔액이 {amount + pol.min_reserve_usdc:.2f} 미만인 지점이 필요합니다",
        )

    delivery = db.put(
        "deliveries",
        economy._delivery_id(store_id),
        {
            "store_id": store_id,
            "items": [{"sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 1,
                       "unit_price_usdc": amount}],
            "received": {"CHK-10": 1},  # 검수 일치 — 협상만 시험한다
            "source": "stage-trigger",
        },
    )
    invoice = hq_tools.create_invoice(delivery["id"])
    if invoice.get("error"):
        raise HTTPException(500, invoice["error"])

    handled = await a2a.send(store_id, "invoice.handle", invoice_id=invoice["id"])
    outcome = handled.get("outcome")
    if outcome == "negotiating":
        outcome = await economy._negotiate_deferral(store_id, invoice["id"])

    return {
        "store_id": store_id,
        "invoice_id": invoice["id"],
        "amount_usdc": invoice["amount_usdc"],
        "outcome": outcome,
        "hint": "협상 기록 패널과 실행 로그에서 라운드를 확인하세요",
    }
