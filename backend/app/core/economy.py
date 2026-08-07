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

# 요리 마진 — 지점은 식자재(공급가)로 요리를 만들어 더 받고 판다.
# 이게 1.0이면 지점의 장기 순현금흐름이 정확히 0이라, 타이밍 어긋남·데모 리셋 같은
# 마찰 손실만 남아 지점 돈이 본사로 서서히 빨려간다 (8/6에 실제로 겪음 — 본사가
# 총량의 80%를 들고 있었다). 카드정산이 본사 가용액 안에서만 지급되므로(부분 지급)
# 마진을 줘도 온체인 총량은 깨지지 않는다 — 본사가 쌓아둔 돈이 지점으로 흘러내려
# 본사는 유통(flow-through) 계층이 된다.
RETAIL_MARGIN = 1.35

# 예약·미결 청구서 상환은 틱마다 지점당 이 개수까지만 시도한다.
# 전수 시도하면 백로그가 클 때 틱 하나가 수백 번의 온체인 조회로 수 분씩 걸린다
# (8/6: 예약 311건 전수조사로 틱이 60~350초, 대부분 도중 사망).
PAYDOWN_PER_STORE = 2

# 결제가 막힌 청구서(발행·협의 — 아직 납부 방법이 정해지지 않은 것)가 이만큼 쌓인
# 지점은 새 발주를 멈춘다. 주문만 반복하면 부채와 틱 부하가 같이 폭주한다.
#
# 예약(scheduled)은 세지 않는다 — 납부일을 이미 합의한 건이라 "막힌" 상태가 아니고,
# 여기에 포함하면 분할 합의가 쌓인 지점이 영구히 발주를 못 한다
# (8/7 라이브: 미결 210건 중 184건이 예약이라 세 지점 전부 발주 정지 →
#  데모가 3시간마다 넣어주는 냉장 닭만 남고 나머지 품목 재고가 전부 0이 됐다).
MAX_STUCK_INVOICES = 3

# 그래도 전체 미결이 이 선을 넘으면 멈춘다 — 폭주에 대한 회로 차단기다
# (평시엔 닿지 않는 값. 8/6 사고 때 하루 700건이 쌓였다).
MAX_OPEN_INVOICES = 200

# 발주는 안전재고까지가 아니라 그 배수까지 채운다. 딱 안전재고로 맞추면 판매 한 번에
# 다시 미달이라 매 틱 발주가 나가 청구서가 무의미하게 불어난다.
REORDER_TO_SAFETY_X = 2


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
    revenue = round(result["sold"] * _sku_price(sku) * RETAIL_MARGIN, 2)
    till = db.get(TILL, store_id) or {"accrued_usdc": 0.0}
    db.put(TILL, store_id, {"accrued_usdc": round(till["accrued_usdc"] + revenue, 2)})
    return {"store_id": store_id, "sku": sku, "qty": result["sold"],
            "remaining": result["remaining"], "revenue": revenue}


def run_sales(rng: random.Random) -> list[dict]:
    """지점마다 보유 재고 한도 내에서 몇 개 판매한다 (시뮬 수요).

    10분 틱 기준의 수요다 — 품목당 0~2개를 균등 추첨하면 하루 백 단위로 팔려
    발주·정산이 경제 규모(총 몇백 USDC)에 비해 폭주한다. 한산한 틱이 기본이고
    가끔 손님이 몰리는 정도로 둔다.
    """
    sold = []
    for store_id in fixtures.load()["stores"]:
        for sku, entry in utils.effective_inventory(store_id).items():
            if entry["qty"] <= 0:
                continue
            qty = min(entry["qty"], rng.choices((0, 1, 2), weights=(60, 32, 8))[0])
            if qty <= 0:
                continue
            result = sell(store_id, sku, qty, "영업 판매")
            if not result.get("error"):
                sold.append(result)
    return sold


# ── 2. 카드정산 — 적립 매출이 온체인으로 지급된다 ─────────────────────

