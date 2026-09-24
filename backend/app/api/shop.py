"""손님 구매 API — 방문자(심사위원 포함)가 라이브 경제에 수요를 넣는 창구.

구매는 지점의 재고 원장에 판매로 기록되고 매출은 금고에 적립된다 —
틱의 시뮬 판매와 정확히 같은 경로(economy.sell). 재고가 안전선을 깨면
**그 자리에서** 지점 에이전트의 조달(P2P/본사 발주)을 태운다 — 응답을 보낸 뒤
작업 스레드에서, 틱과 같은 잠금 아래. 방문자는 구경꾼이 아니라 이 경제의 트리거다.
스케줄러 틱은 그래도 돈다: 사람이 없는 시간의 배경 수요와, 구매가 놓친 지점을 맡는다.
"""

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from app import config
from app.agents import utils
from app.api import guard
from app.core import economy, fixtures, kst, menu, stats
from app.db import store as db
from app.solana import payments

router = APIRouter(prefix="/api/shop", tags=["shop"])


@router.get("")
def shelves() -> dict:
    """지점과 판매 품목(현재고·가격) — 예전 진열대(재료 단위). 메뉴판은 /api/shop/menu."""
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


def _visitor(request: Request) -> str:
    """방문자 표식 — IP 원문은 남기지 않는다. 소금 친 해시 앞 12자로 고유 방문자만 센다."""
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "?")
    return hashlib.sha256(f"{config.VISITOR_SALT}:{ip}".encode()).hexdigest()[:12]


def _procure_now(store_id: str, sku: str, ref: str | None = None) -> None:
    """손님 구매가 깨뜨린 안전선을 그 자리에서 메운다 — 응답을 보낸 뒤 작업 스레드에서.

    틱 잠금은 구매 핸들러가 잡아서 넘겨준다. 어떤 실패도 손님의 영수증에는 영향이
    없고, 잠금은 반드시 되돌린다 — 안 그러면 다음 틱이 TTL(9분)을 기다린다.
    ref는 손님 주문번호 — 로그와 납품 문서에 남아 주문 추적 화면이 이걸로 찾는다.
    """
    tag = {"store_id": store_id, "sku": sku, **({"order_id": ref} if ref else {})}
    try:
        action = asyncio.run(economy.procure_store(store_id, trigger="shop", trigger_ref=ref)) \
            or {"route": "none"}
        # procure_store는 실패를 삼켜 route="error"로 돌려준다 — 화면은 그걸 완료로 읽으면 안 된다
        done = "shop.procure_failed" if action.get("route") == "error" else "shop.procured"
        utils.log("system", done, {**tag, **action})
    except Exception as exc:  # noqa: BLE001 — 조달 실패는 기록만, 손님과 무관
        utils.log("system", "shop.procure_failed", {**tag, "reason": str(exc)[:160]})
    finally:
        economy.release_tick_lock()


def _maybe_trigger(background: BackgroundTasks, store_id: str, sku: str | None,
                   low: bool, ref: str | None = None) -> str | None:
    """안전선이 깨졌으면 다음 틱을 기다리지 않는다 — 방문자가 누른 버튼이 곧 트리거다.

    틱이 도는 중이면 양보한다: 그 틱의 조달 단계가 이 지점을 곧 처리하고, 겹치면 경합이다.
    돌려주는 값: started · tick_running · None(안전선 위거나 꺼져 있음).
    """
    if not (low and config.SHOP_TRIGGER_ENABLED and config.TICK_ENABLED):
        return None
    if economy.acquire_tick_lock() is None:
        background.add_task(_procure_now, store_id, sku, ref)
        mode = "started"
    else:
        mode = "tick_running"
    utils.log("guest", "shop.trigger",
              {"store_id": store_id, "sku": sku, "mode": mode, **({"order_id": ref} if ref else {})})
    return mode


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

    result = economy.sell(body.store_id, body.sku, body.qty, economy.LIVE_NOTE)
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
                   "amount_usdc": amount, "tx": tx, "visitor": _visitor(request)})
        stats.add_guest_flow(body.store_id, amount)

    entry = utils.effective_inventory(body.store_id).get(body.sku, {})
    low = entry.get("qty", 0) < entry.get("safety", 0)

    trigger = _maybe_trigger(background, body.store_id, body.sku, low)
    return {
        **result,
        "paid_usdc": amount if tx else None,
        "tx": tx,
        "network": config.NETWORK,
        "low_stock": low,
        "trigger": trigger,
        "next": _next_text(low, trigger),
    }


