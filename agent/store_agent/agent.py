"""Solply 가맹점 에이전트.

돈을 내는 쪽: 검증 없이 내지 않고, 못 낼 때는 협상한다.
STORE_ID 환경변수(store-a|store-b|store-c)로 지점 인스턴스를 구분한다.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from google.adk.agents import Agent

from solply import fixtures, payments, state

load_dotenv()

STORE_ID = os.getenv("STORE_ID", "store-a")
SPEND_LIMIT = float(os.getenv("AGENT_SPEND_LIMIT_USDC", "50"))
ACTOR = f"{STORE_ID}-agent"


def get_my_invoices() -> list[dict]:
    """이 지점 앞으로 발행된 미결 청구서를 조회한다."""
    docs = state.list_docs("invoices", store_id=STORE_ID)
    return [d for d in docs if d["status"] not in ("paid", "settled")]


def verify_delivery(invoice_id: str) -> dict:
    """청구서를 자체 검수 기록과 대조해 품목별 불일치를 산출한다."""
    invoice = state.get("invoices", invoice_id)
    if not invoice or invoice["store_id"] != STORE_ID:
        return {"error": f"이 지점의 청구서가 아님: {invoice_id}"}

    logs = fixtures.load()["receiving_logs"].get(STORE_ID, {}).get(invoice["delivery_id"], {})
    discrepancies = []
    for item in invoice["items"]:
        received = logs.get(item["sku"], 0)
        if received != item["qty"]:
            discrepancies.append(
                {
                    "sku": item["sku"],
                    "name": item["name"],
                    "invoiced_qty": item["qty"],
                    "received_qty": received,
                    "over_billed_usdc": round((item["qty"] - received) * item["unit_price_usdc"], 2),
                }
            )
    result = {"invoice_id": invoice_id, "match": not discrepancies, "discrepancies": discrepancies}
    state.log_event(ACTOR, "delivery.verified", result)
    return result


def assess_cashflow(invoice_id: str) -> dict:
    """지갑 잔액과 예상 현금흐름(POS)으로 이 청구서의 지불 여력을 판단할 재료를 모은다."""
    invoice = state.get("invoices", invoice_id)
    if not invoice:
        return {"error": f"청구서 없음: {invoice_id}"}
    bal = payments.balance(STORE_ID)
    forecast = fixtures.load()["pos_forecast"].get(STORE_ID, {})
    return {
        "invoice_amount_usdc": invoice["amount_usdc"],
        "wallet_usdc": bal["usdc"],
        "wallet_sol": bal["sol"],
        "sufficient": bal["usdc"] >= invoice["amount_usdc"],
        "auto_pay_limit_usdc": SPEND_LIMIT,
        "within_auto_limit": invoice["amount_usdc"] <= SPEND_LIMIT,
        "pos_forecast": forecast,
    }


def execute_payment(invoice_id: str) -> dict:
    """청구서를 USDC로 결제한다. 자동결제 한도를 넘으면 거부하고 사람 승인을 요구한다."""
    invoice = state.get("invoices", invoice_id)
    if not invoice or invoice["store_id"] != STORE_ID:
        return {"error": f"이 지점의 청구서가 아님: {invoice_id}"}
    if invoice["amount_usdc"] > SPEND_LIMIT:
        state.log_event(ACTOR, "payment.blocked_over_limit", {"invoice_id": invoice_id})
        return {
            "status": "needs_human_approval",
            "reason": f"자동결제 한도 초과: {invoice['amount_usdc']} > {SPEND_LIMIT} USDC",
        }

    hq_address = payments.balance("hq")["address"]
    result = payments.pay(STORE_ID, hq_address, invoice["amount_usdc"], invoice_id)
    state.update("invoices", invoice_id, {"status": "paid", "tx_sig": result["signature"]})
    state.log_event(ACTOR, "payment.executed", {"invoice_id": invoice_id, "tx": result["signature"]})
    return result


def propose_adjustment(invoice_id: str, deduction_usdc: float, reason: str) -> dict:
    """검수 불일치분 차감을 본사에 제안한다 (W2에서 A2A 전송으로 교체)."""
    proposal = {
        "invoice_id": invoice_id,
        "type": "adjustment",
        "deduction_usdc": deduction_usdc,
        "reason": reason,
        "proposed_by": ACTOR,
    }
    state.log_event(ACTOR, "proposal.adjustment", proposal)
    return proposal


def propose_deferral(invoice_id: str, pay_when: str, reason: str) -> dict:
    """잔액 부족 시 납부 유예(또는 분할)를 본사에 제안한다 (W2에서 A2A 전송으로 교체)."""
    proposal = {
        "invoice_id": invoice_id,
        "type": "deferral",
        "pay_when": pay_when,
        "reason": reason,
        "proposed_by": ACTOR,
    }
    state.log_event(ACTOR, "proposal.deferral", proposal)
    return proposal


def refuse_payment(invoice_id: str, reason: str) -> dict:
    """이상 청구(미발주 품목·비정상 금액)를 거부하고 사람에게 에스컬레이션한다."""
    state.update("invoices", invoice_id, {"status": "refused"})
    state.log_event(ACTOR, "payment.refused", {"invoice_id": invoice_id, "reason": reason})
    return {"status": "refused", "escalated_to_human": True, "reason": reason}


root_agent = Agent(
    name=f"solply_{STORE_ID.replace('-', '_')}",
    model=os.getenv("STORE_MODEL", "gemini-3.6-flash"),
    description=f"Solply 가맹점 에이전트 ({STORE_ID}) — 검수 검증·자율 결제·협상",
    instruction=(
        f"너는 프랜차이즈 {STORE_ID} 지점의 대금 지불 담당 에이전트다.\n"
        "청구서를 받으면 반드시 이 순서로 처리해라:\n"
        "1. verify_delivery로 검수 기록과 대조한다. 불일치가 있으면 propose_adjustment로 차감을 제안하고 결제를 보류한다.\n"
        "2. 검수가 일치하면 assess_cashflow로 지불 여력을 확인한다.\n"
        "3. 잔액이 충분하고 한도 내면 execute_payment로 즉시 결제하고 트랜잭션 서명을 보고한다.\n"
        "4. 잔액이 부족하면 pos_forecast의 예상 입금 일정을 근거로 propose_deferral로 유예를 제안한다.\n"
        "5. 발주하지 않은 품목이 청구되거나 금액이 비정상적으로 크면 refuse_payment로 거부해라.\n"
        "돈을 쓰는 판단은 보수적으로, 근거 없는 결제는 절대 하지 마라. 항상 한국어로 간결하게 보고해라."
    ),
    tools=[
        get_my_invoices,
        verify_delivery,
        assess_cashflow,
        execute_payment,
        propose_adjustment,
        propose_deferral,
        refuse_payment,
    ],
)
