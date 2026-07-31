"""라이브 경제 루프 — 판매·정산·발주·재입고가 스스로 도는 틱.

라이브 URL이 "과거 데모의 기록"이 아니라 "지금 거래 중인 시스템"이 되도록,
스케줄러(Cloud Scheduler → POST /api/ticks/run)가 주기적으로 이 틱을 굴린다.

원칙 두 가지:
  1) 발주 버튼은 없다 — 사건(재고 미달)이 트리거고, 사람은 경계에서만.
     조달 판단(P2P vs 본사 발주)은 기존 에이전트 그래프를 그대로 태운다.
  2) 온체인 총량 보존 — 손님·외부 공급사는 체인 밖 존재라, 소매가 = 공급가로
     두고(마진은 표시 계층 몫) 카드정산(hq→지점)과 물대(지점→hq)가 순환한다.
     외부로 돈이 새는 단계(본사 재입고)는 원장 기록만 남긴다.

틱 한 번의 순서: 판매 → 카드정산 지급 → 지점 조달(P2P/발주→청구→x402 정산)
→ 본사 창고 재입고 → 예약 납부 실행. 각 단계가 남긴 것을 요약으로 돌려준다.
"""

import random

from app.agents import runner, utils
from app.core import fixtures, kst
from app.core import policy as policy_mod
from app.core import status as status_mod
from app.db import store as db
from app.solana import payments

TILL = "till"  # 지점별 적립 매출 (카드 매출 — 다음 정산 때 지급)


# ── 공용 헬퍼 ─────────────────────────────────────────────────────────

def ensure_funds(store_id: str, invoice_amount: float) -> float:
    """'청구액 + 운영 하한'까지만 채우는 카드정산 입금 (데모·리허설용 시간 당김).

    demo.py가 쓰던 로직의 공용화 — 반복해도 잔액이 불어나지 않는 자기 유지 금액.
    """
    balance = payments.balance(store_id)
    reserve = policy_mod.get(store_id).min_reserve_usdc
    needed = round(max(0.0, invoice_amount + reserve - balance["usdc"]), 2)
    if needed > 0:
        payments.pay("hq", balance["address"], needed, "CARD-SETTLEMENT")
    return needed


def _sku_price(sku: str) -> float:
    """품목 공급 단가 — 본사 발주 조건에 없으면 시드 납품에서 찾는다."""
    terms = utils.hq_reorder_terms(sku)
    if terms.get("unit_price_usdc"):
        return float(terms["unit_price_usdc"])
    for delivery in fixtures.load()["deliveries"].values():
        for item in delivery["items"]:
            if item["sku"] == sku:
                return float(item["unit_price_usdc"])
    return 1.0


def _delivery_id(store_id: str) -> str:
    day = kst.mmdd()
    initial = store_id.rsplit("-", 1)[-1][:1].upper()
    seq = len(db.list_docs("deliveries", store_id=store_id)) + 1
    while db.get("deliveries", f"DEL-{day}-{initial}{seq:02d}"):
        seq += 1
    return f"DEL-{day}-{initial}{seq:02d}"


# ── 1. 판매 — 손님이 다녀간다 ────────────────────────────────────────

def sell(store_id: str, sku: str, qty: int, note: str) -> dict:
    """판매 한 건 — 재고 원장에 기록하고 매출을 금고(till)에 적립한다.

    틱의 시뮬 판매와 /shop의 실제 방문자 구매가 같은 경로를 지난다.
    손님 결제는 체인 밖(카드) — 온체인은 카드정산 틱에서 일어난다.
    """
    from app.agents.store import tools as store_tools

    result = store_tools.record_sales(store_id, sku, qty, note)
    if result.get("error"):
        return result
    revenue = round(result["sold"] * _sku_price(sku), 2)  # 소매가 = 공급가 (총량 보존)
    till = db.get(TILL, store_id) or {"accrued_usdc": 0.0}
    db.put(TILL, store_id, {"accrued_usdc": round(till["accrued_usdc"] + revenue, 2)})
    return {"store_id": store_id, "sku": sku, "qty": result["sold"],
            "remaining": result["remaining"], "revenue": revenue}


