"""데이터 상점 — 본사가 x402 판매자가 되는 곳.

  GET  /x402/data/{product}/{sku}            → 402 + 주문서 (견적)
  POST /x402/data/orders/{order_id}/settle   → 결제 증빙 검증 후 지수 인도

청구서 정산과 같은 규약, 같은 3중 대조다. 다른 점은 상대 — 세로(본사↔지점),
가로(지점↔지점)에 이어 이번엔 바깥(외부 구매자)을 향한다. 주문 문서가
memo의 근거이자 재사용 차단 장치다: 한 주문은 한 번만 이행된다.
"""

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from app import config
from app.core import data_products, protocol, stats
from app.core import policy as policy_mod
from app.db import store
from app.solana import payments

router = APIRouter(prefix="/x402/data", tags=["data"])


@router.get("/{product}/{sku}")
def quote(product: str, sku: str) -> JSONResponse:
    """데이터 견적 — 402와 함께 주문서를 발행한다."""
    if product not in data_products.PRODUCTS:
        raise HTTPException(404, f"없는 데이터 상품: {product} (market | demand)")

    order = store.put(
        "data_orders",
        store.new_id("ORD"),
        {
            "product": product,
            "sku": sku,
            "price_usdc": policy_mod.get("hq").data_price_usdc,
            "state": "quoted",
        },
    )
    hq_address = payments.balance("hq")["address"]
    requirements = protocol.build_data_requirements(order, hq_address, config.NETWORK)
    store.log_event(
        "hq-agent", "data.quoted",
        {"order_id": order["id"], "product": product, "sku": sku,
         "price_usdc": order["price_usdc"]},
    )
    return JSONResponse(
        content=requirements,
        status_code=402,
        headers={"PAYMENT-REQUIRED": protocol.encode_header(requirements)},
    )


@router.post("/orders/{order_id}/settle")
def settle(
    order_id: str,
    payment_signature: str | None = Header(default=None, alias="PAYMENT-SIGNATURE"),
) -> JSONResponse:
    """결제 증빙을 대조하고, 통과하면 지수를 인도한다."""
    order = store.get("data_orders", order_id)
    if not order:
        raise HTTPException(404, f"주문 없음: {order_id}")
    if not payment_signature:
        raise HTTPException(400, "PAYMENT-SIGNATURE 헤더가 필요합니다")

    payload = protocol.decode_header(payment_signature)
    signature = payload.get("payload", {}).get("signature") or payload.get("signature")
    if not signature:
        raise HTTPException(400, "결제 페이로드에 트랜잭션 서명이 없습니다")

    if order["state"] == "fulfilled":
        # 같은 주문의 재요청 — 같은 결제면 데이터를 다시 내준다 (멱등 재시도),
        # 다른 서명이면 거절 (주문 하나 = 이행 한 번)
        if order.get("tx_sig") != signature:
            raise HTTPException(409, "이미 이행된 주문입니다")
        data = data_products.build(order["product"], order["sku"])
        return JSONResponse({"data": data, "order": order})

    tx = payments.verify_tx(signature)
    transfer = tx.get("transfer") or {}
    amount_ok = abs(transfer.get("amount", 0) - order["price_usdc"]) < 1e-6
    memo_ok = order_id in str(tx.get("memo") or "")
    verified = bool(tx.get("found") and tx.get("success") and amount_ok and memo_ok)

    if verified:
        order = store.update("data_orders", order_id, {"state": "fulfilled", "tx_sig": signature})
        stats.add("data_sales", order["price_usdc"])
        store.log_event(
            "hq-agent", "data.sold",
            {"order_id": order_id, "product": order["product"], "sku": order["sku"],
             "price_usdc": order["price_usdc"], "tx": signature},
        )
    receipt = protocol.build_settlement_response(order_id, signature, verified, tx.get("explorer", ""))
    body: dict = {"receipt": receipt, "order": store.get("data_orders", order_id)}
    if verified:
        body["data"] = data_products.build(order["product"], order["sku"])
    return JSONResponse(
        content=body,
        status_code=200 if verified else 402,
        headers={"PAYMENT-RESPONSE": protocol.encode_header(receipt)},
    )
