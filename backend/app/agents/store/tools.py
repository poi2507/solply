"""가맹점 도구 — 부수효과를 일으키는 함수들.

노드가 호출한다. 순수 계산은 `agents/utils.py`, 판단은 `app/llm`, 흐름은 `node.py`.
모든 함수가 store_id를 명시적으로 받는다 — 지점별 인스턴스를 따로 만들지 않기 위해서다.
"""

from app.agents import utils
from app.core import policy as policy_mod
from app.core import protocol, x402_client
from app.db import store as db
from app.solana import payments


def list_open_invoices(store_id: str) -> list[dict]:
    """이 지점 앞으로 발행된 미결 청구서."""
    return utils.open_invoices(store_id)


def verify_delivery(store_id: str, invoice_id: str) -> dict:
    """청구서를 자체 검수 기록과 대조해 품목별 불일치를 산출한다."""
    invoice = utils.get_invoice(invoice_id, store_id=store_id)
    if not invoice:
        return utils.error(f"이 지점의 청구서가 아님: {invoice_id}")

    received = utils.receiving_log(store_id, invoice["delivery_id"])
    discrepancies = utils.find_discrepancies(invoice["items"], received)
    result = {"invoice_id": invoice_id, "match": not discrepancies, "discrepancies": discrepancies}
    utils.log(utils.actor_name(store_id), "delivery.verified", result)
    return result


def assess_cashflow(store_id: str, invoice_id: str) -> dict:
    """잔액·정책 한도·예상 입금으로 지불 여력을 판단할 재료를 모은다.

    상한(auto_pay_limit)과 하한(min_reserve)을 모두 본다 — 둘 다 점주가 설정한 값이다.
    """
    invoice = utils.get_invoice(invoice_id, store_id=store_id)
    if not invoice:
        return utils.error(f"이 지점의 청구서가 아님: {invoice_id}")

    pol = policy_mod.get(store_id)
    balance = payments.balance(store_id)
    amount = invoice["amount_usdc"]
    remaining = round(balance["usdc"] - amount, 6)

    return {
        "invoice_amount_usdc": amount,
        "wallet_usdc": balance["usdc"],
        "wallet_sol": balance["sol"],
        "sufficient": balance["usdc"] >= amount,
        "auto_pay_limit_usdc": pol.auto_pay_limit_usdc,
        "within_auto_limit": amount <= pol.auto_pay_limit_usdc,
        "min_reserve_usdc": pol.min_reserve_usdc,
        "balance_after": remaining,
        "keeps_reserve": remaining >= pol.min_reserve_usdc,
        "pos_forecast": utils.pos_forecast(store_id),
    }


def request_settlement_terms(store_id: str, invoice_id: str) -> dict:
    """본사 x402 엔드포인트에 정산을 요청한다. 402 응답의 accepts[]가 협상 조건 목록이다."""
    invoice = utils.get_invoice(invoice_id, store_id=store_id)
    if not invoice:
        return utils.error(f"이 지점의 청구서가 아님: {invoice_id}")

    try:
        challenge = x402_client.fetch_terms(invoice_id)
    except Exception as exc:  # noqa: BLE001 — API 서버가 없으면 도구가 원인을 알려준다
        return utils.error(f"x402 정산 요청 실패 (API 서버 :8080 확인): {exc}")

    if challenge.get("status") == "already_settled":
        return {"invoice_id": invoice_id, "already_settled": True, "accepts": []}

    accepts = challenge.get("accepts", [])
    utils.log(
        utils.actor_name(store_id),
        "x402.terms_received",
        {"invoice_id": invoice_id, "terms": [a.get("extra", {}).get("term") for a in accepts]},
    )
    return {"invoice_id": invoice_id, "already_settled": False, "accepts": accepts}


