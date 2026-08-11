"""데이터 상점 — 본사가 x402 판매자가 되는 경로.

지키는 것:
  - 지수 집계가 온체인 정산이 확인된 체결(settled·confirmed)만 센다
  - 견적(402)이 주문서를 만들고, 3중 대조를 통과해야만 데이터가 인도된다
  - 주문 하나는 한 번만 이행된다 (같은 결제의 재시도는 멱등, 다른 서명은 거절)
  - 비식별 — 응답 어디에도 지점 식별자가 없다
"""

import pytest
from fastapi.testclient import TestClient

from app.agents import utils
from app.core import data_products
from app.db import store as db
from app.main import app

client = TestClient(app)


def seed_market_data():
    db.put("invoices", "INV-DP-1", {
        "delivery_id": "DEL-DP", "store_id": "store-a",
        "items": [{"sku": "OIL-18", "name": "튀김유 18L", "qty": 10, "unit_price_usdc": 0.5}],
        "amount_usdc": 5.0, "status": "settled", "tx_sig": "SIG1",
    })
    db.put("p2p_trades", "P2P-DP-1", {
        "sku": "OIL-18", "name": "튀김유 18L", "qty": 4, "price_usdc": 1.88,
        "buyer_id": "store-b", "seller_id": "store-a", "status": "confirmed",
    })
    db.put("invoices", "INV-DP-2", {  # 미정산 — 집계에서 빠져야 한다
        "delivery_id": "DEL-DP", "store_id": "store-b",
        "items": [{"sku": "OIL-18", "name": "튀김유 18L", "qty": 100, "unit_price_usdc": 9.9}],
        "amount_usdc": 990.0, "status": "issued", "tx_sig": None,
    })


def test_market_index_counts_only_settled_deals():
    seed_market_data()
    idx = data_products.market_index("OIL-18")
    assert idx["samples"] == 2, "settled 청구서 1 + confirmed 직거래 1 — issued는 체결이 아니다"
    assert idx["unit_price_usdc"] == pytest.approx(round((10 * 0.5 + 1.88) / 14, 4))
    assert idx["sources"] == {"hq_orders": 1, "p2p_trades": 1}
    assert "store-" not in str(idx), "비식별 — 지점 식별자가 나가면 안 된다"


def test_demand_index_sums_sold_moves():
    utils.record_move("store-a", "PCK-50", "포장 박스 50매", -3, "sold", "test")
    utils.record_move("store-b", "PCK-50", "포장 박스 50매", -2, "sold", "test")
    idx = data_products.demand_index("PCK-50")
    assert idx["units_sold"] >= 5
    assert idx["reporting_stores"] >= 2
    assert "store-" not in str(idx)


def _mock_hq_balance(monkeypatch):
    monkeypatch.setattr(
        "app.api.data_products.payments.balance",
        lambda w: {"address": "HQ-ADDR", "usdc": 100.0, "sol": 1},
    )


def test_quote_returns_402_with_order(monkeypatch):
    _mock_hq_balance(monkeypatch)
    resp = client.get("/x402/data/market/OIL-18")
    assert resp.status_code == 402
    body = resp.json()
    order_id = body["extensions"]["solply.dataOrder"]["id"]
    assert db.get("data_orders", order_id)["state"] == "quoted"
    assert body["accepts"][0]["extra"]["memo"] == order_id, "memo = 주문 ID — 결제와 주문의 끈"
    assert [e for e in db.list_events() if e["action"] == "data.quoted"]


def test_unknown_product_is_404():
    assert client.get("/x402/data/credit/store-b").status_code == 404


def _order_and_pay(monkeypatch, amount_paid: float):
    _mock_hq_balance(monkeypatch)
    seed_market_data()
    order_id = client.get("/x402/data/market/OIL-18").json()["extensions"]["solply.dataOrder"]["id"]
    monkeypatch.setattr(
        "app.api.data_products.payments.verify_tx",
        lambda sig: {"found": True, "success": True, "memo": order_id,
                     "transfer": {"amount": amount_paid}, "explorer": "http://x"},
    )
    from app.core import protocol
    header = protocol.encode_header({"x402Version": 2, "payload": {"signature": "SIG-DP"}})
    return order_id, header


def test_settle_delivers_data_after_triple_check(monkeypatch):
    order_id, header = _order_and_pay(monkeypatch, amount_paid=0.1)
    resp = client.post(f"/x402/data/orders/{order_id}/settle", headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["product"] == "market" and body["data"]["samples"] >= 2
    assert db.get("data_orders", order_id)["state"] == "fulfilled"
    assert [e for e in db.list_events() if e["action"] == "data.sold"]


def test_settle_rejects_wrong_amount(monkeypatch):
    order_id, header = _order_and_pay(monkeypatch, amount_paid=0.05)
    resp = client.post(f"/x402/data/orders/{order_id}/settle", headers={"PAYMENT-SIGNATURE": header})
    assert resp.status_code == 402, "검증 실패는 다시 402 — 주장은 인도가 아니다"
    assert db.get("data_orders", order_id)["state"] == "quoted"
    assert "data" not in resp.json()


def test_fulfilled_order_is_idempotent_but_not_replayable(monkeypatch):
    order_id, header = _order_and_pay(monkeypatch, amount_paid=0.1)
    client.post(f"/x402/data/orders/{order_id}/settle", headers={"PAYMENT-SIGNATURE": header})

    again = client.post(f"/x402/data/orders/{order_id}/settle", headers={"PAYMENT-SIGNATURE": header})
    assert again.status_code == 200, "같은 결제의 재시도는 멱등 — 데이터를 다시 내준다"

    from app.core import protocol
    other = protocol.encode_header({"x402Version": 2, "payload": {"signature": "다른서명"}})
    replay = client.post(f"/x402/data/orders/{order_id}/settle", headers={"PAYMENT-SIGNATURE": other})
    assert replay.status_code == 409, "주문 하나 = 이행 한 번 — 다른 서명의 재사용은 거절"
