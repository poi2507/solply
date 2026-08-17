"""사람 승인 API — 에이전트 자율성의 경계.

사람 몫이 두 종류 온다:
  pending_approval — 정책 상한 초과. 승인하면 에이전트가 이어서 결제한다.
  refused          — 발주 기록 없는 청구를 에이전트가 거부한 것. "거부하고
                     사람에게 넘긴다"고 말했으면 실제로 사람 앞에 도착해야 한다.
                     재발행(발주가 실제로 있었다면)하거나 거부를 확정한다.
사람의 개입은 전부 실행 증빙(actor=human)으로 남는다.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.a2a import client as a2a
from app.api import guard
from app.db import store

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class Decision(BaseModel):
    decision: str  # approve | reject
    note: str = ""


@router.get("")
def list_pending() -> dict:
    """사람 손을 기다리는 청구서 목록 — 승인 대기와, 아직 확인 안 된 거부 건."""
    docs = store.list_docs("invoices", status="pending_approval")
    docs += [d for d in store.list_docs("invoices", status="refused")
             if not d.get("human_reviewed")]
    return {"pending": sorted(docs, key=lambda d: d.get("updated_at", ""))}


@router.post("/{invoice_id}/decide", dependencies=[Depends(guard.require_admin)])
async def decide(invoice_id: str, body: Decision) -> dict:
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        raise HTTPException(404, f"청구서 없음: {invoice_id}")
    if invoice["status"] not in ("pending_approval", "refused"):
        raise HTTPException(409, f"사람 결정 대상이 아님: {invoice['status']}")
    if invoice["status"] == "refused" and invoice.get("human_reviewed"):
        raise HTTPException(409, "이미 사람이 확인한 거부 건")
    if body.decision not in ("approve", "reject"):
        raise HTTPException(400, "decision은 approve 또는 reject")

    action = "human.approved" if body.decision == "approve" else "human.rejected"
    store.log_event(
        "human",
        action,
        {"invoice_id": invoice_id, "amount_usdc": invoice["amount_usdc"], "note": body.note},
    )

    if body.decision == "reject":
        # 승인 대기의 반려든 거부의 확정이든 — 사람이 봤다는 표시를 남겨 큐에서 내린다
        updated = store.update("invoices", invoice_id,
                               {"status": "refused", "human_reviewed": True})
        return {"invoice": updated, "outcome": "refused"}

    # 승인 — 결제는 사람이 아니라 에이전트가 한다. 사람은 권한만 열어준다.
    store.update("invoices", invoice_id, {"status": "issued"})
    final = await a2a.send(invoice["store_id"], "invoice.pay_approved", invoice_id=invoice_id)
    return {
        "invoice": store.get("invoices", invoice_id),
        "outcome": final.get("outcome"),
        "tx_signature": final.get("tx_signature"),
        "messages": final.get("messages", []),
    }
