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
        assert sale["revenue"] == pytest.approx(sale["qty"] * economy._sku_price(sale["sku"]))
        till = db.get(economy.TILL, sale["store_id"])
        assert till["accrued_usdc"] > 0
    # 판매는 원장(sold 이동)을 지나므로 현재고가 그만큼 줄어야 한다
    a_sold = sum(s["qty"] for s in sold if s["store_id"] == "store-a" and s["sku"] == "CHK-10")
    assert utils.effective_inventory("store-a")["CHK-10"]["qty"] == before["store-a"] - a_sold


def test_card_settlement_pays_accrued_and_resets(monkeypatch):
    db.put(economy.TILL, "store-a", {"accrued_usdc": 3.5})
    db.put(economy.TILL, "store-b", {"accrued_usdc": 0.0})
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

    assert [(p["store_id"], p["amount_usdc"]) for p in paid] == [("store-a", 3.5)]
    assert payouts[0][0] == "hq" and payouts[0][3] == "CARD-SETTLEMENT"
    assert db.get(economy.TILL, "store-a")["accrued_usdc"] == 0.0
    assert [e for e in db.list_events() if e["action"] == "card.settled"]


def test_card_settlement_respects_hq_reserve(monkeypatch):
    """hq 잔액이 바닥이면 지급하지 않는다 — 생태계가 마이너스로 가지 않게."""
    db.put(economy.TILL, "store-c", {"accrued_usdc": 50.0})
    monkeypatch.setattr(
        "app.core.economy.payments.balance",
        lambda w: {"address": f"{w}-ADDR", "usdc": 10.0, "sol": 1},
    )
    monkeypatch.setattr(
        "app.core.economy.payments.pay",
        lambda *a: pytest.fail("예비금을 깨고 지급하면 안 된다"),
    )
    assert economy.settle_cards() == []
    db.put(economy.TILL, "store-c", {"accrued_usdc": 0.0})  # 다른 테스트 오염 방지


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


def test_tick_endpoint_respects_toggle(monkeypatch):
    monkeypatch.setattr("app.config.TICK_ENABLED", False)
    assert client.post("/api/ticks/run").status_code == 409


# ── 손님 구매 (/shop) ────────────────────────────────────────────────

def test_shop_menu_lists_stores_with_prices():
    menu = client.get("/api/shop").json()
    assert {s["id"] for s in menu["stores"]} == {"store-a", "store-b", "store-c"}
    item = menu["stores"][0]["items"][0]
    assert {"sku", "name", "qty", "safety", "price_usdc"} <= set(item)


def test_visitor_purchase_moves_ledger_and_till():
    before_qty = utils.effective_inventory("store-c")["CHK-10"]["qty"]
    before_till = (db.get(economy.TILL, "store-c") or {}).get("accrued_usdc", 0.0)

    res = client.post("/api/shop/purchase", json={"store_id": "store-c", "sku": "CHK-10", "qty": 1})

    assert res.status_code == 200
    data = res.json()
    assert data["remaining"] == before_qty - 1
    assert "next" in data
    till = db.get(economy.TILL, "store-c")["accrued_usdc"]
    assert till == pytest.approx(before_till + economy._sku_price("CHK-10"))
    move = db.list_docs("inventory_moves")[-1]
    assert move["reason"] == "sold" and move["ref"] == "손님 구매 (라이브)"


def test_visitor_purchase_guards():
    assert client.post("/api/shop/purchase",
                       json={"store_id": "store-x", "sku": "CHK-10", "qty": 1}).status_code == 404
    assert client.post("/api/shop/purchase",
                       json={"store_id": "store-a", "sku": "CHK-10", "qty": 9}).status_code == 422
    assert client.post("/api/shop/purchase",
                       json={"store_id": "store-a", "sku": "LOB-01", "qty": 1}).status_code == 409