def settle_cards() -> list[dict]:
    """금고에 쌓인 매출을 hq(카드 매입 대행 역할)가 지점에 온체인으로 지급한다.

    본사 가용액 안에서 **부분 지급**한다 — 통째로 건너뛰면 금액이 큰 금고 하나가
    본사 잔액보다 커지는 순간 영원히 못 받는다. 지급 실패는 그 지점만 건너뛰고
    금고를 보존한다 (다음 틱에 재시도) — 한 결제의 일시 오류가 환류 전체를
    멈추면 지점 돈이 마르기 시작한다.
    """
    paid = []
    available = payments.balance("hq")["usdc"] - 5.0  # hq 운영 예비
    # 금고가 작은 지점부터 — 고정 순서로 돌면 가용액이 빠듯할 때 첫 지점(금고가 가장
    # 큰 a)이 매 틱 전액을 흡수해 나머지가 굶는다 (8/7 라이브: 카드정산 158.95가
    # 전부 a로만). 소액을 먼저 완납하면 모든 지점이 매 틱 환류를 받는다.
    def _accrued(store_id: str) -> float:
        return round((db.get(TILL, store_id) or {}).get("accrued_usdc", 0.0), 2)

    for store_id in sorted(fixtures.load()["stores"], key=_accrued):
        accrued = _accrued(store_id)
        amount = round(min(accrued, available), 2)
        if amount <= 0.01:
            continue
        try:
            address = payments.balance(store_id)["address"]
            result = payments.pay("hq", address, amount, "CARD-SETTLEMENT")
        except Exception as exc:  # noqa: BLE001 — 다음 틱이 재시도한다
            utils.log("hq-agent", "card.settle_failed",
                      {"store_id": store_id, "amount_usdc": amount, "reason": str(exc)[:160]})
            continue
        db.put(TILL, store_id, {"accrued_usdc": round(accrued - amount, 2)})
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

        # 결제가 막힌 지점은 발주를 멈춘다 (8/6: 하루 700건 발행 사고의 재발 방지).
        open_invoices = [inv for inv in db.list_docs("invoices", store_id=store_id)
                         if inv["status"] in status_mod.ACTIONABLE]
        stuck = sum(1 for inv in open_invoices
                    if inv["status"] != status_mod.InvoiceStatus.SCHEDULED)
        if stuck >= MAX_STUCK_INVOICES or len(open_invoices) >= MAX_OPEN_INVOICES:
            actions.append({"store_id": store_id, "route": "hold",
                            "status": f"stuck={stuck} open={len(open_invoices)}"})
            continue

        try:
            # 조달 판단은 에이전트의 몫 — P2P가 유리하면 직거래를 제안한다
            result = await runner.run("store", "restock.check", store_id=store_id)
            trade = result.get("trade")
            if trade:
                status = await _p2p_handshake(trade)
                actions.append({"store_id": store_id, "route": "p2p", "status": status})
                continue

            # 잉여 지점이 없으면 본사 발주 — 납품·청구 생성 후 기존 x402 정산 플로우
            shortage = shortages[0]
            need = shortage["need"] + shortage["safety"] * (REORDER_TO_SAFETY_X - 1)
            invoice_id = _fulfill_order(store_id, shortage["sku"], max(1, need))
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
        except Exception as exc:  # noqa: BLE001 — 한 지점의 실패가 다른 지점을 막지 않는다
            actions.append({"store_id": store_id, "route": "error", "status": str(exc)[:160]})
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
    """예약·미결 청구서를 오래된 것부터 상환한다 — 지점당 틱당 몇 건씩만.

    잔액 조회는 지점당 한 번이다. 청구서마다 조회하면 백로그가 클 때 틱 하나가
    수백 번의 온체인 왕복이 된다 (8/6: 311건 전수조사 → 틱 60~350초 → 도중 사망).
    잔액이 안 되는 지점은 이번 틱은 건너뛴다 — 카드정산이 채우면 다음 틱에 갚는다.
    """
    executed = []
    payable = {"scheduled": "invoice.pay_scheduled", "issued": "invoice.handle"}
    for store_id in fixtures.load()["stores"]:
        backlog = sorted(
            (inv for inv in db.list_docs("invoices", store_id=store_id)
             if inv["status"] in payable),
            key=lambda inv: inv.get("updated_at", ""),
        )
        if not backlog:
            continue
        try:
            wallet = payments.balance(store_id)["usdc"]
        except Exception as exc:  # noqa: BLE001 — 조회 실패면 이번 틱은 쉰다
            executed.append({"store_id": store_id, "outcome": "balance_check_failed",
                             "reason": str(exc)[:120]})
            continue
        reserve = policy_mod.get(store_id).min_reserve_usdc
        for invoice in backlog[:PAYDOWN_PER_STORE]:
            if wallet < invoice["amount_usdc"] + reserve:
                executed.append({"invoice_id": invoice["id"], "outcome": "waiting_funds"})
                break  # 오래된 것도 못 내면 뒤의 것도 못 낸다
            final = await runner.run(
                "store", payable[invoice["status"]],
                store_id=store_id, invoice_id=invoice["id"],
            )
            if final.get("outcome") == "paid":
                wallet -= invoice["amount_usdc"]
            executed.append({"invoice_id": invoice["id"], "outcome": final.get("outcome")})
    return executed


# ── 틱 — 다섯 단계를 한 바퀴 ─────────────────────────────────────────

async def tick(rng: random.Random | None = None) -> dict:
    """다섯 단계를 한 바퀴 — 단계는 서로 격리된다.

    devnet 결제는 가끔 실패한다. 격리하지 않으면 한 단계의 예외가 틱 전체를
    죽이고, 특히 뒤 단계(카드정산 이후)가 계속 굶어서 지점 돈이 마른다
    (8/6: 틱 대부분이 500으로 사망, card.settled 0건 — 그 사고의 재발 방지).
    """
    rng = rng or random.Random()

    async def _stage(fn):
        try:
            result = fn()
            return (await result) if hasattr(result, "__await__") else result
        except Exception as exc:  # noqa: BLE001 — 실패는 요약에 남기고 다음 단계로
            return {"stage_error": str(exc)[:200]}

    summary = {
        "sales": await _stage(lambda: run_sales(rng)),
        "card_settlements": await _stage(settle_cards),
        "procurement": await _stage(run_procurement),
        "hq_restocked": await _stage(restock_hq),
        "scheduled_runs": await _stage(run_scheduled_payments),
    }
    utils.log(
        "system", "tick.completed",
        {k: (v if isinstance(v, dict) else len(v)) for k, v in summary.items()},
    )
    return summary
