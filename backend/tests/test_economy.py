"""경제 루프 테스트 — LLM·체인 없이 도는 단계만.

에이전트 그래프를 태우는 조달·예약 단계는 make demo-mock/tick이 검증한다.
여기서 지키는 것: 판매가 원장·금고를 정확히 움직이고, 정산이 총량을 보존하며,
본사 이행이 읽히는 납품·청구를 만들고, 틱이 꺼지면 아무 일도 없다.
"""

import random

import pytest
from fastapi.testclient import TestClient

from app.agents import utils
from app.core import economy
from app.db import store as db
from app.main import app

client = TestClient(app)


def test_sales_move_ledger_and_accrue_till():
    rng = random.Random(7)
    before = {s: utils.effective_inventory(s).get("CHK-10", {}).get("qty", 0)
              for s in ("store-a", "store-b", "store-c")}

    sold = economy.run_sales(rng)

    assert sold, "재고가 있는데 아무것도 안 팔리면 rng 경계가 잘못된 것"
    for sale in sold:
        assert sale["qty"] > 0
        assert sale["revenue"] == pytest.approx(
                round(sale["qty"] * economy._sku_price(sale["sku"]) * economy.RETAIL_MARGIN, 2)
            ), "매출 = 공급가 × 마진 — 마진 없이는 지점 순현금흐름이 0이라 마찰 손실만 남는다"
        till = db.get(economy.TILL, sale["store_id"])
        assert till["accrued_usdc"] > 0
    # 판매는 원장(sold 이동)을 지나므로 현재고가 그만큼 줄어야 한다
    a_sold = sum(s["qty"] for s in sold if s["store_id"] == "store-a" and s["sku"] == "CHK-10")
    assert utils.effective_inventory("store-a")["CHK-10"]["qty"] == before["store-a"] - a_sold


def test_card_settlement_pays_accrued_and_resets(monkeypatch):
    """금고 4.0 정리 = 실지급 3.0(로열티 25% 공제) + 채권 전액 소멸."""
    db.put(economy.TILL, "store-a", {"accrued_usdc": 4.0})
    db.put(economy.TILL, "store-b", {"accrued_usdc": 0.0})
    db.put(economy.TILL, "store-c", {"accrued_usdc": 0.0})  # 앞 테스트의 판매 적립 제거
    payouts = []
    monkeypatch.setattr(
        "app.core.economy.payments.balance",
        lambda w: {"address": f"{w}-ADDR", "usdc": 100.0 if w == "hq" else 1.0, "sol": 1},
    )
    monkeypatch.setattr(
        "app.core.economy.payments.pay",
        lambda src, to, amt, memo: payouts.append((src, to, amt, memo)) or {"signature": "S"},
    )

    paid = economy.settle_cards()

    assert [(p["store_id"], p["amount_usdc"], p["royalty_usdc"]) for p in paid] == [
        ("store-a", 3.0, 1.0)
    ], "실지급 = 금고 × (1 − 로열티 25%)"
    assert payouts[0][0] == "hq" and payouts[0][2] == 3.0 and payouts[0][3] == "CARD-SETTLEMENT"
    assert db.get(economy.TILL, "store-a")["accrued_usdc"] == 0.0, "채권은 gross만큼 정리"
    settled = [e for e in db.list_events() if e["action"] == "card.settled"]
    assert settled and settled[-1]["payload"]["royalty_usdc"] == 1.0


