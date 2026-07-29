"""손님 구매 API — 방문자(심사위원 포함)가 라이브 경제에 수요를 넣는 창구.

구매는 지점의 재고 원장에 판매로 기록되고 매출은 금고에 적립된다 —
틱의 시뮬 판매와 정확히 같은 경로(economy.sell). 재고가 안전선을 깨면
다음 틱에서 에이전트가 조달(P2P/본사 발주)을 스스로 시작한다.
방문자는 구경꾼이 아니라 이 경제의 수요가 된다.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents import utils
from app.core import economy, fixtures

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

    entry = utils.effective_inventory(body.store_id).get(body.sku, {})
    low = entry.get("qty", 0) < entry.get("safety", 0)
    return {
        **result,
        "low_stock": low,
        "next": (
            "재고가 안전선 아래로 내려갔습니다 — 다음 틱(10분 내)에 에이전트가 "
            "조달을 시작합니다. 대시보드 실행 로그에서 지켜보세요."
            if low else
            "매출이 적립됐습니다 — 다음 카드정산 틱에 온체인으로 지급됩니다."
        ),
    }
