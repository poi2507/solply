"""예약 납부 실행 API.

유예 합의로 `scheduled`가 된 청구서를 예약일에 실행한다. 실행 주체는 가맹점
에이전트 그래프 그대로다 — 예약이라고 다른 코드가 도는 게 아니라, 같은 x402
왕복(정산 요청 → 조건 선택 → 결제 → 서명 제출)을 시점만 늦춰 태운다.

배포 후에는 Cloud Scheduler가 이 엔드포인트를 부른다. 데모에서는 시간을 당겨
직접 실행한다.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents import runner
from app.core import policy as policy_mod
from app.db import store
from app.solana import payments

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


class RunOptions(BaseModel):
    # 대시보드의 "지금 실행"은 예약일의 카드정산 입금까지 시뮬레이션한다 (시간 당김).
    # Cloud Scheduler는 본문 없이 불러 실제 잔액 그대로 실행된다.
    simulate_inflow: bool = False


def _simulate_card_settlement(store_id: str, invoice_amount: float) -> float:
    """'청구액 + 운영 하한'을 채우는 만큼만 입금 — 데모 반복에도 잔액이 불어나지 않는다."""
    balance = payments.balance(store_id)
    reserve = policy_mod.get(store_id).min_reserve_usdc
    needed = round(max(0.0, invoice_amount + reserve - balance["usdc"]), 2)
    if needed > 0:
        payments.pay("hq", balance["address"], needed, "CARD-SETTLEMENT")
    return needed


@router.get("")
def list_scheduled() -> dict:
    """예약(유예 합의) 상태의 청구서 목록."""
    docs = store.list_docs("invoices", status="scheduled")
    return {"scheduled": sorted(docs, key=lambda d: d.get("updated_at", ""))}


@router.post("/{invoice_id}/run")
async def run_scheduled(invoice_id: str, options: RunOptions | None = None) -> dict:
    """예약 납부를 지금 실행한다 (데모: 시간 당김 / 운영: Cloud Scheduler)."""
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        raise HTTPException(404, f"청구서 없음: {invoice_id}")
    if invoice["status"] != "scheduled":
        raise HTTPException(409, f"예약 상태가 아님: {invoice_id} ({invoice['status']})")

    if options and options.simulate_inflow:
        _simulate_card_settlement(invoice["store_id"], invoice["amount_usdc"])

    final = await runner.run(
        "store", "invoice.pay_scheduled",
        store_id=invoice["store_id"], invoice_id=invoice_id,
    )
    return {
        "invoice": store.get("invoices", invoice_id),
        "outcome": final.get("outcome"),
        "tx_signature": final.get("tx_signature"),
        "messages": final.get("messages", []),
    }