def run_sales(rng: random.Random) -> list[dict]:
    """지점마다 보유 재고 한도 내에서 몇 개 판매한다 (시뮬 수요)."""
    sold = []
    for store_id in fixtures.load()["stores"]:
        for sku, entry in utils.effective_inventory(store_id).items():
            if entry["qty"] <= 0:
                continue
            qty = min(entry["qty"], rng.randint(0, 2))
            if qty <= 0:
                continue
            result = sell(store_id, sku, qty, "영업 판매")
            if not result.get("error"):
                sold.append(result)
    return sold


# ── 2. 카드정산 — 적립 매출이 온체인으로 지급된다 ─────────────────────

def settle_cards() -> list[dict]:
    """금고에 쌓인 매출을 hq(카드 매입 대행 역할)가 지점에 온체인으로 지급한다."""
    paid = []
    hq_balance = payments.balance("hq")
    available = hq_balance["usdc"] - 5.0  # hq 운영 예비
    for store_id in fixtures.load()["stores"]:
        till = db.get(TILL, store_id)
        amount = round((till or {}).get("accrued_usdc", 0.0), 2)
        if amount <= 0 or amount > available:
            continue
        address = payments.balance(store_id)["address"]
        result = payments.pay("hq", address, amount, "CARD-SETTLEMENT")
        db.put(TILL, store_id, {"accrued_usdc": 0.0})
        available -= amount
        utils.log(
            "hq-agent", "card.settled",
            {"store_id": store_id, "amount_usdc": amount, "tx": result["signature"]},
        )
        paid.append({"store_id": store_id, "amount_usdc": amount})
    return paid


# ── 3. 조달 — 재고 미달이 발주를 시작한다 (Agent-Initiated) ───────────

async def _p2p_handshake(trade: dict) -> str:
    """제안된 직거래의 나머지 왕복 — 판매측 응답 → 본사 심사 → 결제 → 장부."""
    trade_id = trade["id"]
    responded = await runner.run(
        "store", "p2p.respond", store_id=trade["seller_id"], trade_id=trade_id
    )
    if (responded.get("trade") or {}).get("status") != status_mod.TradeStatus.ACCEPTED:
        return "rejected_by_seller"
    await runner.run("hq", "p2p.review", trade_id=trade_id)
    if (db.get("p2p_trades", trade_id) or {}).get("status") != status_mod.TradeStatus.APPROVED:
        return "rejected_by_hq"
    paid = await runner.run(
        "store", "p2p.pay", store_id=trade["buyer_id"], trade_id=trade_id
    )
    if paid.get("outcome") == "paid":
        await runner.run("hq", "p2p.record", trade_id=trade_id)
        return "confirmed"
    return "payment_failed"


def _fulfill_order(store_id: str, sku: str, need: int) -> str | None:
    """본사 이행 — 주문 수량만큼 납품 문서를 만들고 청구서를 발행한다."""
    terms = utils.hq_reorder_terms(sku)
    order_qty = max(need, int(terms.get("min_qty", 1)))
    hq_stock = utils.effective_inventory("hq").get(sku, {}).get("qty", 0)
    ship_qty = min(order_qty, max(0, hq_stock))
    if ship_qty <= 0:
        return None

    name = utils.effective_inventory("hq").get(sku, {}).get("name", sku)
    delivery = db.put(
        "deliveries",
        _delivery_id(store_id),
        {
            "store_id": store_id,
            "items": [{"sku": sku, "name": name, "qty": ship_qty,
                       "unit_price_usdc": _sku_price(sku)}],
            "received": {sku: ship_qty},  # 루프 납품은 검수 일치가 기본
            "source": "economy-tick",
        },
    )
    from app.agents.hq import tools as hq_tools

    invoice = hq_tools.create_invoice(delivery["id"])
    return None if invoice.get("error") else invoice["id"]


