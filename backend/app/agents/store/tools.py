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


def execute_payment(
    store_id: str, invoice_id: str, term: dict | None = None, human_approved: bool = False
) -> dict:
    """청구서를 USDC로 결제한다. 정책 상한을 넘으면 사람 승인을 요구한다.

    x402 조건(term)이 있으면 그 조건의 수취 주소·금액대로 지불하고, 서명을
    PAYMENT-SIGNATURE로 제출해 본사의 온체인 검증·정산 확정까지 한 왕복으로 끝낸다.
    human_approved는 사람이 대시보드에서 승인한 건 — 상한 검사만 면제되고 나머지는 같다.
    """
    invoice = utils.get_invoice(invoice_id, store_id=store_id)
    if not invoice:
        return utils.error(f"이 지점의 청구서가 아님: {invoice_id}")
    if invoice["status"] in ("paid", "settled"):
        # 이중 결제 방지 — 재시도·중복 호출이 와도 돈은 한 번만 나간다
        return utils.error(f"이미 결제된 청구서: {invoice_id} (상태 {invoice['status']})")

    pol = policy_mod.get(store_id)
    amount = protocol.from_atomic(term["amount"]) if term else invoice["amount_usdc"]
    actor = utils.actor_name(store_id)

    if amount > pol.auto_pay_limit_usdc and not human_approved:
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
             "explorer": receipt.get("explorer", ""),
             **({"human_approved": True} if human_approved else {})},
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


# ── 지점 간 직거래 (P2P) ─────────────────────────────────────────────

def check_inventory(store_id: str) -> dict:
    """지점 재고 현황 — 시드 재고에 확정된 직거래를 반영한 값과 안전재고 미달 품목."""
    inventory = utils.effective_inventory(store_id)
    return {"inventory": inventory, "shortages": utils.stock_shortages(inventory)}


def find_peer_supply(store_id: str, sku: str, qty: int) -> dict:
    """다른 지점의 잉여 재고를 조회하고, 본사 발주 조건과 비교할 재료를 만든다."""
    from app.core import fixtures

    peers = []
    for sid, profile in fixtures.load()["stores"].items():
        if sid == store_id:
            continue
        surplus = utils.sellable_surplus(utils.effective_inventory(sid), sku)
        if surplus >= qty:
            peers.append({"store_id": sid, "name": profile["name"], "surplus": surplus})
    return {"sku": sku, "qty": qty, "peers": peers, "hq_reorder": utils.hq_reorder_terms(sku)}


def propose_p2p_trade(store_id: str, seller_id: str, sku: str, name: str, qty: int, price_usdc: float) -> dict:
    """잉여 지점에 재고 직거래를 제안한다. 대금은 구매 지점이 판매 지점에 직접 낸다."""
    trade = db.put(
        "p2p_trades",
        db.new_id("P2P"),
        {
            "sku": sku, "name": name, "qty": qty, "price_usdc": price_usdc,
            "buyer_id": store_id, "seller_id": seller_id,
            "status": "proposed", "tx_sig": None,
        },
    )
    utils.log(
        utils.actor_name(store_id),
        "p2p.proposed",
        {"trade_id": trade["id"], "seller_id": seller_id, "sku": sku, "qty": qty,
         "price_usdc": price_usdc},
    )
    return trade


def respond_p2p_trade(store_id: str, trade_id: str, decision: str, reasoning: str) -> dict:
    """(판매 지점) 직거래 제안에 응답한다. 안전재고를 지킬 수 있을 때만 수락한다."""
    trade = utils.get_trade(trade_id)
    if not trade or trade["seller_id"] != store_id:
        return utils.error(f"이 지점 앞으로 온 제안이 아님: {trade_id}")
    if trade["status"] != "proposed":
        return utils.error(f"응답할 수 있는 상태가 아님: {trade['status']}")

    updated = db.update(
        "p2p_trades", trade_id, {"status": "accepted" if decision == "accept" else "rejected"}
    )
    utils.log(
        utils.actor_name(store_id),
        "p2p.responded",
        {"trade_id": trade_id, "decision": decision, "reasoning": reasoning},
    )
    return updated


def pay_p2p_trade(store_id: str, trade_id: str) -> dict:
    """(구매 지점) 직거래 대금을 x402 왕복으로 결제한다.

    **본사 승인(approved) 전에는 결제하지 않는다** — 이 가드가 심사 포인트다.
    정책 상한도 본사 정산과 동일하게 적용된다.
    """
    trade = utils.get_trade(trade_id)
    if not trade or trade["buyer_id"] != store_id:
        return utils.error(f"이 지점의 직거래 건이 아님: {trade_id}")
    if trade["status"] != "approved":
        utils.log(
            utils.actor_name(store_id),
            "p2p.blocked_unapproved",
            {"trade_id": trade_id, "status": trade["status"]},
        )
        return utils.error(f"본사 승인 전에는 결제할 수 없음 (현재: {trade['status']})")

    pol = policy_mod.get(store_id)
    amount = trade["price_usdc"]
    actor = utils.actor_name(store_id)
    if amount > pol.auto_pay_limit_usdc:
        utils.log(actor, "p2p.blocked_over_limit", {"trade_id": trade_id, "amount": amount})
        return {
            "status": "needs_human_approval",
            "reason": f"자동결제 상한 초과: {amount} > {pol.auto_pay_limit_usdc} USDC",
        }

    challenge = x402_client.fetch_trade_terms(trade_id)
    term = utils.pick_term(challenge.get("accepts", []), "immediate")
    if not term:
        return utils.error("판매 지점의 402 응답에 결제 조건이 없습니다")

    result = payments.pay(store_id, term["payTo"], protocol.from_atomic(term["amount"]), trade_id)
    utils.log(actor, "p2p.paid", {"trade_id": trade_id, "tx": result["signature"], "amount": amount})

    receipt = x402_client.submit_trade_payment(trade_id, result["signature"]).get("receipt", {})
    if not receipt.get("settled"):
        return {**result, "amount": amount, "settled": False,
                "error": "판매 지점 검증에 실패해 거래가 확정되지 않았습니다."}
    return {**result, "amount": amount, "settled": True, "explorer": receipt.get("explorer", "")}
