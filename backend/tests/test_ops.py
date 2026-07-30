"""운영 견고성 테스트 — 이중 결제 방지, 분할 역제안, 사람 승인, 정산 리포트."""

import pytest
from fastapi.testclient import TestClient

from app.agents.hq import tools as hq_tools
from app.agents.store import tools as store_tools
from app.db import store as db
from app.llm import rules
from app.main import app

client = TestClient(app)


def make_invoice(status: str = "issued", amount: float = 35.0, store_id: str = "store-b") -> dict:
    return db.put(
        "invoices",
        db.new_id("INV"),
        {"delivery_id": "DEL-002", "store_id": store_id, "items": [],
         "amount_usdc": amount, "status": status, "tx_sig": None},
    )


# ── 이중 결제 방지 ───────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["paid", "settled"])
def test_already_paid_invoice_cannot_be_paid_again(monkeypatch, status):
    monkeypatch.setattr("app.solana.payments.pay", lambda *a: pytest.fail("돈이 두 번 나가면 안 된다"))
    invoice = make_invoice(status=status)
    result = store_tools.execute_payment(invoice["store_id"], invoice["id"])
    assert result.get("error")


# ── 분할 역제안 (멀티턴) ─────────────────────────────────────────────

def test_split_invoice_creates_installments():
    invoice = make_invoice(amount=42.5)
    result = hq_tools.split_invoice(invoice["id"], parts=2)

    children = result["children"]
    assert [c["amount_usdc"] for c in children] == [21.25, 21.25]
    assert children[0]["status"] == "issued" and children[1]["status"] == "scheduled"
    assert all(c["parent_id"] == invoice["id"] for c in children)
    assert db.get("invoices", invoice["id"])["status"] == "split"


def test_split_handles_odd_amounts_without_losing_a_cent():
    invoice = make_invoice(amount=33.33)
    children = hq_tools.split_invoice(invoice["id"], parts=2)["children"]
    assert round(sum(c["amount_usdc"] for c in children), 2) == 33.33


def test_split_refuses_settled_invoice():
    invoice = make_invoice(status="settled")
    assert hq_tools.split_invoice(invoice["id"])["error"]


def test_deferral_over_exposure_counters_with_installment():
    """유예액이 외상 한도 비율을 넘으면 거절이 아니라 분할 역제안이어야 한다."""
    verdict = rules.review_deferral(
        {"credit_score": 87, "amount_usdc": 42.5, "credit_limit_usdc": 150,
         "pay_when": "금요일", "history": "정시납 20건"},
        {"min_credit_score": 85, "defer_max_pct": 20},
    )
    assert verdict["decision"] == "counter"


def test_scenario_f_data_is_in_the_counter_window():
    """F 시나리오 데이터 가드 — DEL-005가 '상한 이하 + 한도 비율 초과' 창에 있어야 한다."""
    from app.agents import utils
    from app.core import credit, fixtures

    data = fixtures.load()
    amount = utils.line_total(data["deliveries"]["DEL-005"]["items"])
    assert amount <= 50, "자동결제 상한을 넘으면 유예가 아니라 에스컬레이션으로 빠진다"
    assert amount / data["stores"]["store-b"]["credit_limit_usdc"] * 100 > 20, "한도 비율을 넘어야 역제안"

    hist = data["payment_history"]["store-b"]
    seeded = credit.BASE + credit.ON_TIME_POINTS * hist["on_time"] - credit.LATE_PENALTY * hist["late"]
    assert seeded >= 85, "신용 미달이면 역제안 전에 거절된다"


def test_pay_approved_intent_bypasses_limit_but_not_wallet():
    from app.agents.store import node

    assert node.route_after_context({"intent": "invoice.pay_approved"}) == "request_terms"
    assert node.route_after_cashflow({"intent": "invoice.pay_approved", "cashflow": {}}) == "pay"


# ── 사람 승인 ────────────────────────────────────────────────────────

