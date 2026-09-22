"""SFC 메뉴 주문 — 손님은 요리를 주문하고, 레시피가 재료로 풀려 재고에서 빠진다.

지키는 것:
  - 메뉴판은 지점별 판매 항목·값·가능 인분을 준다 (지역 메뉴는 그 지점에만)
  - 값 = Σ재료 공급가 × 요리 마진 — 메뉴에 따로 적힌 값이 없다
  - 주문 1건 = 재료별 판매 기록 + 온체인 이체 1건(메모=주문번호) + 주문 문서
  - 손님이 내는 돈 = 금고에 적립된 합계 (장부가 기준)
  - 재고가 모자라면 전부 거절 — 반쪽 주문은 없다 (어떤 재료가 모자란지 말한다)
  - 상한(6인분) 초과·타 지점 전용 메뉴는 409
  - 안전선이 깨진 재료가 있으면 즉시 조달이 주문번호를 달고 돈다
  - 주문 추적은 그 주문번호가 달린 에이전트 기록만 모아 준다
"""

import pytest
from fastapi.testclient import TestClient

from app.agents import utils
from app.core import economy, menu
from app.db import store as db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_chain(monkeypatch):
    monkeypatch.setattr("app.api.shop.payments.balance",
                        lambda w: {"address": f"{w}-ADDR", "usdc": 100.0, "sol": 1})
    economy.release_tick_lock()
    yield
    economy.release_tick_lock()


def _set_stock(store_id, sku, target):
    entry = utils.effective_inventory(store_id)[sku]
    delta = target - entry["qty"]
    if delta:
        utils.record_move(store_id, sku, entry.get("name", sku), delta, "adjust", "test baseline")


def _stock(store_id):
    return {sku: e["qty"] for sku, e in utils.effective_inventory(store_id).items()}


def _recorder(result=None):
    calls = []

    async def fake(store_id, *, trigger="tick", trigger_ref=None):
        calls.append((store_id, trigger, trigger_ref))
        return result
    return calls, fake


def _order(store, items):
    return client.post("/api/shop/order", json={"store_id": store, "items": items})


def test_menu_board_lists_store_specific_items():
    board = client.get("/api/shop/menu").json()
    assert board["brand"]["short"] == "SFC"
    by = {s["id"]: {it["id"]: it for it in s["items"]} for s in board["stores"]}
    assert "SFC-SALAD" in by["store-a"] and "SFC-SALAD" not in by["store-b"], "강남 전용"
    assert "SFC-BITES" in by["store-b"] and "SFC-BITES" not in by["store-c"], "홍대 전용"
    assert "SFC-FIRE" in by["store-c"] and "SFC-FIRE" not in by["store-a"], "부산 전용"
    fried = by["store-a"]["SFC-FRIED"]
    assert fried["price_usdc"] > 0 and isinstance(fried["servings"], int)
    assert {r["sku"] for r in fried["recipe"]} == {"CHK-10", "FLR-20", "OIL-18", "MU-03", "PCK-50"}
    assert by["store-a"]["SFC-SALAD"]["exclusive"] and not fried["exclusive"]


def test_price_is_recipe_supply_times_margin():
    item = menu.items()["SFC-FRIED"]
    expected = round(sum(economy._sku_price(s) * n for s, n in item["recipe"].items())
                     * economy.RETAIL_MARGIN, 2)
    assert menu.price_of(item) == expected


