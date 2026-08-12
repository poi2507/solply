"""손님 구매 API — 방문자(심사위원 포함)가 라이브 경제에 수요를 넣는 창구.

구매는 지점의 재고 원장에 판매로 기록되고 매출은 금고에 적립된다 —
틱의 시뮬 판매와 정확히 같은 경로(economy.sell). 재고가 안전선을 깨면
다음 틱에서 에이전트가 조달(P2P/본사 발주)을 스스로 시작한다.
방문자는 구경꾼이 아니라 이 경제의 수요가 된다.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import config
from app.agents import utils
from app.core import economy, fixtures, stats
from app.solana import payments

router = APIRouter(prefix="/api/shop", tags=["shop"])


@router.get("")
def menu() -> dict:
    """지점과 판매 품목(현재고·가격) — 손님 페이지의 진열대."""
    stores = []
    for store_id, profile in fixtures.load()["stores"].items():
        inventory = utils.effective_inventory(store_id)
        stores.append({
            "id": store_id,
            "name": profile["name"],
            "items": [
                {"sku": sku, "name": e.get("name", sku), "qty": e["qty"],
                 "safety": e["safety"], "price_usdc": economy._sku_price(sku)}
                for sku, e in inventory.items()
            ],
        })
    return {"stores": stores}


@router.get("/wallet")
def wallet() -> dict:
    """손님 지갑 — 구매 대금이 나가는 온체인 주머니. 조회 실패해도 진열대는 살아야 한다."""
    try:
        bal = payments.balance("guest")
        return {"address": bal["address"], "usdc": bal["usdc"]}
    except Exception:  # noqa: BLE001
        return {"address": None, "usdc": None}


class Purchase(BaseModel):
    store_id: str
    sku: str
    qty: int = Field(default=1, ge=1, le=3)  # 방문자 1회 구매는 소량 — 진열대 보호


@router.post("/purchase")
def purchase(body: Purchase) -> dict:
    if body.store_id not in fixtures.load()["stores"]:
        raise HTTPException(404, f"없는 지점: {body.store_id}")

    result = economy.sell(body.store_id, body.sku, body.qty, "손님 구매 (라이브)")
    if result.get("error"):
        raise HTTPException(409, result["error"])

    # 손님 지갑 → 본사 — 카드 매출이 밴사·본사를 거쳐 지점에 정산되는 실제 구조.
    # 금고 적립(sell)→카드정산 지급은 그대로 두고, 유입만 실돈이 된다.
    # 결제가 막혀도(지갑 고갈·RPC) 판매 기록은 이미 남았다 — 데모가 멈추지 않는다.
    amount = round(economy._sku_price(body.sku) * body.qty, 2)
    tx = None
    try:
        receipt = payments.pay(
            "guest", payments.balance("hq")["address"], amount,
            f"SHOP-{body.store_id}-{body.sku}",
        )
        tx = receipt.get("signature")
    except Exception as exc:  # noqa: BLE001 — 결제 실패는 기록하고 계속
        utils.log("guest", "shop.pay_failed",
                  {"store_id": body.store_id, "sku": body.sku,
                   "amount_usdc": amount, "reason": str(exc)[:120]})
    if tx:
        utils.log("guest", "shop.sale",
                  {"store_id": body.store_id, "sku": body.sku, "qty": body.qty,
                   "amount_usdc": amount, "tx": tx})
        stats.add_guest_flow(amount)

    entry = utils.effective_inventory(body.store_id).get(body.sku, {})
    low = entry.get("qty", 0) < entry.get("safety", 0)
    return {
        **result,
        "paid_usdc": amount if tx else None,
        "tx": tx,
        "network": config.NETWORK,
        "low_stock": low,
        "next": (
            "재고가 안전선 아래로 내려갔습니다 — 다음 틱(10분 내)에 에이전트가 "
            "조달을 시작합니다. 대시보드 실행 로그에서 지켜보세요."
            if low else
            "매출이 적립됐습니다 — 다음 카드정산 틱에 온체인으로 지급됩니다."
        ),
    }