def test_card_settlement_royalty_returns_margin_leak(monkeypatch):
    """로열티 원천징수의 수지 가드 — 이게 없으면 폐쇄 풀에서 본사가 마른다.

    마진 1.35는 판매마다 매출의 26%(0.35/1.35)를 본사→지점으로 영구 이동시킨다
    (8/11 라이브: 온체인 총량 400 중 본사 5.0까지 고갈, 카드정산 정지).
    gross − net == gross × royalty_pct/100 이 지켜져야 유출이 1.25%대로 준다.
    """
    from app.core import policy as policy_mod

    db.put(economy.TILL, "store-a", {"accrued_usdc": 0.0})
    db.put(economy.TILL, "store-b", {"accrued_usdc": 27.0})
    db.put(economy.TILL, "store-c", {"accrued_usdc": 0.0})
    payouts = []
    monkeypatch.setattr(
        "app.core.economy.payments.balance",
        lambda w: {"address": f"{w}-ADDR", "usdc": 500.0, "sol": 1},
    )
    monkeypatch.setattr(
        "app.core.economy.payments.pay",
        lambda src, to, amt, memo: payouts.append(amt) or {"signature": "S"},
    )

    paid = economy.settle_cards()

    pct = policy_mod.get("hq").royalty_pct
    assert pct > 0, "로열티가 0이면 본사 순유출이 매출의 26%로 복귀한다 (재주입 검출)"
    expected_net = round(27.0 * (1 - pct / 100), 2)
    assert payouts == [expected_net]
    assert paid[0]["amount_usdc"] + paid[0]["royalty_usdc"] == pytest.approx(27.0), "gross 보존"
    db.put(economy.TILL, "store-b", {"accrued_usdc": 0.0})


def test_card_settlement_pays_partially_within_hq_reserve(monkeypatch):
    """hq 가용액(잔액−예비 5)까지 **부분 지급**하고 잔여 채권은 금고에 남긴다.

    통째로 건너뛰면 금고가 hq 잔액보다 커지는 순간 영원히 못 받는다 —
    8/6 라이브에서 카드정산이 멈춰 지점 돈이 말랐던 사고의 회귀 가드.
    """
    db.put(economy.TILL, "store-c", {"accrued_usdc": 50.0})
    paid = []
    monkeypatch.setattr(
        "app.core.economy.payments.balance",
        lambda w: {"address": f"{w}-ADDR", "usdc": 10.0, "sol": 1},
    )
    monkeypatch.setattr(
        "app.core.economy.payments.pay",
        lambda src, to, amount, memo: paid.append((to, amount)) or {"signature": "S"},
    )
    result = economy.settle_cards()

    assert paid == [("store-c-ADDR", 3.75)], "가용액 10−5=5(gross)의 로열티 공제 후 3.75 지급"
    assert result == [{"store_id": "store-c", "amount_usdc": 3.75, "royalty_usdc": 1.25}]
    assert db.get(economy.TILL, "store-c")["accrued_usdc"] == pytest.approx(45.0), "잔여 채권 보존"
    db.put(economy.TILL, "store-c", {"accrued_usdc": 0.0})  # 다른 테스트 오염 방지


def test_card_settlement_failure_preserves_till(monkeypatch):
    """지급 실패는 그 지점만 건너뛰고 금고를 보존한다 — 다음 틱이 재시도한다."""
    db.put(economy.TILL, "store-c", {"accrued_usdc": 3.0})
    monkeypatch.setattr(
        "app.core.economy.payments.balance",
        lambda w: {"address": f"{w}-ADDR", "usdc": 100.0, "sol": 1},
    )
    def boom(*a):
        raise RuntimeError("devnet 일시 오류")
    monkeypatch.setattr("app.core.economy.payments.pay", boom)

    assert economy.settle_cards() == []
    assert db.get(economy.TILL, "store-c")["accrued_usdc"] == pytest.approx(3.0)
    db.put(economy.TILL, "store-c", {"accrued_usdc": 0.0})


def test_fulfill_order_creates_readable_delivery_and_invoice():
    """본사 이행 — 최소 발주량 반영, 검수 일치 납품 문서, 청구 발행, 원장 쌍."""
    invoice_id = economy._fulfill_order("store-b", "CHK-10", need=4)

    assert invoice_id and invoice_id.startswith("INV-")
    invoice = db.get("invoices", invoice_id)
    assert invoice["items"][0]["qty"] == 10, "need 4 < min_qty 10 → 10개 발주"
    assert invoice["amount_usdc"] == pytest.approx(10 * economy._sku_price("CHK-10"))

    delivery = db.get("deliveries", invoice["delivery_id"])
    assert delivery["received"] == {"CHK-10": 10}
    assert utils.receiving_log("store-b", delivery["id"]) == {"CHK-10": 10}, "DB 납품도 검수 조회 가능"

    moves = [m for m in db.list_docs("inventory_moves") if m["ref"] == delivery["id"]]
    assert {(m["store_id"], m["qty"]) for m in moves} == {("hq", -10), ("store-b", 10)}


