"""본사 도구 — 부수효과를 일으키는 함수들.

노드가 호출한다. 순수 계산은 `agents/utils.py`, 판단은 `app/llm/judge.py`, 흐름은 `node.py`.
"""

from app.agents import utils
from app.core import kst
from app.core import status as status_mod
from app.db import store
from app.solana import payments

ACTOR = utils.actor_name()


def _invoice_id(store_id: str) -> str:
    """사람이 읽는 청구서 번호 — INV-0729-B01 (날짜·지점·순번).

    무작위 16진수는 화면·영상·온체인 memo 어디서도 읽히지 않는다.
    번호는 지점별 발행 수에서 나오고, 데모 초기화 시 함께 리셋된다.
    """

    day = kst.mmdd()
    initial = store_id.rsplit("-", 1)[-1][:1].upper()
    seq = len(store.list_docs("invoices", store_id=store_id)) + 1
    while store.get("invoices", f"INV-{day}-{initial}{seq:02d}"):
        seq += 1
    return f"INV-{day}-{initial}{seq:02d}"


def create_invoice(delivery_id: str) -> dict:
    """납품 완료 이벤트로부터 청구서를 생성한다 (시드·동적 납품 모두)."""
    delivery = utils.get_delivery(delivery_id)
    if not delivery:
        return utils.error(f"납품 건 없음: {delivery_id}")

    amount = utils.line_total(delivery["items"])
    invoice_id = _invoice_id(delivery["store_id"])
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

    # 납품 = 본사 창고 출고(발주 수량) ↔ 지점 입고(검수 수량).
    # 두 수량의 차이가 곧 검수 분쟁이다 — 원장이 분쟁을 숫자로 보여준다.
    received = utils.receiving_log(delivery["store_id"], delivery_id)
    for item in delivery["items"]:
        utils.record_move("hq", item["sku"], item["name"], -item["qty"], "shipped", delivery_id)
        qty = received.get(item["sku"], 0)
        if qty > 0:
            utils.record_move(
                delivery["store_id"], item["sku"], item["name"], qty, "received", delivery_id
            )
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
            # 처음 청구한 금액 — 화면이 "7.00 → 6.50"으로 합의 결과를 보여줄 근거.
            # 여러 번 조정돼도 최초값을 지킨다.
            "original_amount_usdc": invoice.get("original_amount_usdc", invoice["amount_usdc"]),
        },
    )
    utils.log(
        ACTOR, "invoice.adjusted", {"invoice_id": invoice_id, "new_amount": new_amount_usdc, "reason": reason}
    )
    return invoice


def split_invoice(invoice_id: str, parts: int = 2) -> dict:
    """분할 역제안이 합의 경로가 되도록 청구서를 회차별 자식 청구서로 쪼갠다.

    1회차는 즉시 결제 대상(issued), 나머지는 예약(scheduled) — 기존 x402 왕복과
    예약 실행기를 그대로 태우기 위한 구조다. 원본은 split으로 남아 이력이 이어진다.
    """
    invoice = utils.get_invoice(invoice_id)
    if not invoice:
        return utils.error(f"청구서 없음: {invoice_id}")
    if invoice["status"] not in status_mod.ACTIONABLE:
        # 손으로 적은 목록엔 refused가 빠져 있었다 — 거부된 청구서가 분할됐다.
        # 받을 수 있고 아직 열려 있는 상태의 정의는 core/status.py 한 곳에서만 온다.
        return utils.error(f"분할할 수 없는 상태: {invoice['status']}")

    per = round(invoice["amount_usdc"] / parts, 2)
    amounts = [per] * (parts - 1) + [round(invoice["amount_usdc"] - per * (parts - 1), 2)]
    children = []
    for i, amount in enumerate(amounts, start=1):
        children.append(
            store.put(
                "invoices",
                f"{invoice_id}-P{i}",
                {
                    "delivery_id": invoice["delivery_id"],
                    "store_id": invoice["store_id"],
                    "items": invoice["items"] if i == 1 else [],
                    "amount_usdc": amount,
                    "status": "issued" if i == 1 else "scheduled",
                    "tx_sig": None,
                    "parent_id": invoice_id,
                    "installment": f"{i}/{parts}",
                },
            )
        )
    store.update("invoices", invoice_id, {"status": "split"})
    utils.log(
        ACTOR,
        "invoice.split",
        {"invoice_id": invoice_id, "parts": parts, "amounts": amounts,
         "children": [c["id"] for c in children]},
    )
    return {"invoice_id": invoice_id, "children": children, "per_usdc": amounts[0]}


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


def review_p2p_trade(trade_id: str, decision: str, reasoning: str) -> dict:
    """가맹점 간 직거래를 심사한다. 위생·품질 책임이 본사에 있으므로 승인이 결제의 전제다."""
    trade = store.get("p2p_trades", trade_id)
    if not trade:
        return utils.error(f"직거래 건 없음: {trade_id}")
    updated = store.update(
        "p2p_trades", trade_id,
        {"status": status_mod.TradeStatus.APPROVED if decision == "accept"
                   else status_mod.TradeStatus.REJECTED},
    )
    utils.log(
        ACTOR, "p2p.reviewed", {"trade_id": trade_id, "decision": decision, "reasoning": reasoning}
    )
    return updated


def record_p2p_settlement(trade_id: str) -> dict:
    """확정된 직거래를 본사 장부에 기록한다 — 본사·가맹점이 같은 장부를 본다."""
    trade = store.get("p2p_trades", trade_id)
    if not trade:
        return utils.error(f"직거래 건 없음: {trade_id}")
    if trade["status"] != status_mod.TradeStatus.CONFIRMED:
        return utils.error(f"확정 전이라 기록할 수 없음: {trade['status']}")
    utils.log(
        ACTOR,
        "p2p.recorded",
        {"trade_id": trade_id, "buyer_id": trade["buyer_id"], "seller_id": trade["seller_id"],
         "sku": trade["sku"], "qty": trade["qty"], "amount_usdc": trade["price_usdc"],
         "tx": trade.get("tx_sig")},
    )
    return trade


def store_credit(store_id: str) -> dict:
    """가맹점의 신용 정보 — 유예 심사의 근거.

    점수는 상수가 아니라 `core/credit.py`가 납부 이력(시드 + 이번 세션 온체인 정산)에서
    계산한다. 근거(정시납·연체·분쟁 건수)가 함께 온다.
    """
    from app.core import credit

    profile = utils.store_profile(store_id) or {}
    rating = credit.evaluate(store_id)
    settled = [i for i in store.list_docs("invoices", store_id=store_id) if i["status"] == "settled"]
    return {
        **rating,
        "credit_limit_usdc": profile.get("credit_limit_usdc", 0),
        "settled_count": len(settled),
        "settled_usdc": round(sum(i["amount_usdc"] for i in settled), 2),
    }
