"""도메인 로직 테스트 — 체인이나 LLM 없이 도는 것만.

온체인이 필요한 경로(execute_payment, verify_payment)는 로컬넷이 떠 있어야 하므로
여기서는 다루지 않는다. `make demo-mock`이 그 역할을 한다.
"""

import json

import pytest

from app.core import protocol
from app.db.local_store import LocalStore


@pytest.fixture()
def store(tmp_path):
    return LocalStore(tmp_path / "state.json")


def test_store_roundtrip(store):
    store.put("invoices", "INV-1", {"store_id": "store-a", "amount_usdc": 10.0, "status": "issued"})
    assert store.get("invoices", "INV-1")["amount_usdc"] == 10.0

    store.update("invoices", "INV-1", {"status": "settled"})
    assert store.get("invoices", "INV-1")["status"] == "settled"

    store.put("invoices", "INV-2", {"store_id": "store-b", "amount_usdc": 5.0, "status": "issued"})
    assert len(store.list_docs("invoices", store_id="store-a")) == 1


def test_events_are_append_only(store):
    store.log_event("hq-agent", "invoice.created", {"invoice_id": "INV-1"})
    store.log_event("store-a-agent", "payment.executed", {"invoice_id": "INV-1"})
    events = store.list_events()
    assert [e["action"] for e in events] == ["invoice.created", "payment.executed"]
    assert all("ts" in e for e in events)


def test_atomic_units_roundtrip():
    # USDC는 소수점 6자리 — 부동소수 오차로 1 lamport라도 어긋나면 검증이 깨진다
    for amount in (0.01, 32.5, 35.0, 1234.567891):
        assert protocol.from_atomic(protocol.to_atomic(amount)) == pytest.approx(amount)


def test_header_encoding_roundtrip():
    payload = {"x402Version": 2, "scheme": "exact", "note": "한글도 안전한가"}
    assert protocol.decode_header(protocol.encode_header(payload)) == payload


def test_payment_requirements_offer_three_terms():
    invoice = {
        "id": "INV-abc",
        "store_id": "store-c",
        "delivery_id": "DEL-003",
        "items": [{"sku": "CHK-10", "name": "냉장 닭", "qty": 10, "unit_price_usdc": 2.5}],
        "amount_usdc": 25.0,
    }
    profile = {"policy": {"defer_max_pct": 20, "installment_max": 2}}
    req = protocol.build_payment_requirements(invoice, "HqWallet111", "localnet", profile)

    assert req["x402Version"] == 2
    terms = [a["extra"]["term"] for a in req["accepts"]]
    assert terms == ["immediate", "deferred", "installment"]

    # 즉시납은 전액, 분할은 절반
    assert protocol.from_atomic(req["accepts"][0]["amount"]) == pytest.approx(25.0)
    assert protocol.from_atomic(req["accepts"][2]["amount"]) == pytest.approx(12.5)

    # 유예·분할은 본사 승인이 필요하다고 표시돼야 한다
    assert req["accepts"][1]["extra"]["requiresApproval"] is True
    assert req["accepts"][2]["extra"]["requiresApproval"] is True

    # 청구 근거(품목)를 함께 실어 보내야 가맹점이 검수 대조를 할 수 있다
    assert req["extensions"]["solply.invoice"]["items"] == invoice["items"]


def test_settlement_response_marks_failure():
    ok = protocol.build_settlement_response("INV-1", "sig", True, "https://explorer")
    bad = protocol.build_settlement_response("INV-1", "sig", False, "")
    assert ok["verified"] and ok["settled"]
    assert not bad["verified"] and not bad["settled"]


def test_fixtures_scenarios_are_intact():
    """데모 시나리오는 코드가 아니라 이 데이터로 만들어진다 — 깨지면 데모가 죽는다."""
    from app import config

    data = json.loads(config.FIXTURES_PATH.read_text())

    # B지점은 검수 불일치가 있어야 차감 협상이 발동한다
    invoiced = {i["sku"]: i["qty"] for i in data["deliveries"]["DEL-002"]["items"]}
    received = data["receiving_logs"]["store-b"]["DEL-002"]
    assert any(received[sku] < qty for sku, qty in invoiced.items())

    # C지점은 시드 이력이 만드는 신용점수가 심사 기준(85) 이상이어야 유예가 수락된다
    from app.core import credit

    hist = data["payment_history"]["store-c"]
    seeded_score = (
        credit.BASE
        + credit.ON_TIME_POINTS * hist.get("on_time", 0)
        - credit.LATE_PENALTY * hist.get("late", 0)
        - credit.DISPUTE_PENALTY * hist.get("disputed", 0)
    )
    assert seeded_score >= 85

    # D 시나리오: DEL-004에는 발주 목록에 없는 품목이 있어야 거부가 발동한다
    ordered = set(data["orders"]["store-a"])
    assert any(i["sku"] not in ordered for i in data["deliveries"]["DEL-004"]["items"])