def test_restock_refills_hq_below_safety():
    entry = utils.effective_inventory("hq")["CHK-10"]
    drop = entry["qty"] - entry["safety"] + 1  # 안전선 1개 아래로
    utils.record_move("hq", "CHK-10", entry["name"], -drop, "shipped", "TEST-DRAIN")

    restocked = economy.restock_hq()

    assert any(r["sku"] == "CHK-10" for r in restocked)
    after = utils.effective_inventory("hq")["CHK-10"]
    assert after["qty"] >= after["safety"]
    assert [e for e in db.list_events() if e["action"] == "warehouse.restocked"]


def test_scheduled_backlog_does_not_block_procurement():
    """예약(합의된 분할·유예)이 쌓여도 발주는 계속돼야 한다.

    8/7 라이브: 미결 210건 중 184건이 예약이었는데 게이트가 전부 세는 바람에
    세 지점이 영구 발주 정지 → 데모가 넣어주는 냉장 닭만 남고 나머지 재고가 0이 됐다.
    """
    from app.core import status as status_mod

    for i in range(economy.MAX_STUCK_INVOICES + 5):  # 게이트 기준을 넘는 예약 백로그
        db.put("invoices", f"INV-TEST-SCHED-{i}", {
            "id": f"INV-TEST-SCHED-{i}", "store_id": "store-b",
            "status": status_mod.InvoiceStatus.SCHEDULED, "amount_usdc": 1.0, "items": [],
        })

    inv = utils.effective_inventory("store-b")["CHK-10"]
    utils.record_move("store-b", "CHK-10", inv["name"], -(inv["qty"] - inv["safety"] + 1),
                      "sold", "TEST-DRAIN")

    open_invoices = [d for d in db.list_docs("invoices", store_id="store-b")
                     if d["status"] in status_mod.ACTIONABLE]
    stuck = sum(1 for d in open_invoices
                if d["status"] != status_mod.InvoiceStatus.SCHEDULED)
    assert len(open_invoices) > economy.MAX_STUCK_INVOICES, "예약 백로그가 기준을 넘어야 의미 있는 검사"
    assert stuck < economy.MAX_STUCK_INVOICES, "예약은 '막힌' 청구서로 세지 않는다"
    assert utils.stock_shortages(utils.effective_inventory("store-b")), "미달이 있어야 발주 대상"


def test_overstock_sells_faster():
    """과잉 재고는 더 팔려야 한다 — 안 그러면 한 지점에 쌓여 직거래가 단방향이 된다."""
    def mean(w):
        return sum(i * x for i, x in zip((0, 1, 2), w)) / sum(w)

    normal = economy.sale_weights({"qty": 4, "safety": 4})
    piled = economy.sale_weights({"qty": 40, "safety": 4})
    assert mean(piled) > mean(normal), "안전선의 10배가 쌓였는데 판매 기대값이 같다"


def test_starving_store_can_order_despite_backlog():
    """재고가 바닥난 지점은 미납이 쌓여 있어도 발주할 수 있어야 한다.

    8/7 라이브 사망 나선: 게이트에 막혀 발주 불가 → 팔 재고 0 → 매출 0 →
    갚을 돈 없음 → 계속 게이트. 굶는 지점은 우회로가 있어야 경제가 회복된다.
    """
    inventory = utils.effective_inventory("store-c")
    for sku, e in inventory.items():  # 전 품목을 안전선 아래로
        if e["qty"] >= e["safety"]:
            utils.record_move("store-c", sku, e["name"], -(e["qty"] - e["safety"] + 1),
                              "sold", "TEST-STARVE")
    shortages = utils.stock_shortages(utils.effective_inventory("store-c"))
    starving = len(shortages) >= max(1, round(len(inventory) * economy.STARVING_RATIO))
    assert starving, "전 품목 미달이면 굶는 지점으로 판정돼 게이트를 우회한다"


