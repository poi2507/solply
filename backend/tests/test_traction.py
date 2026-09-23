"""실사용 계측 — 실제 방문자와 시뮬 배경 수요를 섞지 않는다.

지키는 것:
  - 손님 주문은 방문자 해시를 남긴다 (IP 원문은 남기지 않는다)
  - 손님 주문이 일으킨 발주의 청구서엔 출처(shop-purchase)와 주문번호가, 틱 발주엔 economy-tick이 새겨진다
  - /api/traction은 실제 주문·결제액·고유 방문자·에이전트 반응을 세고,
    판매 이동을 실판매(표식 있음)와 시뮬(표식 없음)로 가른다
  - 최근 주문은 그 주문이 일으킨 청구서 번호를 달고 나온다
"""

import pytest
from fastapi.testclient import TestClient

from app.agents import utils
from app.core import economy, traction
from app.db import store as db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr("app.api.shop.payments.balance",
                        lambda w: {"address": f"{w}-ADDR", "usdc": 100.0, "sol": 1})
    monkeypatch.setattr("app.api.shop.payments.pay", lambda *a: {"signature": "SIG"})
    traction._CACHE["value"] = None
    economy.release_tick_lock()
    yield
    economy.release_tick_lock()
    traction._CACHE["value"] = None


def _set_stock(store_id, sku, target):
    entry = utils.effective_inventory(store_id)[sku]
    if target - entry["qty"]:
        utils.record_move(store_id, sku, entry.get("name", sku), target - entry["qty"], "adjust", "test baseline")


def test_order_records_hashed_visitor_not_ip():
    _set_stock("store-a", "BEV-24", 20)
    doc = client.post("/api/shop/order", json={"store_id": "store-a",
                                               "items": [{"item_id": "SFC-SODA", "qty": 1}]}).json()
    v = doc["visitor"]
    assert len(v) == 12 and all(c in "0123456789abcdef" for c in v)
    assert "testclient" not in v and "127.0.0.1" not in str(doc)
    logged = [e for e in db.list_events() if e["action"] == "shop.order"][-1]["payload"]
    assert logged["visitor"] == v


def test_invoice_carries_origin_and_order_ref(monkeypatch):
    captured = {}
    real_update = db.update

    def spy(collection, doc_id, patch):
        if collection == "invoices":
            captured[doc_id] = patch
        return real_update(collection, doc_id, patch)
    monkeypatch.setattr("app.core.economy.db.update", spy)

    shop_inv = economy._fulfill_order("store-b", "CHK-10", need=2,
                                      source=economy.PROCURE_SOURCE["shop"], ref="ORD-TEST-1")
    tick_inv = economy._fulfill_order("store-b", "CHK-10", need=2)
    assert captured[shop_inv] == {"origin": "shop-purchase", "order_ref": "ORD-TEST-1"}
    assert captured[tick_inv] == {"origin": "economy-tick"}
    assert db.get("invoices", shop_inv)["order_ref"] == "ORD-TEST-1"


def test_traction_counts_real_and_simulated_separately(monkeypatch):
    monkeypatch.setattr("app.config.TRACTION_SINCE", "2000-01-01")
    before = traction.compute()["totals"]
    traction._CACHE["value"] = None

    # 시뮬 판매 1 (표식 없음) + 실제 주문 1 (표식 있음, 소다 1인분)
    economy.sell("store-a", "MU-03", 1, "시뮬 손님 (테스트)")
    _set_stock("store-a", "BEV-24", 20)
    doc = client.post("/api/shop/order", json={"store_id": "store-a",
                                               "items": [{"item_id": "SFC-SODA", "qty": 1}]}).json()
    # 그 주문이 일으킨 조달 완료 기록 — 최근 주문이 청구서 번호를 달고 나와야 한다
    utils.log("system", "shop.procured", {"store_id": "store-a", "order_id": doc["id"],
                                          "route": "hq_order", "invoice_id": "INV-TR-1"})

    after = client.get("/api/traction").json()
    t = after["totals"]
    assert t["orders"] - before["orders"] == 1
    assert t["paid_usdc"] - before["paid_usdc"] == pytest.approx(doc["total_usdc"])
    assert t["real_servings"] - before["real_servings"] == 1, "주문의 재료 판매는 실판매로"
    assert t["sim_servings"] - before["sim_servings"] == 1, "표식 없는 판매는 시뮬로"
    assert t["procured"] - before["procured"] == 1
    assert t["visitors"] >= 1
    latest = after["recentOrders"][0]
    assert latest["order_id"] == doc["id"] and latest["invoice_id"] == "INV-TR-1"
    assert any("hash" in n for n in after["notes"])


def test_traction_starts_at_the_configured_day(monkeypatch):
    monkeypatch.setattr("app.config.TRACTION_SINCE", "2999-01-01")
    out = traction.compute()
    assert out["daily"] == [] and out["totals"]["orders"] == 0, "시작일 전 기록은 세지 않는다"
