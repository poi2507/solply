"""x402 결제 엔드포인트.

본사-가맹점 정산 — 본사가 판매자(resource server):
  GET  /x402/invoices/{id}/settle  → 402 + accepts[] (즉시납·유예·분할)
  POST /x402/invoices/{id}/settle  → PAYMENT-SIGNATURE 검증 후 정산 확정

지점 간 직거래 — 판매 지점이 resource server:
  GET  /x402/trades/{id}/settle    → 402 + 직거래 대금 조건
  POST /x402/trades/{id}/settle    → 온체인 대조 후 거래 확정 (재고 인수)
"""

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from app import config
from app.core import fixtures, protocol
from app.db import store
from app.solana import payments

router = APIRouter(prefix="/x402", tags=["x402"])


@router.get("/invoices/{invoice_id}/settle")
def challenge(invoice_id: str) -> JSONResponse:
    """정산 요청에 402로 결제 조건을 제시한다 (조건 목록 = 협상 옵션)."""
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        raise HTTPException(404, f"청구서 없음: {invoice_id}")
    if invoice["status"] == "settled":
        return JSONResponse(
            {"status": "already_settled", "invoiceId": invoice_id, "txSig": invoice.get("tx_sig")}
        )

    hq_address = payments.balance("hq")["address"]
    profile = fixtures.load()["stores"].get(invoice["store_id"])
    requirements = protocol.build_payment_requirements(invoice, hq_address, config.NETWORK, profile)

    store.log_event(
        "hq-agent",
        "x402.payment_required",
        {"invoice_id": invoice_id, "options": len(requirements["accepts"])},
    )
    return JSONResponse(
        content=requirements,
        status_code=402,
        headers={"PAYMENT-REQUIRED": protocol.encode_header(requirements)},
    )


@router.post("/invoices/{invoice_id}/settle")
def settle(
    invoice_id: str,
    payment_signature: str | None = Header(default=None, alias="PAYMENT-SIGNATURE"),
) -> JSONResponse:
    """결제 후 재요청. 온체인에서 대조 검증하고 정산을 확정한다."""
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        raise HTTPException(404, f"청구서 없음: {invoice_id}")
    if not payment_signature:
        raise HTTPException(400, "PAYMENT-SIGNATURE 헤더가 필요합니다")

    payload = protocol.decode_header(payment_signature)
    signature = payload.get("payload", {}).get("signature") or payload.get("signature")
    if not signature:
        raise HTTPException(400, "결제 페이로드에 트랜잭션 서명이 없습니다")

    tx = payments.verify_tx(signature)
    transfer = tx.get("transfer") or {}
    amount_ok = abs(transfer.get("amount", 0) - invoice["amount_usdc"]) < 1e-6
    memo_ok = invoice_id in str(tx.get("memo") or "")
    verified = bool(tx.get("found") and tx.get("success") and amount_ok and memo_ok)

    if verified:
        store.update("invoices", invoice_id, {"status": "settled", "tx_sig": signature})
    store.log_event(
        "hq-agent",
        "x402.settled" if verified else "x402.verification_failed",
        {"invoice_id": invoice_id, "tx": signature, "amount_ok": amount_ok, "memo_ok": memo_ok},
    )

    receipt = protocol.build_settlement_response(invoice_id, signature, verified, tx.get("explorer", ""))
    return JSONResponse(
        content={"receipt": receipt, "invoice": store.get("invoices", invoice_id)},
        status_code=200 if verified else 402,
        headers={"PAYMENT-RESPONSE": protocol.encode_header(receipt)},
    )


# ── 지점 간 직거래 (판매 지점이 resource server) ─────────────────────

@router.get("/trades/{trade_id}/settle")
def trade_challenge(trade_id: str) -> JSONResponse:
    """직거래 대금 요청에 402로 결제 조건을 제시한다."""
    trade = store.get("p2p_trades", trade_id)
    if not trade:
        raise HTTPException(404, f"직거래 건 없음: {trade_id}")
    if trade["status"] == "confirmed":
        return JSONResponse(
            {"status": "already_settled", "tradeId": trade_id, "txSig": trade.get("tx_sig")}
        )

    seller_address = payments.balance(trade["seller_id"])["address"]
    requirements = protocol.build_trade_requirements(trade, seller_address, config.NETWORK)
    store.log_event(
        f"{trade['seller_id']}-agent",
        "p2p.payment_required",
        {"trade_id": trade_id, "amount_usdc": trade["price_usdc"]},
    )
    return JSONResponse(
        content=requirements,
        status_code=402,
        headers={"PAYMENT-REQUIRED": protocol.encode_header(requirements)},
    )


@router.post("/trades/{trade_id}/settle")
def trade_settle(
    trade_id: str,
    payment_signature: str | None = Header(default=None, alias="PAYMENT-SIGNATURE"),
) -> JSONResponse:
    """직거래 결제 서명을 온체인에서 대조하고, 일치하면 거래(재고 인수)를 확정한다."""
    trade = store.get("p2p_trades", trade_id)
    if not trade:
        raise HTTPException(404, f"직거래 건 없음: {trade_id}")
    if not payment_signature:
        raise HTTPException(400, "PAYMENT-SIGNATURE 헤더가 필요합니다")

    payload = protocol.decode_header(payment_signature)
    signature = payload.get("payload", {}).get("signature") or payload.get("signature")
    if not signature:
        raise HTTPException(400, "결제 페이로드에 트랜잭션 서명이 없습니다")

    tx = payments.verify_tx(signature)
    transfer = tx.get("transfer") or {}
    amount_ok = abs(transfer.get("amount", 0) - trade["price_usdc"]) < 1e-6
    memo_ok = trade_id in str(tx.get("memo") or "")
    verified = bool(tx.get("found") and tx.get("success") and amount_ok and memo_ok)

    if verified:
        store.update("p2p_trades", trade_id, {"status": "confirmed", "tx_sig": signature})
        # 인수 확정 = 재고 이동 — 판 쪽은 줄고 산 쪽은 는다 (재고 원장)
        from app.agents import utils as agent_utils

        agent_utils.record_move(
            trade["seller_id"], trade["sku"], trade["name"], -trade["qty"], "p2p_out", trade_id
        )
        agent_utils.record_move(
            trade["buyer_id"], trade["sku"], trade["name"], trade["qty"], "p2p_in", trade_id
        )
    store.log_event(
        f"{trade['seller_id']}-agent",
        "p2p.confirmed" if verified else "p2p.verification_failed",
        {"trade_id": trade_id, "tx": signature, "amount_ok": amount_ok, "memo_ok": memo_ok},
    )

    receipt = protocol.build_settlement_response(trade_id, signature, verified, tx.get("explorer", ""))
    return JSONResponse(
        content={"receipt": receipt, "trade": store.get("p2p_trades", trade_id)},
        status_code=200 if verified else 402,
        headers={"PAYMENT-RESPONSE": protocol.encode_header(receipt)},
    )