# ── SFC 메뉴 주문 — 손님은 요리를 주문하고, 레시피가 재료로 풀려 재고에서 빠진다 ──
# 주문 1건 = 온체인 이체 1건(메모 = 주문번호). 결제가 곧 주문 기록이다.
# 배달·조리 상태를 지어내지 않는다 — 보여주는 건 결제(tx)·빠진 재료·에이전트의 반응, 전부 실제 기록.

@router.get("/menu")
def menu_board() -> dict:
    """브랜드 + 지점별 메뉴판 — 손님 페이지의 첫 화면. 값·지금 가능한 인분·레시피."""
    stores = [{"id": sid, "name": p["name"], "items": menu.items_for(sid)}
              for sid, p in fixtures.load()["stores"].items()]
    return {"brand": menu.brand(), "stores": stores, "max_servings": menu.MAX_SERVINGS_PER_ORDER}


class OrderLine(BaseModel):
    item_id: str
    qty: int = Field(default=1, ge=1, le=menu.MAX_SERVINGS_PER_ORDER)


class Order(BaseModel):
    store_id: str
    items: list[OrderLine] = Field(min_length=1, max_length=8)
    # demo: 프로젝트가 채운 공용 손님 지갑이 대신 낸다 (지갑 없는 방문자용)
    # wallet: 방문자가 자기 Phantom 지갑으로 직접 서명해 낸다 — 이게 진짜 사용자 결제다
    pay: str = Field(default="demo", pattern="^(demo|wallet)$")
    wallet: str | None = Field(default=None, min_length=32, max_length=44)


class Confirm(BaseModel):
    signature: str = Field(min_length=64, max_length=100)


def _order_id(store_id: str) -> str:
    """ORD-0922-B7f3a — 날짜·지점 머리글자는 청구서·납품 번호와 같은 문법, 뒤는 무작위."""
    initial = store_id.rsplit("-", 1)[-1][:1].upper()
    while True:
        oid = f"ORD-{kst.mmdd()}-{initial}{secrets.token_hex(2)}"
        if not db.get("customer_orders", oid):
            return oid


def _quote(need: dict[str, int]) -> float:
    """손님이 낼 돈 — economy.sell이 금고에 적립하는 식과 똑같이 재료별로 반올림해 더한다."""
    return round(sum(round(n * economy._sku_price(sku) * economy.RETAIL_MARGIN, 2)
                     for sku, n in need.items()), 2)


def _fulfil(order_id: str, store_id: str, need: dict[str, int], background: BackgroundTasks) -> tuple[dict, list]:
    """결제가 된(또는 데모 결제를 시도한) 주문의 재료를 판매로 기록하고 안전선을 본다.

    틱의 시뮬 판매·1개 구매와 정확히 같은 경로(economy.sell). 안전선이 깨지면 즉시 조달.
    """
    note = f"{economy.LIVE_NOTE} {order_id}"
    drawn = {}
    for sku, n in need.items():
        result = economy.sell(store_id, sku, n, note)
        if result.get("error"):
            raise HTTPException(409, result["error"])
        drawn[sku] = result["qty"]
    inv = utils.effective_inventory(store_id)
    low = [sku for sku in need
           if inv.get(sku, {}).get("qty", 0) < inv.get(sku, {}).get("safety", 0)]
    trigger = _maybe_trigger(background, store_id, low[0] if low else None, bool(low), ref=order_id)
    return {"ingredients": drawn, "low_stock": low, "trigger": trigger}, low


