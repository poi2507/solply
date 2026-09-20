"""손님 구매 API — 방문자(심사위원 포함)가 라이브 경제에 수요를 넣는 창구.

구매는 지점의 재고 원장에 판매로 기록되고 매출은 금고에 적립된다 —
틱의 시뮬 판매와 정확히 같은 경로(economy.sell). 재고가 안전선을 깨면
**그 자리에서** 지점 에이전트의 조달(P2P/본사 발주)을 태운다 — 응답을 보낸 뒤
작업 스레드에서, 틱과 같은 잠금 아래. 방문자는 구경꾼이 아니라 이 경제의 트리거다.
스케줄러 틱은 그래도 돈다: 사람이 없는 시간의 배경 수요와, 구매가 놓친 지점을 맡는다.
"""

import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from app import config
from app.agents import utils
from app.api import guard
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
                # 진열대는 소비자 가격 — 공급가에 요리 마진(1.35)이 붙는다
                {"sku": sku, "name": e.get("name", sku), "qty": e["qty"],
                 "safety": e["safety"],
                 "price_usdc": round(economy._sku_price(sku) * economy.RETAIL_MARGIN, 2)}
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


def _procure_now(store_id: str, sku: str) -> None:
    """손님 구매가 깨뜨린 안전선을 그 자리에서 메운다 — 응답을 보낸 뒤 작업 스레드에서.

    틱 잠금은 구매 핸들러가 잡아서 넘겨준다. 어떤 실패도 손님의 영수증에는 영향이
    없고, 잠금은 반드시 되돌린다 — 안 그러면 다음 틱이 TTL(9분)을 기다린다.
    """
    try:
        action = asyncio.run(economy.procure_store(store_id, trigger="shop")) or {"route": "none"}
        # procure_store는 실패를 삼켜 route="error"로 돌려준다 — 화면은 그걸 완료로 읽으면 안 된다
        done = "shop.procure_failed" if action.get("route") == "error" else "shop.procured"
        utils.log("system", done, {"store_id": store_id, "sku": sku, **action})
    except Exception as exc:  # noqa: BLE001 — 조달 실패는 기록만, 손님과 무관
        utils.log("system", "shop.procure_failed",
                  {"store_id": store_id, "sku": sku, "reason": str(exc)[:160]})
    finally:
        economy.release_tick_lock()


def _next_text(low: bool, trigger: str | None) -> str:
    if not low:
        return "매출이 적립됐습니다 — 다음 카드정산 틱에 온체인으로 지급됩니다."
    if trigger == "started":
        return "재고가 안전선 아래로 내려갔습니다 — 지점 에이전트가 지금 조달을 시작합니다."
    if trigger == "tick_running":
        return "재고가 안전선 아래로 내려갔습니다 — 지금 도는 틱이 곧 이 지점의 조달을 처리합니다."
    return "재고가 안전선 아래로 내려갔습니다 — 다음 틱(10분 내)에 에이전트가 조달을 시작합니다."


@router.post("/purchase")
def purchase(body: Purchase, request: Request, background: BackgroundTasks) -> dict:
    # 남용 감속이 맨 앞이다 — 무거운 일(온체인 결제) 전에 끊어야 의미가 있다
    guard.rate_limit(request, "shop")
    if body.store_id not in fixtures.load()["stores"]:
        raise HTTPException(404, f"없는 지점: {body.store_id}")

    result = economy.sell(body.store_id, body.sku, body.qty, "손님 구매 (라이브)")
    if result.get("error"):
        raise HTTPException(409, result["error"])

    # 손님 지갑 → 본사 — 카드 매출이 밴사·본사를 거쳐 지점에 정산되는 실제 구조.
    # 청구액 = 금고 적립액(소비자 가격, 마진 포함) — 다르면 본사 장부가 어긋난다 (8/12 팀장 발견).
    # 결제가 막혀도(지갑 고갈·RPC) 판매 기록은 이미 남았다 — 데모가 멈추지 않는다.
    amount = result["revenue"]
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
        stats.add_guest_flow(body.store_id, amount)

    entry = utils.effective_inventory(body.store_id).get(body.sku, {})
    low = entry.get("qty", 0) < entry.get("safety", 0)

    # 안전선이 깨졌으면 다음 틱을 기다리지 않는다 — 방문자가 누른 버튼이 곧 트리거다.
    # 틱이 도는 중이면 양보한다: 그 틱의 조달 단계가 이 지점을 곧 처리하고, 겹치면 경합이다.
    trigger = None
    if low and config.SHOP_TRIGGER_ENABLED and config.TICK_ENABLED:
        if economy.acquire_tick_lock() is None:
            background.add_task(_procure_now, body.store_id, body.sku)
            trigger = "started"
        else:
            trigger = "tick_running"
        utils.log("guest", "shop.trigger",
                  {"store_id": body.store_id, "sku": body.sku, "mode": trigger})
    return {
        **result,
        "paid_usdc": amount if tx else None,
        "tx": tx,
        "network": config.NETWORK,
        "low_stock": low,
        "trigger": trigger,
        "next": _next_text(low, trigger),
    }