def test_reorder_fills_above_safety():
    """딱 안전재고까지만 채우면 판매 한 번에 다시 미달이라 매 틱 발주가 나간다."""
    inv = utils.effective_inventory("store-c")["CHK-10"]
    utils.record_move("store-c", "CHK-10", inv["name"], -(inv["qty"] - inv["safety"] + 2),
                      "sold", "TEST-DRAIN")
    shortage = utils.stock_shortages(utils.effective_inventory("store-c"))[0]
    need = shortage["need"] + shortage["safety"] * (economy.REORDER_TO_SAFETY_X - 1)
    assert shortage["qty"] + need > shortage["safety"], "재주문 후엔 안전선 위에 여유가 남아야 한다"


def test_tick_endpoint_respects_toggle(monkeypatch):
    monkeypatch.setattr("app.config.TICK_ENABLED", False)
    assert client.post("/api/ticks/run").status_code == 409


# ── 손님 구매 (/shop) ────────────────────────────────────────────────

def test_shop_menu_lists_stores_with_prices():
    menu = client.get("/api/shop").json()
    assert {s["id"] for s in menu["stores"]} == {"store-a", "store-b", "store-c"}
    item = menu["stores"][0]["items"][0]
    assert {"sku", "name", "qty", "safety", "price_usdc"} <= set(item)
    assert item["price_usdc"] == pytest.approx(
        round(economy._sku_price(item["sku"]) * economy.RETAIL_MARGIN, 2)
    ), "진열대는 소비자 가격 — 공급가 그대로면 손님 결제와 금고 적립이 어긋난다"


def test_visitor_purchase_moves_ledger_and_till():
    before_qty = utils.effective_inventory("store-c")["CHK-10"]["qty"]
    before_till = (db.get(economy.TILL, "store-c") or {}).get("accrued_usdc", 0.0)

    res = client.post("/api/shop/purchase", json={"store_id": "store-c", "sku": "CHK-10", "qty": 1})

    assert res.status_code == 200
    data = res.json()
    assert data["remaining"] == before_qty - 1
    assert "next" in data
    till = db.get(economy.TILL, "store-c")["accrued_usdc"]
    assert till == pytest.approx(before_till + round(economy._sku_price("CHK-10") * economy.RETAIL_MARGIN, 2))
    move = db.list_docs("inventory_moves")[-1]
    assert move["reason"] == "sold" and move["ref"] == "손님 구매 (라이브)"


def test_visitor_purchase_carries_onchain_receipt(monkeypatch):
    """손님 결제 성공 — 응답에 온체인 영수증이 실리고 유입 계수기·이벤트가 남는다."""
    from app.core import kst

    monkeypatch.setattr("app.api.shop.payments.balance",
                        lambda w: {"address": f"{w}-ADDR", "usdc": 100.0})
    monkeypatch.setattr("app.api.shop.payments.pay",
                        lambda *a, **k: {"signature": "SIG-GUEST-1"})
    before = (db.get("stats", f"flows-{kst.today()}") or {}).get("guest_usdc", 0.0)

    res = client.post("/api/shop/purchase", json={"store_id": "store-c", "sku": "CHK-10", "qty": 1})

    assert res.status_code == 200
    data = res.json()
    assert data["tx"] == "SIG-GUEST-1" and data["paid_usdc"] > 0
    assert data["paid_usdc"] == pytest.approx(data["revenue"]), \
        "손님이 낸 돈 == 금고 적립액 — 어긋나면 본사가 받은 것보다 더 내준다"
    flows = db.get("stats", f"flows-{kst.today()}")
    assert flows["guest_usdc"] == pytest.approx(before + data["paid_usdc"])
    sale = [e for e in db.list_events() if e["action"] == "shop.sale"][-1]
    assert sale["payload"]["tx"] == "SIG-GUEST-1"


