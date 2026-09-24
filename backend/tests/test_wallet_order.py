"""방문자 자기 지갑(Phantom) 결제 — 청구 → 방문자 서명·전송 → 서버가 체인에서 대조 → 그때 판매.

지키는 것:
  - 청구 단계에서는 재고가 움직이지 않는다 (돈을 내기 전에 팔지 않는다)
  - 청구 응답은 받을 곳(본사 USDC 계좌)·금액·메모(주문번호)를 준다
  - 체인 대조가 맞아야만 판매·조달이 일어난다: 성공·수취 계좌·금액·메모·서명 지갑
  - 체인에 아직 안 보이면 425 — 재고 그대로
  - 같은 트랜잭션으로 두 주문을 낼 수 없고, 같은 확인이 두 번 와도 한 번만 판다
  - 실사용 패널은 자기 지갑 결제를 데모 지갑 결제와 따로 센다
"""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.agents import utils
from app.core import economy, traction
from app.db import store as db
from app.main import app

client = TestClient(app)
WALLET = "7VisitorWa11etPubkey1111111111111111111111"
_n = [0]


def _sig():
    """테스트마다 새 서명 — 상태 파일이 테스트 사이에 남는다."""
    _n[0] += 1
    return f"{_n[0]:04d}" + "5" * 84


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr("app.api.shop.payments.balance",
                        lambda w: {"address": f"{w}-ADDR", "usdc": 100.0, "sol": 1})
    monkeypatch.setattr("app.api.shop.payments.pay", lambda *a: {"signature": "DEMO-SIG"})
    economy.release_tick_lock()
    traction._CACHE["value"] = None
    for sku in ("BEV-24",):
        e = utils.effective_inventory("store-a")[sku]
        if 20 - e["qty"]:
            utils.record_move("store-a", sku, e["name"], 20 - e["qty"], "adjust", "test baseline")
    yield
    economy.release_tick_lock()


def _stock():
    return utils.effective_inventory("store-a")["BEV-24"]["qty"]


def _prepare(qty=1):
    return client.post("/api/shop/order", json={"store_id": "store-a", "pay": "wallet", "wallet": WALLET,
                                               "items": [{"item_id": "SFC-SODA", "qty": qty}]}).json()


def _chain(monkeypatch, order, **over):
    tx = {"found": True, "success": True, "memo": order["id"], "feePayer": WALLET,
          "transfer": {"source": "VisitorAta", "destination": config.HQ_USDC_ATA,
                       "amount": order["total_usdc"]}}
    tx.update({k: v for k, v in over.items() if k != "transfer"})
    if "transfer" in over:
        tx["transfer"] = {**tx["transfer"], **over["transfer"]}
    monkeypatch.setattr("app.api.shop.payments.verify_tx", lambda sig: tx)


def test_prepare_bills_without_touching_stock():
    before = _stock()
    o = _prepare(2)
    assert o["status"] == "awaiting_payment" and o["payer"] == "own_wallet"
    p = o["payment"]
    assert p["recipient_token_account"] == config.HQ_USDC_ATA and p["memo"] == o["id"]
    assert p["amount_base_units"] == round(o["total_usdc"] * 1_000_000)
    assert _stock() == before, "돈을 내기 전에 팔지 않는다"


def test_confirm_after_onchain_match_sells_and_logs(monkeypatch):
    SIG = _sig()
    before = _stock()
    o = _prepare(1)
    _chain(monkeypatch, o)
    res = client.post(f"/api/shop/orders/{o['id']}/confirm", json={"signature": SIG})
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["status"] == "paid" and d["tx"] == SIG and d["paid_usdc"] == o["total_usdc"]
    assert _stock() == before - 1
    logged = [e for e in db.list_events() if e["action"] == "shop.order"][-1]["payload"]
    assert logged["payer"] == "own_wallet" and logged["wallet"] == WALLET

    again = client.post(f"/api/shop/orders/{o['id']}/confirm", json={"signature": SIG})
    assert again.status_code == 200 and _stock() == before - 1, "두 번 확인해도 한 번만 판다"


@pytest.mark.parametrize("over, word", [
    ({"success": False}, "failed"),
    ({"transfer": {"destination": "SomeoneElse"}}, "HQ"),
    ({"transfer": {"amount": 0.01}}, "amount"),
    ({"memo": "ORD-OTHER"}, "memo"),
    ({"feePayer": "AnotherWallet"}, "signed"),
])
def test_confirm_rejects_mismatch(monkeypatch, over, word):
    SIG = _sig()
    before = _stock()
    o = _prepare(1)
    _chain(monkeypatch, o, **over)
    res = client.post(f"/api/shop/orders/{o['id']}/confirm", json={"signature": SIG})
    assert res.status_code == 409 and word in res.json()["detail"]
    assert _stock() == before
    assert db.get("customer_orders", o["id"])["status"] == "payment_rejected"


def test_confirm_not_yet_visible_is_425(monkeypatch):
    SIG = _sig()
    before = _stock()
    o = _prepare(1)
    monkeypatch.setattr("app.api.shop.payments.verify_tx", lambda sig: {"found": False})
    res = client.post(f"/api/shop/orders/{o['id']}/confirm", json={"signature": SIG})
    assert res.status_code == 425 and _stock() == before


def test_one_transaction_cannot_pay_two_orders(monkeypatch):
    SIG = _sig()
    a = _prepare(1)
    _chain(monkeypatch, a)
    assert client.post(f"/api/shop/orders/{a['id']}/confirm", json={"signature": SIG}).status_code == 200
    b = _prepare(1)
    _chain(monkeypatch, b)
    res = client.post(f"/api/shop/orders/{b['id']}/confirm", json={"signature": SIG})
    assert res.status_code == 409 and "another order" in res.json()["detail"]


def test_traction_counts_own_wallet_separately(monkeypatch):
    monkeypatch.setattr("app.config.TRACTION_SINCE", "2000-01-01")
    before = traction.compute()["totals"]
    SIG = _sig()
    o = _prepare(1)
    _chain(monkeypatch, o)
    client.post(f"/api/shop/orders/{o['id']}/confirm", json={"signature": SIG})
    client.post("/api/shop/order", json={"store_id": "store-a", "items": [{"item_id": "SFC-SODA", "qty": 1}]})
    after = traction.compute()["totals"]
    assert after["own_wallet_orders"] - before["own_wallet_orders"] == 1
    assert after["orders"] - before["orders"] == 2
    assert after["own_wallets"] >= 1