def _log_order(doc: dict, order_id: str) -> None:
    utils.log("guest", "shop.order", {
        "store_id": doc["store_id"], "order_id": order_id,
        "items": [f"{line['name']} x{line['qty']}" for line in doc["lines"]],
        "amount_usdc": doc["total_usdc"], "tx": doc.get("tx"),
        "low_stock": doc.get("low_stock"), "trigger": doc.get("trigger"),
        "visitor": doc.get("visitor"), "payer": doc.get("payer", "demo"),
        **({"wallet": doc["wallet"]} if doc.get("wallet") else {}),
    })


@router.post("/order")
def place_order(body: Order, request: Request, background: BackgroundTasks) -> dict:
    guard.rate_limit(request, "shop")
    stores = fixtures.load()["stores"]
    if body.store_id not in stores:
        raise HTTPException(404, f"없는 지점: {body.store_id}")
    try:
        lines, need = menu.expand(body.store_id, [line.model_dump() for line in body.items])
    except menu.OrderError as exc:
        raise HTTPException(409, str(exc)) from None

    order_id = _order_id(body.store_id)
    total = _quote(need)
    base = {
        "store_id": body.store_id, "store_name": stores[body.store_id]["name"],
        "lines": lines, "need": need, "total_usdc": total, "network": config.NETWORK,
        "visitor": _visitor(request), "created_at": datetime.now(UTC).isoformat(),
    }

    if body.pay == "wallet":
        # 방문자 지갑 결제 — 여기서는 청구만 한다. 재고는 체인에서 결제를 확인한 뒤에 뺀다.
        if not body.wallet:
            raise HTTPException(422, "wallet address is required to pay with your own wallet")
        doc = db.put("customer_orders", order_id, {
            **base, "payer": "own_wallet", "wallet": body.wallet,
            "status": "awaiting_payment", "paid_usdc": None, "tx": None,
        })
        return {**doc, "id": order_id, "payment": {
            "network": config.NETWORK, "mint": config.USDC_MINT, "decimals": 6,
            "recipient": config.HQ_ADDRESS, "recipient_token_account": config.HQ_USDC_ATA,
            "amount_usdc": total, "amount_base_units": round(total * 1_000_000), "memo": order_id,
        }}

    # 데모 지갑 결제 — 프로젝트가 채운 공용 손님 지갑이 대신 낸다
    tx = None
    try:
        receipt = payments.pay("guest", payments.balance("hq")["address"], total, order_id)
        tx = receipt.get("signature")
    except Exception as exc:  # noqa: BLE001 — 결제 실패는 기록하고 계속, 판매 기록은 남긴다
        utils.log("guest", "shop.pay_failed",
                  {"store_id": body.store_id, "order_id": order_id,
                   "amount_usdc": total, "reason": str(exc)[:120]})
    if tx:
        stats.add_guest_flow(body.store_id, total)
    effects, _ = _fulfil(order_id, body.store_id, need, background)
    doc = db.put("customer_orders", order_id, {
        **base, **effects, "payer": "demo",
        "paid_usdc": total if tx else None, "tx": tx,
        "status": "paid" if tx else "pay_failed",
    })
    _log_order(doc, order_id)
    return {**doc, "id": order_id}


