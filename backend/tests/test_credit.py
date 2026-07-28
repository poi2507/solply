"""Phase 2 테스트 — 신용점수 실계산, 이상 청구 거부, 예약 납부 실행.

체인·LLM 없이 도는 판단 로직만 본다. 실제 왕복은 `make demo-mock`이 검증한다.
"""

import pytest
from fastapi.testclient import TestClient

from app.agents import utils
from app.core import credit
from app.db import store as db
from app.main import app

client = TestClient(app)


# ── 신용점수: 상수가 아니라 이력에서 나온다 ──────────────────────────

@pytest.fixture()
def no_live_history(monkeypatch):
    monkeypatch.setattr("app.db.store.list_docs", lambda *a, **k: [])


@pytest.mark.parametrize(
    ("store_id", "expected"),
    [("store-a", 88), ("store-b", 81), ("store-c", 92)],
)
def test_seeded_history_reproduces_known_scores(no_live_history, store_id, expected):
    """예전에 fixtures에 박혀 있던 88/81/92가 이제 이력 계산으로 재현된다."""
    assert credit.evaluate(store_id)["credit_score"] == expected


def test_live_settlement_raises_the_score(monkeypatch):
    """이번 세션의 온체인 정산이 정시납으로 가산된다 — 데모 중 점수가 오른다."""
    monkeypatch.setattr(
        "app.db.store.list_docs",
        lambda *a, **k: [{"status": "settled"}, {"status": "settled"}, {"status": "issued"}],
    )
    rating = credit.evaluate("store-a")
    assert rating["live_settled"] == 2
    assert rating["credit_score"] == 88 + 2 * credit.ON_TIME_POINTS


def test_score_is_clamped(monkeypatch, no_live_history):
    monkeypatch.setattr(
        "app.core.credit.fixtures.load",
        lambda: {"payment_history": {"x": {"on_time": 999}, "y": {"late": 999}}},
    )
    assert credit.evaluate("x")["credit_score"] == 100
    assert credit.evaluate("y")["credit_score"] == 0


def test_deferral_review_uses_computed_score(no_live_history):
    """본사 심사 도구가 계산된 점수와 근거를 쓰는지 — 하드코딩 회귀 방지."""
    from app.agents.hq import tools as hq_tools

    info = hq_tools.store_credit("store-c")
    assert info["credit_score"] == 92
    assert info["on_time"] == 21 and info["late"] == 0 and info["disputed"] == 0


# ── 이상 청구: 미발주 품목은 협상이 아니라 거부 ──────────────────────

def test_unordered_items_are_flagged():
    items = [
        {"sku": "CHK-10", "name": "냉장 닭", "qty": 10, "unit_price_usdc": 2.5},
        {"sku": "LOB-01", "name": "활 랍스터", "qty": 4, "unit_price_usdc": 12.5},
    ]
    flagged = utils.unordered_items(["CHK-10", "VEG-05"], items)
    assert [i["sku"] for i in flagged] == ["LOB-01"]
    assert utils.unordered_items(["CHK-10", "LOB-01"], items) == []


def test_suspect_items_route_to_refuse_not_negotiation():
    """미발주 품목은 깎아줄 문제가 아니다 — 수량 불일치와 경로가 달라야 한다."""
    from app.agents.store import node

    suspect = {"verification": {"match": False, "suspect_items": [{"sku": "LOB-01"}]}}
    mismatch = {"verification": {"match": False, "discrepancies": [{"sku": "CHK-10"}]}}
    assert node.route_after_verify(suspect) == "refuse"
    assert node.route_after_verify(mismatch) == "propose_adjustment"


def test_del_004_triggers_refusal_for_store_a():
    """거부 시나리오는 코드가 아니라 이 데이터로 만들어진다."""
    from app.core import fixtures

    delivery = fixtures.load()["deliveries"]["DEL-004"]
    assert delivery["store_id"] == "store-a"
    flagged = utils.unordered_items(utils.store_orders("store-a"), delivery["items"])
    assert flagged, "DEL-004에 미발주 품목이 없으면 D 시나리오가 죽는다"


# ── 예약 납부 실행 ───────────────────────────────────────────────────

def test_pay_scheduled_intent_skips_verify():
    """예약 실행분은 이미 검수·합의가 끝난 건이라 바로 정산 요청으로 간다."""
    from app.agents.store import node

    assert node.route_after_context({"intent": "invoice.pay_scheduled"}) == "request_terms"


def test_schedule_run_guards_status():
    invoice = db.put(
        "invoices",
        db.new_id("INV"),
        {"delivery_id": "DEL-003", "store_id": "store-c", "items": [],
         "amount_usdc": 35.0, "status": "issued", "tx_sig": None},
    )
    assert client.post(f"/api/schedules/{invoice['id']}/run").status_code == 409
    assert client.post("/api/schedules/INV-ghost/run").status_code == 404


def test_schedule_list_returns_scheduled_only():
    invoice = db.put(
        "invoices",
        db.new_id("INV"),
        {"delivery_id": "DEL-003", "store_id": "store-c", "items": [],
         "amount_usdc": 35.0, "status": "scheduled", "tx_sig": None},
    )
    listed = client.get("/api/schedules").json()["scheduled"]
    assert invoice["id"] in {d["id"] for d in listed}
    assert all(d["status"] == "scheduled" for d in listed)
