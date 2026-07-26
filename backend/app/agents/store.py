"""가맹점 에이전트 — 돈을 내는 쪽.

검증 없이 내지 않고, 못 낼 때는 협상한다.
지점마다 같은 코드에 지갑·정책만 다르게 주입한 인스턴스를 만든다.
"""

from app import config
from app.chain import payments
from app.core import fixtures
from app.db import store as db


def make_tools(store_id: str, spend_limit: float):
    """지점에 바인딩된 도구 묶음을 만든다."""
    actor = f"{store_id}-agent"

    def get_my_invoices() -> list[dict]:
        """이 지점 앞으로 발행된 미결 청구서를 조회한다."""
        docs = db.list_docs("invoices", store_id=store_id)
        return [d for d in docs if d["status"] not in ("paid", "settled")]

    def verify_delivery(invoice_id: str) -> dict:
        """청구서를 자체 검수 기록과 대조해 품목별 불일치를 산출한다."""
        invoice = db.get("invoices", invoice_id)
        if not invoice or invoice["store_id"] != store_id:
            return {"error": f"이 지점의 청구서가 아님: {invoice_id}"}

        logs = fixtures.load()["receiving_logs"].get(store_id, {}).get(invoice["delivery_id"], {})
        discrepancies = [
            {
                "sku": item["sku"],
                "name": item["name"],
                "invoiced_qty": item["qty"],
                "received_qty": logs.get(item["sku"], 0),
                "over_billed_usdc": round((item["qty"] - logs.get(item["sku"], 0)) * item["unit_price_usdc"], 2),
            }
            for item in invoice["items"]
            if logs.get(item["sku"], 0) != item["qty"]
        ]
        result = {"invoice_id": invoice_id, "match": not discrepancies, "discrepancies": discrepancies}
        db.log_event(actor, "delivery.verified", result)
        return result

    def assess_cashflow(invoice_id: str) -> dict:
        """지갑 잔액과 예상 현금흐름으로 지불 여력을 판단할 재료를 모은다."""
        invoice = db.get("invoices", invoice_id)
        if not invoice:
            return {"error": f"청구서 없음: {invoice_id}"}
        balance = payments.balance(store_id)
        return {
            "invoice_amount_usdc": invoice["amount_usdc"],
            "wallet_usdc": balance["usdc"],
            "wallet_sol": balance["sol"],
            "sufficient": balance["usdc"] >= invoice["amount_usdc"],
            "auto_pay_limit_usdc": spend_limit,
            "within_auto_limit": invoice["amount_usdc"] <= spend_limit,
            "pos_forecast": fixtures.load()["pos_forecast"].get(store_id, {}),
        }

    def execute_payment(invoice_id: str) -> dict:
        """청구서를 USDC로 결제한다. 자동결제 한도를 넘으면 사람 승인을 요구한다."""
        invoice = db.get("invoices", invoice_id)
        if not invoice or invoice["store_id"] != store_id:
            return {"error": f"이 지점의 청구서가 아님: {invoice_id}"}
        if invoice["amount_usdc"] > spend_limit:
            db.log_event(actor, "payment.blocked_over_limit", {"invoice_id": invoice_id})
            return {
                "status": "needs_human_approval",
                "reason": f"자동결제 한도 초과: {invoice['amount_usdc']} > {spend_limit} USDC",
            }

        hq_address = payments.balance("hq")["address"]
        result = payments.pay(store_id, hq_address, invoice["amount_usdc"], invoice_id)
        db.update("invoices", invoice_id, {"status": "paid", "tx_sig": result["signature"]})
        db.log_event(actor, "payment.executed", {"invoice_id": invoice_id, "tx": result["signature"]})
        return result

    def propose_adjustment(invoice_id: str, deduction_usdc: float, reason: str) -> dict:
        """검수 불일치분 차감을 본사에 제안한다."""
        proposal = {
            "invoice_id": invoice_id,
            "type": "adjustment",
            "deduction_usdc": deduction_usdc,
            "reason": reason,
            "proposed_by": actor,
        }
        db.update("invoices", invoice_id, {"status": "disputed"})
        db.log_event(actor, "proposal.adjustment", proposal)
        return proposal

    def propose_deferral(invoice_id: str, pay_when: str, reason: str) -> dict:
        """잔액 부족 시 납부 유예(또는 분할)를 본사에 제안한다."""
        proposal = {
            "invoice_id": invoice_id,
            "type": "deferral",
            "pay_when": pay_when,
            "reason": reason,
            "proposed_by": actor,
        }
        db.log_event(actor, "proposal.deferral", proposal)
        return proposal

    def refuse_payment(invoice_id: str, reason: str) -> dict:
        """이상 청구(미발주 품목·비정상 금액)를 거부하고 사람에게 에스컬레이션한다."""
        db.update("invoices", invoice_id, {"status": "refused"})
        db.log_event(actor, "payment.refused", {"invoice_id": invoice_id, "reason": reason})
        return {"status": "refused", "escalated_to_human": True, "reason": reason}

    return [
        get_my_invoices,
        verify_delivery,
        assess_cashflow,
        execute_payment,
        propose_adjustment,
        propose_deferral,
        refuse_payment,
    ]


def instruction(store_id: str) -> str:
    return (
        f"너는 프랜차이즈 {store_id} 지점의 대금 지불 담당 에이전트다.\n"
        "청구서를 받으면 반드시 이 순서로 처리해라:\n"
        "1. verify_delivery로 검수 기록과 대조한다. 불일치가 있으면 propose_adjustment로 "
        "차감을 제안하고 결제를 보류한다.\n"
        "2. 검수가 일치하면 assess_cashflow로 지불 여력을 확인한다.\n"
        "3. 잔액이 충분하고 한도 내면 execute_payment로 즉시 결제하고 서명을 보고한다.\n"
        "4. 잔액이 부족하면 pos_forecast의 예상 입금 일정을 근거로 propose_deferral로 유예를 제안한다.\n"
        "5. 발주하지 않은 품목이 청구되거나 금액이 비정상이면 refuse_payment로 거부해라.\n"
        "돈을 쓰는 판단은 보수적으로, 근거 없는 결제는 절대 하지 마라. 항상 한국어로 간결하게 보고해라."
    )


def build(store_id: str | None = None, spend_limit: float | None = None):
    """지점 에이전트를 만든다."""
    store_id = store_id or config.STORE_ID
    spend_limit = spend_limit if spend_limit is not None else config.SPEND_LIMIT_USDC
    tools = make_tools(store_id, spend_limit)

    if config.LLM_PROVIDER == "mock":
        from app.llm.mock import MockAgent, store_planner

        return MockAgent(f"solply_{store_id}", tools, store_planner)

    from google.adk.agents import Agent

    return Agent(
        name=f"solply_{store_id.replace('-', '_')}",
        model=config.STORE_MODEL,
        description=f"Solply 가맹점 에이전트 ({store_id}) — 검수 검증·자율 결제·협상",
        instruction=instruction(store_id),
        tools=tools,
    )


root_agent = build()  # `adk web` 진입점