def test_visitor_purchase_survives_payment_outage(monkeypatch):
    """지갑 고갈·RPC 장애에도 구매 기록은 남는다 — 데모가 멈추지 않는다."""
    def boom(*a, **k):
        raise RuntimeError("guest wallet dry")
    monkeypatch.setattr("app.api.shop.payments.balance", boom)

    res = client.post("/api/shop/purchase", json={"store_id": "store-a", "sku": "CHK-10", "qty": 1})

    assert res.status_code == 200
    assert res.json()["tx"] is None
    assert [e for e in db.list_events() if e["action"] == "shop.pay_failed"]


def test_real_guest_demand_displaces_sim_sales():
    """실수요 우선 — 오늘 손님이 산 만큼 시뮬 판매가 물러나고, 같은 몫이 두 번 차감되지 않는다."""
    class Rush:
        def choices(self, population, weights=None):
            return [1]

    # 다른 테스트의 손님 구매와 겹치지 않는 전용 품목 — 차감 크레딧을 격리한다
    utils.record_move("store-a", "TST-99", "테스트 품목", 5, "received", "TEST-GUESTDEMAND")
    economy.sell("store-a", "TST-99", 1, "손님 구매 (라이브)")

    first = economy.run_sales(Rush())
    assert not any(s["store_id"] == "store-a" and s["sku"] == "TST-99" for s in first), \
        "손님이 산 만큼 시뮬이 물러난다"

    second = economy.run_sales(Rush())
    assert any(s["store_id"] == "store-a" and s["sku"] == "TST-99" for s in second), \
        "차감은 원장에 기록되어 한 번만 — 다음 틱은 평소처럼 돈다"


def test_visitor_purchase_guards():
    assert client.post("/api/shop/purchase",
                       json={"store_id": "store-x", "sku": "CHK-10", "qty": 1}).status_code == 404
    assert client.post("/api/shop/purchase",
                       json={"store_id": "store-a", "sku": "CHK-10", "qty": 9}).status_code == 422
    assert client.post("/api/shop/purchase",
                       json={"store_id": "store-a", "sku": "LOB-01", "qty": 1}).status_code == 409


def test_refused_invoice_reaches_human_queue_and_can_be_confirmed():
    """"거부하고 사람에게 넘긴다"가 화면의 사실이어야 한다 — 거부 건은 승인 큐에
    올라오고, 사람이 확정하면 큐에서 내려간다. (8/7: 거부 42건이 어떤 큐에도 없었다)"""
    db.put("invoices", "INV-TEST-REFUSED", {
        "id": "INV-TEST-REFUSED", "store_id": "store-a", "status": "refused",
        "amount_usdc": 3.0, "items": [],
    })

    queue = client.get("/api/approvals").json()["pending"]
    assert any(d["id"] == "INV-TEST-REFUSED" for d in queue), "거부 건이 사람 큐에 보여야 한다"

    res = client.post("/api/approvals/INV-TEST-REFUSED/decide",
                      json={"decision": "reject"})
    assert res.status_code == 200 and res.json()["outcome"] == "refused"

    queue = client.get("/api/approvals").json()["pending"]
    assert not any(d["id"] == "INV-TEST-REFUSED" for d in queue), "확정한 건은 큐에서 내려간다"


def test_split_rejects_refused_invoice():
    """거부된 청구서는 분할할 수 없다 — 상태 목록을 손으로 적다 빠뜨렸던 구멍."""
    from app.agents.hq import tools as hq_tools

    db.put("invoices", "INV-TEST-NOSPLIT", {
        "id": "INV-TEST-NOSPLIT", "store_id": "store-a", "status": "refused",
        "amount_usdc": 8.0, "items": [],
    })
    result = hq_tools.split_invoice("INV-TEST-NOSPLIT", parts=2)
    assert result.get("error"), "refused는 분할 금지"
