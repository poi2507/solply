"""손님 구매 → 즉시 조달 트리거 (api/shop.py + economy.procure_store).

지키는 것:
  - 안전선이 깨지면 그 지점의 조달이 응답 직후 바로 돈다 — 다음 틱을 기다리지 않는다
  - 틱이 도는 중이면 양보한다 — 같은 지점 거래가 겹치면 경합 오류다 (8/11·8/13)
  - 안전선 위면 아무것도 촉발하지 않는다
  - 끄면(SHOP_TRIGGER_ENABLED=0) 예전처럼 틱에 맡긴다
  - 조달이 죽어도 잠금은 되돌린다 — 안 그러면 다음 틱이 TTL(9분)을 기다린다
  - 틱의 조달 단계는 지점마다 같은 함수를 부른다 — 리팩터가 동작을 바꾸지 않았다
  - 손님 구매가 일으킨 발주는 납품 문서에 그렇게 남는다 — 스케줄러가 돌린 것과 구분된다
"""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app import config
from app.agents import utils
from app.core import economy
from app.db import store as db
from app.main import app

client = TestClient(app)

STORE, SKU = "store-a", "OIL-18"


@pytest.fixture(autouse=True)
def _no_chain(monkeypatch):
    """결제 서비스 없이 — 구매 응답이 온체인 결과에 좌우되면 안 된다. 잠금은 깨끗하게."""
    monkeypatch.setattr("app.api.shop.payments.balance",
                        lambda w: {"address": f"{w}-ADDR", "usdc": 100.0, "sol": 1})
    monkeypatch.setattr("app.api.shop.payments.pay", lambda *a, **k: {"signature": "SIG"})
    economy.release_tick_lock()
    yield
    economy.release_tick_lock()


def _set_stock(store_id: str, sku: str, target: int) -> None:
    """현재고를 정확히 target으로 — 이동 원장에 조정 한 줄을 적어서."""
    entry = utils.effective_inventory(store_id)[sku]
    delta = target - entry["qty"]
    if delta:
        utils.record_move(store_id, sku, entry.get("name", sku), delta, "adjust", "test baseline")


def _safety() -> int:
    return utils.effective_inventory(STORE)[SKU]["safety"]


def _recorder(result=None, raises=None):
    calls = []

    async def fake(store_id, *, trigger="tick", trigger_ref=None):  # 주문번호 참조도 받는다
        calls.append((store_id, trigger))
        if raises:
            raise raises
        return result
    return calls, fake


def _buy(qty=1):
    return client.post("/api/shop/purchase", json={"store_id": STORE, "sku": SKU, "qty": qty})


def _events(action):
    return [e for e in db.list_events() if e["action"] == action]


def test_purchase_below_safety_starts_procurement_now(monkeypatch):
    calls, fake = _recorder({"route": "hq_order", "status": "paid", "invoice_id": "INV-T"})
    monkeypatch.setattr("app.core.economy.procure_store", fake)
    _set_stock(STORE, SKU, _safety())  # 한 개만 팔려도 깨진다
    before = len(_events("shop.procured"))

    res = _buy()

    assert res.status_code == 200
    data = res.json()
    assert data["low_stock"] is True
    assert data["trigger"] == "started"
    assert "지금" in data["next"], "다음 틱을 기다리라고 하면 안 된다"
    assert calls == [(STORE, "shop")], "그 지점만, 손님 구매 트리거로"
    assert db.get("locks", "tick")["started_at"] is None, "끝나면 잠금을 되돌린다"
    done = _events("shop.procured")[before:]
    assert done and done[-1]["payload"]["invoice_id"] == "INV-T"
    assert _events("shop.trigger")[-1]["payload"]["mode"] == "started"


def test_purchase_yields_when_tick_is_running(monkeypatch):
    calls, fake = _recorder({"route": "hq_order"})
    monkeypatch.setattr("app.core.economy.procure_store", fake)
    _set_stock(STORE, SKU, _safety())
    started = datetime.now(UTC).isoformat()
    db.put("locks", "tick", {"started_at": started})

    data = _buy().json()

    assert data["low_stock"] is True
    assert data["trigger"] == "tick_running"
    assert calls == [], "도는 틱이 처리한다 — 겹치면 경합"
    assert db.get("locks", "tick")["started_at"] == started, "남의 잠금은 건드리지 않는다"


