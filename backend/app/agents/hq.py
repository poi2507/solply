"""본사(HQ) 정산 에이전트 — 돈을 받는 쪽.

납품 이벤트 → 청구서 생성 → 협상 제안 심사 → 수금 검증 → 정산 확정.
도구 함수는 mock 모드에서도 그대로 호출되므로 여기에 부수효과를 모아둔다.
"""

from app import config
from app.chain import payments
from app.core import fixtures
from app.db import store

ACTOR = "hq-agent"


def create_invoices(delivery_id: str) -> dict:
    """납품 완료 이벤트로부터 청구서를 생성한다.

    Args:
        delivery_id: 납품 건 ID (예: DEL-001)
    """
    delivery = fixtures.load()["deliveries"].get(delivery_id)
    if not delivery:
        return {"error": f"납품 건 없음: {delivery_id}"}

    amount = round(sum(i["qty"] * i["unit_price_usdc"] for i in delivery["items"]), 2)
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
    store.log_event(ACTOR, "invoice.created", {"invoice_id": invoice_id, "amount": amount})
    return invoice


def get_invoice(invoice_id: str) -> dict:
    """청구서 상세를 조회한다."""
    return store.get("invoices", invoice_id) or {"error": f"청구서 없음: {invoice_id}"}


def list_open_invoices() -> list[dict]:
    """미결(issued/disputed/scheduled) 청구서 목록을 조회한다."""
    return [d for d in store.list_docs("invoices") if d["status"] not in ("paid", "settled")]


def get_store_profile(store_id: str) -> dict:
    """가맹점 프로필(신용점수·외상한도·정책)을 조회한다."""
    return fixtures.load()["stores"].get(store_id) or {"error": f"가맹점 없음: {store_id}"}


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
    if not store.get("invoices", invoice_id):
        return {"error": f"청구서 없음: {invoice_id}"}

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
    store.log_event(ACTOR, "proposal.reviewed", negotiation)
    return negotiation


def adjust_invoice_amount(invoice_id: str, new_amount_usdc: float, reason: str) -> dict:
    """차감 수락 시 청구서를 실입고분으로 정정해 재발행한다.

    금액만 고치면 가맹점이 재검수할 때 같은 불일치를 또 발견하므로 품목 수량도 함께 정정한다.
    """
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        return {"error": f"청구서 없음: {invoice_id}"}

    received = fixtures.load()["receiving_logs"].get(invoice["store_id"], {}).get(invoice["delivery_id"], {})
    corrected = [{**item, "qty": received.get(item["sku"], item["qty"])} for item in invoice["items"]]
    invoice = store.update(
        "invoices",
        invoice_id,
        {"amount_usdc": new_amount_usdc, "items": corrected, "status": "issued", "adjusted": True},
    )
    store.log_event(
        ACTOR, "invoice.adjusted", {"invoice_id": invoice_id, "new_amount": new_amount_usdc, "reason": reason}
    )
    return invoice


def verify_payment(invoice_id: str, tx_signature: str) -> dict:
    """가맹점이 제출한 트랜잭션을 온체인에서 대조하고, 일치하면 정산을 확정한다."""
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        return {"error": f"청구서 없음: {invoice_id}"}

    tx = payments.verify_tx(tx_signature)
    if not tx.get("found") or not tx.get("success"):
        return {"verified": False, "reason": "트랜잭션 미확인 또는 실패"}

    transfer = tx.get("transfer") or {}
    amount_ok = abs(transfer.get("amount", 0) - invoice["amount_usdc"]) < 1e-6
    memo_ok = invoice_id in str(tx.get("memo") or "")
    verified = amount_ok and memo_ok

    if verified:
        store.update("invoices", invoice_id, {"status": "settled", "tx_sig": tx_signature})
    store.log_event(
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

INSTRUCTION = (
    "너는 프랜차이즈 본사의 식자재 대금(물대) 정산 담당 에이전트다.\n"
    "- 납품 완료 보고를 받으면 create_invoices로 청구서를 만들어라.\n"
    "- 차감 제안은 납품 데이터와 대조해 합당하면 review_proposal로 수락을 기록하고 "
    "adjust_invoice_amount로 재발행해라.\n"
    "- 유예/분할 제안은 get_store_profile의 신용점수와 정책을 근거로 심사해라. "
    "신용점수 85 이상이고 납부기한 내 제안이면 수락을 원칙으로 한다.\n"
    "- 모든 심사 결정은 review_proposal로 기록하되 reasoning에 판단 근거를 반드시 남겨라.\n"
    "- 결제 보고를 받으면 verify_payment로 온체인 대조 후 정산을 확정하고 결과를 보고해라.\n"
    "- 항상 한국어로 간결하게 보고해라."
)


def build():
    """설정에 따라 실제 Gemini 에이전트 또는 mock 에이전트를 만든다."""
    if config.LLM_PROVIDER == "mock":
        from app.llm.mock import MockAgent, hq_planner

        return MockAgent("solply_hq", TOOLS, hq_planner)

    from google.adk.agents import Agent

    return Agent(
        name="solply_hq",
        model=config.HQ_MODEL,
        description="Solply 본사 정산 에이전트 — 식자재 대금의 청구·심사·수금 검증·정산",
        instruction=INSTRUCTION,
        tools=TOOLS,
    )


root_agent = build()  # `adk web` 진입점