def execute_payment(store_id: str, invoice_id: str, term: dict | None = None) -> dict:
    """청구서를 USDC로 결제한다. 정책 상한을 넘으면 사람 승인을 요구한다.

    x402 조건(term)이 있으면 그 조건의 수취 주소·금액대로 지불하고, 서명을
    PAYMENT-SIGNATURE로 제출해 본사의 온체인 검증·정산 확정까지 한 왕복으로 끝낸다.
    """
    invoice = utils.get_invoice(invoice_id, store_id=store_id)
    if not invoice:
        return utils.error(f"이 지점의 청구서가 아님: {invoice_id}")

    pol = policy_mod.get(store_id)
    amount = protocol.from_atomic(term["amount"]) if term else invoice["amount_usdc"]
    actor = utils.actor_name(store_id)

    if amount > pol.auto_pay_limit_usdc:
        utils.log(actor, "payment.blocked_over_limit", {"invoice_id": invoice_id, "amount": amount})
        return {
            "status": "needs_human_approval",
            "reason": f"자동결제 상한 초과: {amount} > {pol.auto_pay_limit_usdc} USDC",
        }

    pay_to = term["payTo"] if term else payments.balance("hq")["address"]
    memo = (term or {}).get("extra", {}).get("memo") or invoice_id
    result = payments.pay(store_id, pay_to, amount, memo)

    if term:
        receipt = x402_client.submit_payment(invoice_id, result["signature"]).get("receipt", {})
        utils.log(
            actor,
            "payment.executed",
            {"invoice_id": invoice_id, "tx": result["signature"], "via": "x402",
             "explorer": receipt.get("explorer", "")},
        )
        if not receipt.get("settled"):
            return {**result, "amount": amount, "settled": False,
                    "error": "본사 x402 검증에 실패해 정산이 확정되지 않았습니다."}
        return {**result, "amount": amount, "settled": True, "explorer": receipt.get("explorer", "")}

    # x402 조건 없이 부른 직접 결제 경로 — 정산 확정은 본사 검증(payment.verify)이 맡는다
    db.update("invoices", invoice_id, {"status": "paid", "tx_sig": result["signature"]})
    utils.log(actor, "payment.executed", {"invoice_id": invoice_id, "tx": result["signature"]})
    return {**result, "amount": amount}


def request_approval(store_id: str, invoice_id: str, reason: str) -> dict:
    """자동결제 상한을 넘는 건을 사람에게 넘긴다. 결제는 하지 않는다."""
    db.update("invoices", invoice_id, {"status": "pending_approval"})
    utils.log(
        utils.actor_name(store_id),
        "payment.needs_approval",
        {"invoice_id": invoice_id, "reason": reason},
    )
    return {"status": "pending_approval", "reason": reason}


def propose_adjustment(store_id: str, invoice_id: str, deduction_usdc: float, reason: str) -> dict:
    """검수 불일치분 차감을 본사에 제안한다."""
    proposal = {
        "invoice_id": invoice_id,
        "type": "adjustment",
        "deduction_usdc": deduction_usdc,
        "reason": reason,
        "proposed_by": utils.actor_name(store_id),
    }
    db.update("invoices", invoice_id, {"status": "disputed"})
    utils.log(utils.actor_name(store_id), "proposal.adjustment", proposal)
    return proposal


def propose_deferral(store_id: str, invoice_id: str, pay_when: str, reason: str) -> dict:
    """잔액 부족 시 납부 유예를 본사에 제안한다."""
    proposal = {
        "invoice_id": invoice_id,
        "type": "deferral",
        "pay_when": pay_when,
        "reason": reason,
        "proposed_by": utils.actor_name(store_id),
    }
    utils.log(utils.actor_name(store_id), "proposal.deferral", proposal)
    return proposal


def refuse_payment(store_id: str, invoice_id: str, reason: str) -> dict:
    """이상 청구를 거부하고 사람에게 에스컬레이션한다."""
    db.update("invoices", invoice_id, {"status": "refused"})
    utils.log(
        utils.actor_name(store_id), "payment.refused", {"invoice_id": invoice_id, "reason": reason}
    )
    return {"status": "refused", "escalated_to_human": True, "reason": reason}