def test_human_approval_resumes_the_agent(monkeypatch):
    invoice = make_invoice(status="pending_approval", amount=80.0)

    async def fake_run(agent, intent, **kwargs):
        assert intent == "invoice.pay_approved"
        return {"outcome": "paid", "tx_signature": "SIG", "messages": []}

    monkeypatch.setattr("app.api.approvals.runner.run", fake_run)
    resp = client.post(f"/api/approvals/{invoice['id']}/decide", json={"decision": "approve"})

    assert resp.status_code == 200
    assert resp.json()["outcome"] == "paid"
    event = [e for e in db.list_events() if e["action"] == "human.approved"][-1]
    assert event["actor"] == "human" and event["payload"]["invoice_id"] == invoice["id"]


def test_human_rejection_closes_the_invoice():
    invoice = make_invoice(status="pending_approval", amount=80.0)
    resp = client.post(f"/api/approvals/{invoice['id']}/decide", json={"decision": "reject"})
    assert resp.status_code == 200
    assert db.get("invoices", invoice["id"])["status"] == "refused"
    assert [e for e in db.list_events() if e["action"] == "human.rejected"]


def test_approval_guards_status_and_existence():
    invoice = make_invoice(status="issued")
    assert client.post(f"/api/approvals/{invoice['id']}/decide", json={"decision": "approve"}).status_code == 409
    assert client.post("/api/approvals/INV-ghost/decide", json={"decision": "approve"}).status_code == 404


# ── 청구서 번호는 사람이 읽는다 ──────────────────────────────────────

def test_invoice_ids_are_human_readable():
    """INV-0729-B01 — 화면·영상·온체인 memo에서 그대로 읽히는 번호."""
    import re

    invoice = hq_tools.create_invoice("DEL-002")
    assert re.fullmatch(r"INV-\d{4}-B\d{2,}", invoice["id"]), invoice["id"]

    second = hq_tools.create_invoice("DEL-002")
    assert second["id"] != invoice["id"], "같은 지점 연속 발행도 번호가 겹치면 안 된다"


# ── 대시보드 정합성 ──────────────────────────────────────────────────

def test_outstanding_excludes_split_and_refused():
    """미수금은 받을 돈만 — 분할 원본은 자식과 이중 계산, 거부 건은 채권이 아니다."""
    make_invoice(status="split", amount=42.5)
    make_invoice(status="refused", amount=75.0)
    ov = client.get("/api/overview").json()

    expected = round(
        sum(i["amount_usdc"] for i in ov["invoices"]
            if i["status"] not in ("settled", "split", "refused")), 2,
    )
    assert ov["totals"]["outstandingUsdc"] == expected
    assert ov["totals"]["outstandingCount"] == sum(
        1 for i in ov["invoices"] if i["status"] not in ("settled", "split", "refused")
    )


def test_installment_challenge_offers_immediate_only():
    """합의된 분할 회차의 402에는 유예·재분할을 다시 제시하지 않는다."""
    from app.core import protocol

    child = {
        "id": "INV-x-P1", "store_id": "store-b", "delivery_id": "DEL-005",
        "items": [], "amount_usdc": 21.25, "installment": "1/2",
    }
    req = protocol.build_payment_requirements(child, "HQWALLET", "localnet", None)
    assert [a["extra"]["term"] for a in req["accepts"]] == ["immediate"]
    assert "1/2" in req["accepts"][0]["extra"]["label"]


# ── 프론트 운영 기능: 정책 감사·예약 실행·재고 노출 ──────────────────

def test_policy_change_leaves_audit_trail():
    """규칙 변경도 결제와 같은 무게 — 무엇이 얼마에서 얼마로 바뀌었는지 남는다."""
    current = {f["key"]: f["value"] for f in client.get("/api/policy/store-c").json()["fields"]}
    changed = current["auto_pay_limit_usdc"] + 1

    client.put("/api/policy/store-c", json={"values": {"auto_pay_limit_usdc": changed}})
    event = [e for e in db.list_events() if e["action"] == "policy.updated"][-1]
    assert event["actor"] == "human"
    assert event["payload"]["changes"]["auto_pay_limit_usdc"] == {
        "from": current["auto_pay_limit_usdc"], "to": changed,
    }

    before_count = len([e for e in db.list_events() if e["action"] == "policy.updated"])
    client.put("/api/policy/store-c", json={"values": {"auto_pay_limit_usdc": changed}})
    after_count = len([e for e in db.list_events() if e["action"] == "policy.updated"])
    assert after_count == before_count, "값이 그대로면 이벤트를 남기지 않는다"

    client.put("/api/policy/store-c", json={"values": current})  # 원상 복구


