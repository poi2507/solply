"""Solply 본사(HQ) 정산 에이전트.

돈을 받는 쪽: 납품 이벤트 → 청구서 생성 → 제안 심사 → 수금 검증 → 정산.
설계 근거: docs/product-design.md, docs/architecture.html
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from google.adk.agents import Agent

from solply import fixtures, payments, state

load_dotenv()

ACTOR = "hq-agent"


def create_invoices(delivery_id: str) -> dict:
    """납품 완료 이벤트로부터 청구서를 생성한다.

    Args:
        delivery_id: 납품 건 ID (예: DEL-001)
    """
    data = fixtures.load()
    delivery = data["deliveries"].get(delivery_id)
    if not delivery:
        return {"error": f"납품 건 없음: {delivery_id}"}

    amount = round(sum(i["qty"] * i["unit_price_usdc"] for i in delivery["items"]), 2)
    invoice_id = state.new_id("INV")
    invoice = state.put(
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
    state.log_event(ACTOR, "invoice.created", {"invoice_id": invoice_id, "amount": amount})
    return invoice


def get_invoice(invoice_id: str) -> dict:
    """청구서 상세를 조회한다."""
    return state.get("invoices", invoice_id) or {"error": f"청구서 없음: {invoice_id}"}


def list_open_invoices() -> list[dict]:
    """미결(issued/disputed/scheduled) 청구서 목록을 조회한다."""
    docs = state.list_docs("invoices")
    return [d for d in docs if d["status"] not in ("paid", "settled")]


def get_store_profile(store_id: str) -> dict:
    """가맹점 프로필(신용점수·외상한도·정책)을 조회한다."""
    profile = fixtures.load()["stores"].get(store_id)
    return profile or {"error": f"가맹점 없음: {store_id}"}


def review_proposal(
    invoice_id: str, proposal_type: str, proposal_detail: str, decision: str, reasoning: str
) -> dict:
    """가맹점의 협상 제안(차감/유예/분할)에 대한 심사 결정을 기록·적용한다.

    Args:
        invoice_id: 대상 청구서 ID
        proposal_type: adjustment | deferral | installment
        proposal_detail: 제안 내용 요약 (예: "닭 1박스 부족, 2.5 USDC 차감")
        decision: accept | reject | counter
        reasoning: 결정 사유 (신용 이력·정책 근거 포함) — 실행 증빙 로그에 남는다
    """
    invoice = state.get("invoices", invoice_id)
    if not invoice:
        return {"error": f"청구서 없음: {invoice_id}"}

    neg_id = state.new_id("NEG")
    negotiation = state.put(
        "negotiations",
        neg_id,
        {
            "invoice_id": invoice_id,
            "type": proposal_type,
            "proposal": proposal_detail,
            "decision": decision,
            "reasoning": reasoning,
        },
    )
    if decision == "accept" and proposal_type == "deferral":
        state.update("invoices", invoice_id, {"status": "scheduled"})
    elif decision == "accept" and proposal_type == "adjustment":
        state.update("invoices", invoice_id, {"status": "issued"})
    state.log_event(ACTOR, "proposal.reviewed", negotiation)
    return negotiation


def adjust_invoice_amount(invoice_id: str, new_amount_usdc: float, reason: str) -> dict:
    """차감 수락 시 청구 금액을 조정해 재발행한다."""
    invoice = state.update(
        "invoices", invoice_id, {"amount_usdc": new_amount_usdc, "status": "issued"}
    )
    state.log_event(ACTOR, "invoice.adjusted", {"invoice_id": invoice_id, "new_amount": new_amount_usdc, "reason": reason})
    return invoice


def verify_payment(invoice_id: str, tx_signature: str) -> dict:
    """가맹점이 제출한 트랜잭션을 온체인에서 대조 검증하고, 일치하면 정산 확정한다."""
    invoice = state.get("invoices", invoice_id)
    if not invoice:
        return {"error": f"청구서 없음: {invoice_id}"}

    tx = payments.verify_tx(tx_signature)
    if not tx.get("found") or not tx.get("success"):
        return {"verified": False, "reason": "트랜잭션 미확인 또는 실패", "tx": tx}

    transfer = tx.get("transfer") or {}
    amount_ok = abs(transfer.get("amount", 0) - invoice["amount_usdc"]) < 0.000001
    memo_ok = invoice_id in str(tx.get("memo") or "")
    verified = amount_ok and memo_ok

    if verified:
        state.update("invoices", invoice_id, {"status": "settled", "tx_sig": tx_signature})
    state.log_event(
        ACTOR,
        "payment.verified" if verified else "payment.mismatch",
        {"invoice_id": invoice_id, "tx": tx_signature, "amount_ok": amount_ok, "memo_ok": memo_ok},
    )
    return {"verified": verified, "amount_ok": amount_ok, "memo_ok": memo_ok, "explorer": tx.get("explorer")}


root_agent = Agent(
    name="solply_hq",
    model=os.getenv("HQ_MODEL", "gemini-2.5-flash"),
    description="Solply 본사 정산 에이전트 — 식자재 대금의 청구·심사·수금 검증·정산",
    instruction=(
        "너는 프랜차이즈 본사의 식자재 대금(물대) 정산 담당 에이전트다.\n"
        "- 납품 완료 보고를 받으면 create_invoices로 청구서를 만들어라.\n"
        "- 가맹점의 차감 제안은 납품 데이터와 대조해 합당하면 수락하고 adjust_invoice_amount로 재발행해라.\n"
        "- 유예/분할 제안은 get_store_profile의 신용점수·정책(defer_max_pct, installment_max)을 근거로 심사해라. "
        "신용점수 85 이상이고 납부기한 내 제안이면 수락하는 것을 원칙으로 한다.\n"
        "- 모든 심사 결정은 review_proposal로 기록하되 reasoning에 판단 근거를 반드시 남겨라.\n"
        "- 가맹점이 결제했다고 보고하면 verify_payment로 온체인 대조 후 정산을 확정하고, "
        "explorer 링크를 함께 보고해라.\n"
        "- 항상 한국어로 간결하게 보고해라."
    ),
    tools=[
        create_invoices,
        get_invoice,
        list_open_invoices,
        get_store_profile,
        review_proposal,
        adjust_invoice_amount,
        verify_payment,
    ],
)
