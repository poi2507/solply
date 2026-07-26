"""x402 결제 엔드포인트 — 본사가 판매자(resource server) 역할을 한다.

  GET  /x402/invoices/{id}/settle  → 402 + accepts[] (즉시납·유예·분할)
  POST /x402/invoices/{id}/settle  → PAYMENT-SIGNATURE 검증 후 정산 확정
"""

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from app import config
from app.chain import payments
from app.core import fixtures, protocol
from app.db import store

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