def test_order_sells_ingredients_pays_once_and_records(monkeypatch):
    paid = []
    monkeypatch.setattr("app.api.shop.payments.pay",
                        lambda src, to, amt, memo: paid.append((src, to, amt, memo)) or {"signature": "SIG"})
    for sku in ("CHK-10", "FLR-20", "OIL-18", "MU-03", "PCK-50", "BEV-24"):
        _set_stock("store-a", sku, 10)  # 안전선 위 — 트리거 없이 판매만 본다
    before = _stock("store-a")

    res = _order("store-a", [{"item_id": "SFC-FRIED", "qty": 2}, {"item_id": "SFC-SODA", "qty": 1}])

    assert res.status_code == 200, res.text
    doc = res.json()
    assert doc["id"].startswith("ORD-") and doc["status"] == "paid" and doc["tx"] == "SIG"
    assert doc["ingredients"] == {"CHK-10": 2, "FLR-20": 2, "OIL-18": 2, "MU-03": 2, "PCK-50": 2, "BEV-24": 1}
    after = _stock("store-a")
    for sku, n in doc["ingredients"].items():
        assert before[sku] - after[sku] == n, sku
    # 손님이 낸 돈 = 재료별 판매 매출의 합 (금고 적립액과 같은 식)
    expected = round(sum(round(n * economy._sku_price(sku) * economy.RETAIL_MARGIN, 2)
                         for sku, n in doc["ingredients"].items()), 2)
    assert doc["total_usdc"] == pytest.approx(expected)
    assert paid == [("guest", "hq-ADDR", doc["total_usdc"], doc["id"])], "이체 1건, 메모는 주문번호"
    assert doc["low_stock"] == [] and doc["trigger"] is None
    assert db.get("customer_orders", doc["id"])["store_name"] == "Store A (Gangnam)"
    logged = [e for e in db.list_events() if e["action"] == "shop.order"][-1]["payload"]
    assert logged["order_id"] == doc["id"] and "Seoul Fried Chicken x2" in logged["items"]


def test_order_is_all_or_nothing_when_stock_is_short(monkeypatch):
    paid = []
    monkeypatch.setattr("app.api.shop.payments.pay", lambda *a: paid.append(a) or {"signature": "SIG"})
    _set_stock("store-b", "CHK-10", 1)
    for sku in ("FLR-20", "OIL-18", "MU-03", "PCK-50"):
        _set_stock("store-b", sku, 10)
    before = _stock("store-b")

    res = _order("store-b", [{"item_id": "SFC-FRIED", "qty": 2}])

    assert res.status_code == 409
    assert "not enough stock" in res.json()["detail"] and "Chicken" in res.json()["detail"]
    assert _stock("store-b") == before, "반쪽 주문은 없다 — 재고가 하나도 움직이면 안 된다"
    assert paid == []


def test_order_rejects_exclusive_item_elsewhere():
    res = _order("store-b", [{"item_id": "SFC-SALAD", "qty": 1}])
    assert res.status_code == 409 and "not on this store's menu" in res.json()["detail"]


def test_order_caps_total_servings():
    _set_stock("store-a", "BEV-24", 20)
    res = _order("store-a", [{"item_id": "SFC-SODA", "qty": 4}, {"item_id": "SFC-SODA", "qty": 3}])
    assert res.status_code == 409 and "up to 6 servings" in res.json()["detail"]


def test_order_below_safety_triggers_procurement_with_order_ref(monkeypatch):
    monkeypatch.setattr("app.api.shop.payments.pay", lambda *a: {"signature": "SIG"})
    calls, fake = _recorder({"route": "hq_order", "status": "paid", "invoice_id": "INV-T"})
    monkeypatch.setattr("app.core.economy.procure_store", fake)
    inv = utils.effective_inventory("store-a")
    _set_stock("store-a", "CHK-10", inv["CHK-10"]["safety"])  # 한 마리 팔리면 깨진다
    for sku in ("FLR-20", "OIL-18", "MU-03", "PCK-50"):
        _set_stock("store-a", sku, 10)

    doc = _order("store-a", [{"item_id": "SFC-FRIED", "qty": 1}]).json()

    assert doc["low_stock"] == ["CHK-10"] and doc["trigger"] == "started"
    assert calls == [("store-a", "shop", doc["id"])], "그 지점만, 손님 주문 트리거로, 주문번호를 달고"
    assert db.get("locks", "tick")["started_at"] is None

    status = client.get(f"/api/shop/orders/{doc['id']}").json()
    assert [e["action"] for e in status["agent"]] == ["shop.trigger", "shop.procured"]
    assert all(e["payload"]["order_id"] == doc["id"] for e in status["agent"])
    assert status["agent"][-1]["payload"]["invoice_id"] == "INV-T"


def test_order_status_unknown_is_404():
    assert client.get("/api/shop/orders/ORD-0000-Z0000").status_code == 404