async def run_procurement() -> list[dict]:
    """지점마다 재고를 점검하고, 미달이면 조달 그래프(P2P vs 본사 발주)를 태운다."""
    actions = []
    for store_id in fixtures.load()["stores"]:
        shortages = utils.stock_shortages(utils.effective_inventory(store_id))
        if not shortages:
            continue

        # 조달 판단은 에이전트의 몫 — P2P가 유리하면 직거래를 제안한다
        result = await runner.run("store", "restock.check", store_id=store_id)
        trade = result.get("trade")
        if trade:
            status = await _p2p_handshake(trade)
            actions.append({"store_id": store_id, "route": "p2p", "status": status})
            continue

        # 잉여 지점이 없으면 본사 발주 — 납품·청구 생성 후 기존 x402 정산 플로우
        shortage = shortages[0]
        invoice_id = _fulfill_order(store_id, shortage["sku"], shortage["need"])
        if not invoice_id:
            actions.append({"store_id": store_id, "route": "hq_order", "status": "hq_out_of_stock"})
            continue
        handled = await runner.run(
            "store", "invoice.handle", store_id=store_id, invoice_id=invoice_id
        )
        outcome = handled.get("outcome")
        if outcome == "negotiating":  # 잔액 부족 → 유예 제안 → 본사 심사 한 홉
            proposal = runner.latest_event(db.list_events(), "proposal.deferral")
            if proposal and proposal.get("invoice_id") == invoice_id:
                await runner.run("hq", "proposal.deferral", invoice_id=invoice_id, payload=proposal)
                outcome = "deferred"
        actions.append({"store_id": store_id, "route": "hq_order",
                        "invoice_id": invoice_id, "status": outcome})
    return actions


# ── 4. 본사 재입고 — 창고가 비면 채운다 ──────────────────────────────

def restock_hq() -> list[dict]:
    """본사 창고가 안전선 미달이면 재입고를 원장에 기록한다.

    외부 공급사는 체인 밖 존재라 온체인 이체는 없다 — 이체하면 생태계 총량이
    깨진다. 매입 지출은 이벤트로 남겨 리포트가 집계한다.
    """
    restocked = []
    for sku, entry in utils.effective_inventory("hq").items():
        if entry["qty"] >= entry["safety"]:
            continue
        batch = max(entry["safety"] * 2 - entry["qty"], 1)
        utils.record_move("hq", sku, entry.get("name", sku), batch, "restocked", "SUPPLIER")
        utils.log(
            "hq-agent", "warehouse.restocked",
            {"sku": sku, "qty": batch, "cost_usdc": round(batch * _sku_price(sku), 2)},
        )
        restocked.append({"sku": sku, "qty": batch})
    return restocked


# ── 5. 예약 납부 — 예약일이 온 건을 실행한다 ─────────────────────────

async def run_scheduled_payments() -> list[dict]:
    """예약 상태의 청구서를 결제 시도한다.

    잔액이 아직 안 모였으면 건드리지 않는다 — 시도하면 매 틱 유예 제안이
    쌓이기만 한다. 카드정산이 잔액을 채우면 그때 자연스럽게 실행된다.
    """
    executed = []
    for invoice in list(db.list_docs("invoices")):
        if invoice["status"] != "scheduled":
            continue
        balance = payments.balance(invoice["store_id"])
        reserve = policy_mod.get(invoice["store_id"]).min_reserve_usdc
        if balance["usdc"] < invoice["amount_usdc"] + reserve:
            executed.append({"invoice_id": invoice["id"], "outcome": "waiting_funds"})
            continue
        final = await runner.run(
            "store", "invoice.pay_scheduled",
            store_id=invoice["store_id"], invoice_id=invoice["id"],
        )
        executed.append({"invoice_id": invoice["id"], "outcome": final.get("outcome")})
    return executed


# ── 틱 — 다섯 단계를 한 바퀴 ─────────────────────────────────────────

async def tick(rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    summary = {
        "sales": run_sales(rng),
        "card_settlements": settle_cards(),
        "procurement": await run_procurement(),
        "hq_restocked": restock_hq(),
        "scheduled_runs": await run_scheduled_payments(),
    }
    utils.log(
        "system", "tick.completed",
        {k: len(v) for k, v in summary.items()},
    )
    return summary
