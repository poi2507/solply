"""본사(HQ) 정산 에이전트 — 돈을 받는 쪽.

납품 이벤트 → 청구서 생성 → 협상 제안 심사 → 수금 검증 → 정산 확정.
도구 함수는 mock 모드에서도 그대로 호출되므로 부수효과는 전부 여기에 모아둔다.
프롬프트는 prompt.py, 공통 계산은 agents/utils.py.
"""

from app import config
from app.agents import utils
from app.agents.hq import prompt
from app.db import store
from app.solana import payments

ACTOR = utils.actor_name()


def create_invoices(delivery_id: str) -> dict:
    """납품 완료 이벤트로부터 청구서를 생성한다.

    Args:
        delivery_id: 납품 건 ID (예: DEL-001)
    """
    from app.core import fixtures

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


def get_invoice(invoice_id: str) -> dict:
    """청구서 상세를 조회한다."""
    return utils.get_invoice(invoice_id) or utils.error(f"청구서 없음: {invoice_id}")


def list_open_invoices() -> list[dict]:
    """미결(issued/disputed/scheduled) 청구서 목록을 조회한다."""
    return utils.open_invoices()


def get_store_profile(store_id: str) -> dict:
    """가맹점 프로필(신용점수·외상한도·정책)을 조회한다."""
    return utils.store_profile(store_id) or utils.error(f"가맹점 없음: {store_id}")


def review_proposal(
    invoice_id: str, proposal_type: str, proposal_detail: str, decision: str, reasoning: str
) -> dict:
    """가맹점의 협상 제안(차감/유예/분할)을 심사하고 결정을 기록한다.

    Args:
        invoice_id: 대상 청구서 ID
        proposal_type: adjustment | deferral | installment
        proposal_detail: 제안 내용 요약
        decision: accept | reject | counter
        reasoning: 판단 근거 (신용 이력·정책) — 실행 증빙 로그에 남는다
    """
    if not utils.get_invoice(invoice_id):
        return utils.error(f"청구서 없음: {invoice_id}")

    negotiation = store.put(
        "negotiations",
        store.new_id("NEG"),
        {
            "invoice_id": invoice_id,
            "type": proposal_type,
            "proposal": proposal_detail,
            "decision": decision,
            "reasoning": reasoning,
        },
    )
    if decision == "accept" and proposal_type in ("deferral", "installment"):
        store.update("invoices", invoice_id, {"status": "scheduled"})
    utils.log(ACTOR, "proposal.reviewed", negotiation)
    return negotiation


def adjust_invoice_amount(invoice_id: str, new_amount_usdc: float, reason: str) -> dict:
    """차감 수락 시 청구서를 실입고분으로 정정해 재발행한다."""
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
        ACTOR,
        "invoice.adjusted",
        {"invoice_id": invoice_id, "new_amount": new_amount_usdc, "reason": reason},
    )
    return invoice


def verify_payment(invoice_id: str, tx_signature: str) -> dict:
    """가맹점이 제출한 트랜잭션을 온체인에서 대조하고, 일치하면 정산을 확정한다."""
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


TOOLS = [
    create_invoices,
    get_invoice,
    list_open_invoices,
    get_store_profile,
    review_proposal,
    adjust_invoice_amount,
    verify_payment,
]


def build():
    """설정에 따라 Gemini 에이전트 또는 mock 에이전트를 만든다."""
    if config.LLM_PROVIDER == "mock":
        from app.llm.mock import MockAgent, hq_planner

        return MockAgent("solply_hq", TOOLS, hq_planner)

    from google.adk.agents import Agent

    return Agent(
        name="solply_hq",
        model=config.HQ_MODEL,
        description="Solply 본사 정산 에이전트 — 식자재 대금의 청구·심사·수금 검증·정산",
        instruction=prompt.system(),
        tools=TOOLS,
    )


root_agent = build()  # `adk web` 진입점
