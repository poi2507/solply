"""사람 승인 API — 에이전트 자율성의 경계.

에이전트가 정책 상한을 넘는 결제를 만나면 `pending_approval`로 멈춘다.
여기서 사람이 승인하면 에이전트가 이어서 결제하고(x402 왕복 그대로),
반려하면 거기서 끝난다. 사람의 개입은 전부 실행 증빙(actor=human)으로 남는다.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents import runner
from app.db import store

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class Decision(BaseModel):
    decision: str  # approve | reject
    note: str = ""


@router.get("")
def list_pending() -> dict:
    """사람 승인을 기다리는 청구서 목록."""
    docs = [d for d in store.list_docs("invoices") if d["status"] == "pending_approval"]
    return {"pending": sorted(docs, key=lambda d: d.get("updated_at", ""))}


@router.post("/{invoice_id}/decide")
async def decide(invoice_id: str, body: Decision) -> dict:
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        raise HTTPException(404, f"청구서 없음: {invoice_id}")
    if invoice["status"] != "pending_approval":
        raise HTTPException(409, f"승인 대기 상태가 아님: {invoice['status']}")
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision은 approve 또는 reject")

    action = "human.approved" if body.decision == "approve" else "human.rejected"
    store.log_event(
        "human",
        action,
        {"invoice_id": invoice_id, "amount_usdc": invoice["amount_usdc"], "note": body.note},
    )

    if body.decision == "reject":
        updated = store.update("invoices", invoice_id, {"status": "refused"})
        return {"invoice": updated, "outcome": "refused"}

    # 승인 — 결제는 사람이 아니라 에이전트가 한다. 사람은 권한만 열어준다.
    store.update("invoices", invoice_id, {"status": "issued"})
    final = await runner.run(
        "store", "invoice.pay_approved",
        store_id=invoice["store_id"], invoice_id=invoice_id,
    )
    return {
        "invoice": store.get("invoices", invoice_id),
        "outcome": final.get("outcome"),
        "tx_signature": final.get("tx_signature"),
        "messages": final.get("messages", []),
    }