def test_schedule_run_can_simulate_inflow(monkeypatch):
    """대시보드 '지금 실행'은 예약일의 카드정산 입금까지 시간을 당긴다."""
    invoice = make_invoice(status="scheduled", amount=35.0, store_id="store-c")
    inflows = []

    monkeypatch.setattr(
        "app.api.schedules.payments.balance",
        lambda w: {"address": f"{w}-ADDR", "usdc": 5.0, "sol": 1},
    )
    monkeypatch.setattr(
        "app.api.schedules.payments.pay",
        lambda src, to, amount, memo: inflows.append((src, to, amount, memo)) or {"signature": "S"},
    )

    async def fake_run(agent, intent, **kwargs):
        return {"outcome": "paid", "tx_signature": "SIG", "messages": []}

    monkeypatch.setattr("app.api.schedules.runner.run", fake_run)

    resp = client.post(f"/api/schedules/{invoice['id']}/run", json={"simulate_inflow": True})
    assert resp.status_code == 200
    assert inflows and inflows[0][0] == "hq" and inflows[0][3] == "CARD-SETTLEMENT"
    # 청구액 + 하한 − 잔액 만 채운다 (반복해도 잔액이 불어나지 않는 양).
    # 하한은 데모 금액 규모에 따라 바뀌므로 정책에서 읽는다 — 숫자를 박으면 같이 깨진다.
    from app.core import policy as policy_mod

    reserve = policy_mod.get("store-c").min_reserve_usdc
    assert inflows[0][2] == 35.0 + reserve - 5.0


def test_overview_exposes_store_inventory():
    ov = client.get("/api/overview").json()
    store_a = next(s for s in ov["stores"] if s["id"] == "store-a")
    chick = next(i for i in store_a["inventory"] if i["sku"] == "CHK-10")
    assert {"sku", "name", "qty", "safety"} <= set(chick)


# ── 정산 리포트 ──────────────────────────────────────────────────────

def test_report_stats_and_mock_narration(monkeypatch):
    monkeypatch.setattr(
        "app.core.report.db.list_docs",
        lambda collection, **k: {
            "invoices": [
                {"status": "settled", "amount_usdc": 35.0},
                {"status": "settled", "amount_usdc": 32.5},
                {"status": "refused", "amount_usdc": 75.0},
                {"status": "scheduled", "amount_usdc": 21.25},
            ],
            "negotiations": [{"decision": "accept"}, {"decision": "counter"}],
            "p2p_trades": [{"status": "confirmed", "price_usdc": 10.0}],
        }[collection],
    )
    from app.core import report as report_mod

    stats = report_mod.collect()
    assert stats["settled_count"] == 2 and stats["settled_usdc"] == 67.5
    assert stats["negotiations"] == {"accept": 1, "counter": 1}
    assert stats["p2p_count"] == 1

    text = rules.weekly_report(stats)
    assert "2건" in text and "67.5" in text and "직거래 1건" in text


def test_event_log_reads_only_what_it_shows():
    """로그가 수천 건 쌓여도 화면 조회는 요청한 건수만 읽어야 한다 (SSE·지표 병목 방지)."""
    from app.db import store as db

    for i in range(30):
        db.log_event("human" if i % 10 == 0 else "system", "probe", {"i": i})

    recent = db.recent_events(5)
    assert len(recent) == 5
    assert recent[0]["payload"]["i"] > recent[-1]["payload"]["i"], "최신순이어야 한다"
    assert db.count_events(actor="human") >= 3
    assert db.count_events() >= 30

    cursor = db.count_events()
    db.log_event("system", "probe", {"i": 999})
    fresh = db.events_after(cursor)
    assert [e["payload"]["i"] for e in fresh] == [999], "커서 이후 새 이벤트만"
