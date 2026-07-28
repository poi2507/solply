"""예약 납부 실행 API.

유예 합의로 `scheduled`가 된 청구서를 예약일에 실행한다. 실행 주체는 가맹점
에이전트 그래프 그대로다 — 예약이라고 다른 코드가 도는 게 아니라, 같은 x402
왕복(정산 요청 → 조건 선택 → 결제 → 서명 제출)을 시점만 늦춰 태운다.

배포 후에는 Cloud Scheduler가 이 엔드포인트를 부른다. 데모에서는 시간을 당겨
직접 실행한다.
"""

from fastapi import APIRouter, HTTPException

from app.agents import runner
from app.db import store

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("")
def list_scheduled() -> dict:
    """예약(유예 합의) 상태의 청구서 목록."""
    docs = [d for d in store.list_docs("invoices") if d["status"] == "scheduled"]
    return {"scheduled": sorted(docs, key=lambda d: d.get("updated_at", ""))}


@router.post("/{invoice_id}/run")
async def run_scheduled(invoice_id: str) -> dict:
    """예약 납부를 지금 실행한다 (데모: 시간 당김 / 운영: Cloud Scheduler)."""
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        raise HTTPException(404, f"청구서 없음: {invoice_id}")
    if invoice["status"] != "scheduled":
        raise HTTPException(409, f"예약 상태가 아님: {invoice_id} ({invoice['status']})")

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