def _verify_wallet_payment(doc: dict, order_id: str, signature: str) -> dict | None:
    """체인에서 방문자의 이체를 대조한다 — 프런트가 보낸 값은 믿지 않는다.

    성공·수취 계좌(본사 USDC)·금액·메모(주문번호)·수수료 낸 지갑(=방문자, 서명자) 다섯 가지.
    아직 체인에 안 보이면 None (잠시 뒤 다시).
    """
    try:
        tx = payments.verify_tx(signature)
    except Exception:  # noqa: BLE001 — 404(아직 전파 전)·일시 오류는 "아직"으로 본다
        return None
    if not tx.get("found"):
        return None
    t = tx.get("transfer") or {}
    problems = []
    if not tx.get("success"):
        problems.append("the transaction failed on-chain")
    if t.get("destination") != config.HQ_USDC_ATA:
        problems.append("it was not sent to the franchise HQ's USDC account")
    if abs(float(t.get("amount") or 0) - doc["total_usdc"]) > 0.000001:
        problems.append(f"amount {t.get('amount')} USDC does not match {doc['total_usdc']} USDC")
    if (tx.get("memo") or "").strip() != order_id and order_id not in (tx.get("memo") or ""):
        problems.append("the memo does not carry this order number")
    if tx.get("feePayer") != doc.get("wallet"):
        problems.append("it was not signed and paid by the wallet that placed the order")
    return {"ok": not problems, "problems": problems, "tx": tx}


@router.post("/orders/{order_id}/confirm")
def confirm_wallet_order(order_id: str, body: Confirm, request: Request,
                         background: BackgroundTasks) -> dict:
    """방문자 지갑 결제 확인 — 서명이 체인에서 확인되면 그때 재료를 판매로 기록한다."""
    guard.rate_limit(request, "shop")
    doc = db.get("customer_orders", order_id)
    if not doc or doc.get("payer") != "own_wallet":
        raise HTTPException(404, f"no such wallet order: {order_id}")
    if doc.get("status") == "paid":
        return {**doc, "id": order_id}  # 같은 확인이 두 번 와도 한 번만 판다
    # 이미 다른 주문의 결제로 인정된 트랜잭션은 다시 못 쓴다 (거절된 시도는 세지 않는다)
    used = db.list_docs("customer_orders", tx=body.signature)
    if any(o.get("id") != order_id and o.get("status") == "paid" for o in used):
        raise HTTPException(409, "this transaction already paid for another order")

    check = _verify_wallet_payment(doc, order_id, body.signature)
    if check is None:
        raise HTTPException(425, "transaction not visible on-chain yet — retry in a few seconds")
    if not check["ok"]:
        db.update("customer_orders", order_id, {"status": "payment_rejected",
                                                "rejected_tx": body.signature, "problems": check["problems"]})
        utils.log("guest", "shop.pay_failed", {"store_id": doc["store_id"], "order_id": order_id,
                                               "reason": "; ".join(check["problems"])[:160]})
        raise HTTPException(409, "payment did not check out: " + "; ".join(check["problems"]))

    effects, _ = _fulfil(order_id, doc["store_id"], doc["need"], background)
    stats.add_guest_flow(doc["store_id"], doc["total_usdc"])
    doc = db.put("customer_orders", order_id, {
        **doc, **effects, "status": "paid", "paid_usdc": doc["total_usdc"], "tx": body.signature,
        "confirmed_at": datetime.now(UTC).isoformat(),
    })
    _log_order(doc, order_id)
    return {**doc, "id": order_id}


@router.get("/orders/{order_id}")
def order_status(order_id: str) -> dict:
    """주문 한 건의 자취 — 결제(tx)·빠진 재료·에이전트가 어떻게 반응했나. 전부 실제 기록."""
    doc = db.get("customer_orders", order_id)
    if not doc:
        raise HTTPException(404, f"no such order: {order_id}")
    # 그날 기록만 읽는다 — 전체 이벤트를 훑으면 라이브(수십만 건)에서 폴링마다 느려진다
    day = kst.day_of(doc.get("created_at") or doc.get("updated_at") or "")
    agent = [e for e in db.recent_events(400, day=day)
             if (e.get("payload") or {}).get("order_id") == order_id
             and e["action"] in ("shop.trigger", "shop.procured", "shop.procure_failed")]
    agent.sort(key=lambda e: e["ts"])
    return {**doc, "id": order_id, "agent": agent}
