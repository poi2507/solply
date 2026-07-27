"""본사 도구 — 부수효과를 일으키는 함수들.

노드가 호출한다. 순수 계산은 `agents/utils.py`, 판단은 `app/llm/judge.py`, 흐름은 `node.py`.
"""

from app.agents import utils
from app.core import fixtures
from app.db import store
from app.solana import payments

ACTOR = utils.actor_name()


def create_invoice(delivery_id: str) -> dict:
    """납품 완료 이벤트로부터 청구서를 생성한다."""
    delivery = fixtures.load()["deliveries"].get(delivery_id)
    if not delivery:
        return utils.error(f"납품 건 없음: {delivery_id}")

    amount = utils.line_total(delivery["items"])
    invoice_id = store.new_id("INV")
    invoice = store.put(
        "invoices",
        invoice_id,
        {
            "delivery_id": delivery_id,
            "store_id": delivery["store_id"],
            "items": delivery["items"],
            "amount_usdc": amount,
            "status": "issued",
            "tx_sig": None,
        },
    )
    utils.log(ACTOR, "invoice.created", {"invoice_id": invoice_id, "amount": amount})
    return invoice


def record_decision(invoice_id: str, kind: str, proposal: str, decision: str, reasoning: str) -> dict:
    """협상 심사 결과를 기록한다. 유예·분할 수락 시 청구서를 예약 상태로 옮긴다."""
    negotiation = store.put(
        "negotiations",
        store.new_id("NEG"),
        {
            "invoice_id": invoice_id,
            "type": kind,
            "proposal": proposal,
            "decision": decision,
            "reasoning": reasoning,
        },
    )
    if decision == "accept" and kind in ("deferral", "installment"):
        store.update("invoices", invoice_id, {"status": "scheduled"})
    utils.log(ACTOR, "proposal.reviewed", negotiation)
    return negotiation


def adjust_invoice(invoice_id: str, new_amount_usdc: float, reason: str) -> dict:
    """차감 수락 시 청구서를 실입고분으로 정정해 재발행한다.

    금액만 고치면 가맹점이 재검수할 때 같은 불일치를 또 발견하므로 품목 수량도 정정한다.
    """
    invoice = utils.get_invoice(invoice_id)
    if not invoice:
        return utils.error(f"청구서 없음: {invoice_id}")

    received = utils.receiving_log(invoice["store_id"], invoice["delivery_id"])
    invoice = store.update(
        "invoices",
        invoice_id,
        {
            "amount_usdc": new_amount_usdc,
            "items": utils.correct_items(invoice["items"], received),
            "status": "issued",
            "adjusted": True,
        },
    )
    utils.log(
        ACTOR, "invoice.adjusted", {"invoice_id": invoice_id, "new_amount": new_amount_usdc, "reason": reason}
    )
    return invoice


def verify_payment(invoice_id: str, tx_signature: str) -> dict:
    """제출된 트랜잭션을 온체인에서 대조하고, 일치하면 정산을 확정한다."""
    invoice = utils.get_invoice(invoice_id)
    if not invoice:
        return utils.error(f"청구서 없음: {invoice_id}")

    tx = payments.verify_tx(tx_signature)
    if not tx.get("found") or not tx.get("success"):
        return {"verified": False, "reason": "트랜잭션 미확인 또는 실패"}

    transfer = tx.get("transfer") or {}
    amount_ok = utils.amounts_match(transfer.get("amount", 0), invoice["amount_usdc"])
    memo_ok = invoice_id in str(tx.get("memo") or "")
    verified = amount_ok and memo_ok

    if verified:
        store.update("invoices", invoice_id, {"status": "settled", "tx_sig": tx_signature})
    utils.log(
        ACTOR,
        "payment.verified" if verified else "payment.mismatch",
        {"invoice_id": invoice_id, "tx": tx_signature, "amount_ok": amount_ok, "memo_ok": memo_ok},
    )
    return {
        "verified": verified,
        "amount_ok": amount_ok,
        "memo_ok": memo_ok,
        "explorer": tx.get("explorer"),
    }


def store_credit(store_id: str) -> dict:
    """가맹점의 신용 정보 — 유예 심사의 근거."""
    profile = utils.store_profile(store_id) or {}
    settled = [i for i in store.list_docs("invoices", store_id=store_id) if i["status"] == "settled"]
    return {
        "credit_score": profile.get("credit_score", 0),
        "credit_limit_usdc": profile.get("credit_limit_usdc", 0),
        "settled_count": len(settled),
        "settled_usdc": round(sum(i["amount_usdc"] for i in settled), 2),
    }