def test_purchase_above_safety_triggers_nothing(monkeypatch):
    calls, fake = _recorder({"route": "hq_order"})
    monkeypatch.setattr("app.core.economy.procure_store", fake)
    _set_stock(STORE, SKU, _safety() + 5)

    data = _buy().json()

    assert data["low_stock"] is False
    assert data["trigger"] is None
    assert calls == []


def test_trigger_can_be_switched_off(monkeypatch):
    calls, fake = _recorder({"route": "hq_order"})
    monkeypatch.setattr("app.core.economy.procure_store", fake)
    monkeypatch.setattr(config, "SHOP_TRIGGER_ENABLED", False)
    _set_stock(STORE, SKU, _safety())

    data = _buy().json()

    assert data["low_stock"] is True
    assert data["trigger"] is None
    assert "다음 틱" in data["next"], "꺼져 있으면 예전처럼 틱에 맡긴다"
    assert calls == []


def test_trigger_failure_releases_lock(monkeypatch):
    calls, fake = _recorder(raises=RuntimeError("a2a down"))
    monkeypatch.setattr("app.core.economy.procure_store", fake)
    _set_stock(STORE, SKU, _safety())

    data = _buy().json()

    assert data["trigger"] == "started", "실패는 응답 뒤에 일어난다 — 손님 영수증은 그대로"
    assert calls == [(STORE, "shop")]
    assert db.get("locks", "tick")["started_at"] is None, "죽어도 잠금은 되돌린다"
    assert _events("shop.procure_failed")[-1]["payload"]["reason"].startswith("a2a down")


def test_swallowed_procurement_error_is_logged_as_failure(monkeypatch):
    """procure_store는 예외를 삼켜 route="error"로 돌려준다 — 그걸 '완료'로 남기면 화면이 속는다."""
    calls, fake = _recorder({"route": "error", "status": "A2A 오류 (store-a/p2p.pay)"})
    monkeypatch.setattr("app.core.economy.procure_store", fake)
    _set_stock(STORE, SKU, _safety())
    before = len(_events("shop.procure_failed"))

    assert _buy().json()["trigger"] == "started"

    failed = _events("shop.procure_failed")[before:]
    assert failed and failed[-1]["payload"]["status"].startswith("A2A 오류")
    assert db.get("locks", "tick")["started_at"] is None


def test_run_procurement_visits_every_store_through_procure_store(monkeypatch):
    calls = []

    async def per_store(store_id, *, trigger="tick"):
        calls.append((store_id, trigger))
        return None if store_id == "store-b" else {"store_id": store_id, "route": "hq_order"}
    monkeypatch.setattr("app.core.economy.procure_store", per_store)

    actions = asyncio.run(economy.run_procurement())

    assert calls == [("store-a", "tick"), ("store-b", "tick"), ("store-c", "tick")]
    assert [a["store_id"] for a in actions] == ["store-a", "store-c"], "None(미달 없음)은 건너뛴다"


def test_shop_triggered_order_is_labeled_on_the_delivery(monkeypatch):
    """납품 문서의 source가 트리거를 따른다 — 상태를 남기지 않고(다른 테스트의 게이트를 흔든다) 가로채서 본다."""
    captured = {}
    real_put = db.put

    def spy_put(collection, doc_id, doc):
        if collection == "deliveries":
            captured[doc_id] = doc
            return {**doc, "id": doc_id}
        return real_put(collection, doc_id, doc)
    monkeypatch.setattr("app.core.economy.db.put", spy_put)
    monkeypatch.setattr("app.agents.hq.tools.create_invoice", lambda delivery_id: {"id": "INV-FAKE"})
    monkeypatch.setattr("app.core.economy.db.update", lambda *a: {})  # 가짜 청구서라 출처 새김은 건너뛴다

    assert economy._fulfill_order("store-b", "CHK-10", need=2,
                                  source=economy.PROCURE_SOURCE["shop"]) == "INV-FAKE"
    assert list(captured.values())[-1]["source"] == "shop-purchase"
    assert economy._fulfill_order("store-b", "CHK-10", need=2) == "INV-FAKE"
    assert list(captured.values())[-1]["source"] == "economy-tick", "틱 발주 표기는 그대로"
