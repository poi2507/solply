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
    [("store-a", 88), ("store-b", 85), ("store-c", 92)],
)
def test_seeded_history_reproduces_known_scores(no_live_history, store_id, expected):
    """점수는 상수가 아니라 이력 계산이다 (B는 F 시나리오를 위해 85로 시드됨)."""
    assert credit.evaluate(store_id)["credit_score"] == expected


def test_live_settlement_raises_the_score(monkeypatch):
    """이번 세션의 온체인 정산이 정시납으로 가산된다 — 데모 중 점수가 오른다."""
    seen = {}

    def counted(collection, **filters):
        seen.update(filters)
        return 2

    # 문서를 다 읽지 않고 '정산 완료' 건수만 세는지도 함께 확인한다
    monkeypatch.setattr("app.db.store.count_docs", counted)
    rating = credit.evaluate("store-a")
    assert rating["live_settled"] == 2
    assert seen == {"store_id": "store-a", "status": "settled"}
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


def test_late_moves_score_even_after_long_clean_history():
    """정시납이 수천 건 쌓여도 연체는 점수에 보여야 한다.

    8/7 라이브: 정시납 누적으로 원점수가 1432라 미수 415 USDC·미결 144건인
    지점도 100점이었다 — 나쁜 이력이 점수에 전혀 닿지 않았다.
    """
    clean = credit.score_from(on_time=5000, late=0, disputed=0)
    with_late = credit.score_from(on_time=5000, late=10, disputed=0)
    assert clean == 100
    assert with_late < clean, "정시납 가산에 상한이 없으면 연체가 묻힌다"


def test_overdue_count_ignores_scheduled_invoices():
    """연체는 '납부 계획이 없는' 미결만 센다 — 예약은 날짜를 합의한 건이다.

    (updated_at은 put이 항상 현재로 찍으므로, 과거를 만드는 대신 미래 기준으로
     조회해 상태 필터만 검증한다.)
    """
    from datetime import UTC, datetime, timedelta

    from app.db import store as db

    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    base = db.count_stale("invoices", credit.UNPLANNED, future, store_id="store-a")

    db.put("invoices", "INV-TEST-PLANNED", {
        "id": "INV-TEST-PLANNED", "store_id": "store-a", "status": "scheduled",
        "amount_usdc": 1.0, "items": [],
    })
    assert db.count_stale("invoices", credit.UNPLANNED, future, store_id="store-a") == base, \
        "예약은 연체로 세지 않는다"

    db.put("invoices", "INV-TEST-LATE", {
        "id": "INV-TEST-LATE", "store_id": "store-a", "status": "issued",
        "amount_usdc": 1.0, "items": [],
    })
    assert db.count_stale("invoices", credit.UNPLANNED, future, store_id="store-a") == base + 1, \
        "계획 없는 미결은 연체로 센다"
