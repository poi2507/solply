"""x402 왕복 테스트 — 챌린지(402) → 조건 선택 → 결제 → PAYMENT-SIGNATURE → 정산 확정.

온체인·HTTP는 monkeypatch로 대체한다. 검증 대상은 프로토콜 왕복의 형태와
"검증 실패면 정산하지 않는다"는 서버의 태도다.
"""

import pytest
from fastapi.testclient import TestClient

from app.agents import utils
from app.agents.store import tools as store_tools
from app.core import protocol
from app.db import store as db
from app.main import app

client = TestClient(app)


def make_invoice(amount: float = 7.0, store_id: str = "store-a") -> dict:
    return db.put(
        "invoices",
        db.new_id("INV"),
        {
            "delivery_id": "DEL-001",
            "store_id": store_id,
            "items": [{"sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 10, "unit_price_usdc": 0.5}],
            "amount_usdc": amount,
            "status": "issued",
            "tx_sig": None,
        },
    )


@pytest.fixture()
def hq_wallet(monkeypatch):
    monkeypatch.setattr(
        "app.solana.payments.balance", lambda wallet: {"address": "HQWALLET", "usdc": 0, "sol": 1}
    )


# ── 챌린지: GET → 402 + 협상 조건 ────────────────────────────────────

def test_challenge_returns_402_with_negotiation_terms(hq_wallet):
    invoice = make_invoice()
    resp = client.get(f"/x402/invoices/{invoice['id']}/settle")

    assert resp.status_code == 402
    accepts = resp.json()["accepts"]
    assert {a["extra"]["term"] for a in accepts} == {"immediate", "deferred", "installment"}
    assert all(a["payTo"] == "HQWALLET" for a in accepts)

    # 헤더와 본문이 같은 요구사항을 실어야 한다 (스펙: PAYMENT-REQUIRED)
    header = protocol.decode_header(resp.headers["PAYMENT-REQUIRED"])
    assert header["accepts"] == accepts

    event = [e for e in db.list_events() if e["action"] == "x402.payment_required"][-1]
    assert event["payload"]["invoice_id"] == invoice["id"]


def test_challenge_on_settled_invoice_short_circuits(hq_wallet):
    invoice = make_invoice()
    db.update("invoices", invoice["id"], {"status": "settled", "tx_sig": "SIG"})
    resp = client.get(f"/x402/invoices/{invoice['id']}/settle")
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_settled"


# ── 정산: POST + PAYMENT-SIGNATURE → 온체인 대조 ─────────────────────

def signature_header(signature: str = "SIG123") -> dict:
    value = protocol.encode_header(
        {"x402Version": protocol.X402_VERSION, "payload": {"signature": signature}}
    )
    return {"PAYMENT-SIGNATURE": value}


def test_settle_confirms_after_onchain_match(monkeypatch):
    invoice = make_invoice()
    monkeypatch.setattr(
        "app.solana.payments.verify_tx",
        lambda sig: {
            "found": True, "success": True, "memo": invoice["id"],
            "transfer": {"amount": invoice["amount_usdc"]}, "explorer": "http://explorer/tx",
        },
    )
    resp = client.post(f"/x402/invoices/{invoice['id']}/settle", headers=signature_header())

    assert resp.status_code == 200
    assert resp.json()["receipt"]["settled"] is True
    assert db.get("invoices", invoice["id"])["status"] == "settled"
    event = [e for e in db.list_events() if e["action"] == "x402.settled"][-1]
    assert event["payload"]["invoice_id"] == invoice["id"]


def test_settle_refuses_wrong_amount(monkeypatch):
    """금액이 다르면 서명이 있어도 정산하지 않는다 — 3중 대조의 핵심."""
    invoice = make_invoice(amount=35.0)
    monkeypatch.setattr(
        "app.solana.payments.verify_tx",
        lambda sig: {
            "found": True, "success": True, "memo": invoice["id"],
            "transfer": {"amount": 1.0}, "explorer": "",
        },
    )
    resp = client.post(f"/x402/invoices/{invoice['id']}/settle", headers=signature_header())

    assert resp.status_code == 402
    assert resp.json()["receipt"]["settled"] is False
    assert db.get("invoices", invoice["id"])["status"] == "issued"


def test_settle_requires_signature_header():
    invoice = make_invoice()
    resp = client.post(f"/x402/invoices/{invoice['id']}/settle")
    assert resp.status_code == 400


# ── 가맹점 쪽: 조건 선택과 결제 왕복 ─────────────────────────────────

def test_pick_term_finds_the_right_option():
    accepts = [
        {"extra": {"term": "immediate"}, "amount": "35000000"},
        {"extra": {"term": "deferred"}, "amount": "35000000"},
    ]
    assert utils.pick_term(accepts, "deferred")["extra"]["term"] == "deferred"
    assert utils.pick_term(accepts, "installment") is None
    assert utils.pick_term([], "immediate") is None


def test_store_pays_via_x402_and_gets_settled(monkeypatch):
    """가맹점 도구가 402 조건대로 지불하고 서명 제출로 정산 확정을 받는다."""
    invoice = make_invoice(store_id="store-b")
    paid: dict = {}

    def fake_pay(from_wallet, recipient, amount, memo):
        paid.update(sender=from_wallet, to=recipient, amount=amount, memo=memo)
        return {"signature": "SIGOK"}

    monkeypatch.setattr("app.solana.payments.pay", fake_pay)
    monkeypatch.setattr(
        "app.core.x402_client.submit_payment",
        lambda inv_id, sig: {
            "status_code": 200,
            "receipt": {"settled": True, "verified": True, "explorer": "http://explorer/tx"},
        },
    )

    term = {
        "payTo": "HQWALLET",
        "amount": protocol.to_atomic(invoice["amount_usdc"]),
        "extra": {"term": "immediate", "memo": invoice["id"]},
    }
    result = store_tools.execute_payment("store-b", invoice["id"], term=term)

    assert result["settled"] is True
    assert paid == {
        "sender": "store-b", "to": "HQWALLET",
        "amount": invoice["amount_usdc"], "memo": invoice["id"],
    }
    event = [e for e in db.list_events() if e["action"] == "payment.executed"][-1]
    assert event["payload"]["via"] == "x402"


def test_store_reports_unsettled_when_hq_rejects(monkeypatch):
    """서명 제출이 검증에 실패하면 도구는 성공한 척하지 않는다."""
    invoice = make_invoice(store_id="store-b")
    monkeypatch.setattr("app.solana.payments.pay", lambda *a: {"signature": "SIGBAD"})
    monkeypatch.setattr(
        "app.core.x402_client.submit_payment",
        lambda inv_id, sig: {"status_code": 402, "receipt": {"settled": False, "verified": False}},
    )

    term = {
        "payTo": "HQWALLET",
        "amount": protocol.to_atomic(invoice["amount_usdc"]),
        "extra": {"term": "immediate", "memo": invoice["id"]},
    }
    result = store_tools.execute_payment("store-b", invoice["id"], term=term)
    assert result["settled"] is False
    assert result["error"]


# ── 그래프 배선 ───────────────────────────────────────────────────────

def test_store_graph_routes_through_request_terms():
    from app.agents.store import graph as store_graph
    from app.agents.store import node

    assert "request_terms" in set(store_graph.build().get_graph().nodes)
    assert node.route_after_verify({"verification": {"match": True}}) == "request_terms"
    assert node.route_after_context({"intent": "invoice.pay_adjusted"}) == "request_terms"
    assert node.route_after_terms({"outcome": "noop"}) == "report"
    assert node.route_after_terms({}) == "cashflow"
