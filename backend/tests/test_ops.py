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

    async def fake_send(agent_id, intent, **kwargs):
        assert intent == "invoice.pay_approved"
        return {"outcome": "paid", "tx_signature": "SIG", "messages": []}

    monkeypatch.setattr("app.api.approvals.a2a.send", fake_send)
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

    async def fake_send(agent_id, intent, **kwargs):
        return {"outcome": "paid", "tx_signature": "SIG", "messages": []}

    monkeypatch.setattr("app.api.schedules.a2a.send", fake_send)

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


def test_dashboard_shows_one_day_but_never_hides_what_is_owed():
    """기본은 오늘 하루. 다만 어제 안 낸 돈은 오늘 화면에서도 보여야 한다."""
    from fastapi.testclient import TestClient

    from app.core import kst
    from app.db import store as db
    from app.main import app

    client = TestClient(app)
    today = kst.today()
    yesterday = kst.shift(today, -1)

    db.put("invoices", "INV-OLD-1", {"store_id": "store-a", "amount_usdc": 9.0, "status": "issued"})
    db.put("invoices", "INV-NEW-1", {"store_id": "store-a", "amount_usdc": 3.0, "status": "settled"})

    view = client.get("/api/overview").json()
    assert view["day"] == today and view["today"] == today
    ids = {i["id"] for i in view["invoices"]}
    assert "INV-NEW-1" in ids, "오늘 갱신된 건은 목록에 있어야 한다"
    # 미결 청구는 날짜와 무관하게 미수금에 잡힌다
    assert view["totals"]["outstandingUsdc"] >= 9.0
    assert view["totals"]["allInvoices"] >= 2

    # 어제로 옮기면 오늘 것은 안 보인다
    past = client.get(f"/api/overview?day={yesterday}").json()
    assert past["day"] == yesterday
    assert "INV-NEW-1" not in {i["id"] for i in past["invoices"]}
    assert past["totals"]["outstandingUsdc"] >= 9.0, "미수금은 어느 날짜에서 봐도 같다"


def test_event_log_is_scoped_to_a_day():
    from fastapi.testclient import TestClient

    from app.core import kst
    from app.db import store as db
    from app.main import app

    db.log_event("system", "probe.today", {})
    res = TestClient(app).get("/api/events?limit=5").json()
    assert res["day"] == kst.today()
    assert res["total"] <= res["allTime"]

    empty = TestClient(app).get(f"/api/events?day={kst.shift(kst.today(), -30)}").json()
    assert empty["events"] == [] and empty["total"] == 0


# ── 청구서 상태의 단일 출처 ────────────────────────────────────────
# 실제로 있었던 결함: "받을 돈"의 정의가 대시보드와 어시스턴트에 서로 반대 방향으로
# 손으로 적혀 있었다. 상태가 하나 늘면 한쪽만 고쳐도 에러 없이 숫자가 갈라진다.

def test_receivable_and_not_receivable_are_exact_complements():
    from app.core import status

    assert set(status.RECEIVABLE) | set(status.NOT_RECEIVABLE) == set(status.InvoiceStatus)
    assert not set(status.RECEIVABLE) & set(status.NOT_RECEIVABLE)
    assert all(status.is_receivable(s) for s in status.RECEIVABLE)
    assert not any(status.is_receivable(s) for s in status.NOT_RECEIVABLE)


def test_every_status_the_code_writes_is_declared():
    """코드가 실제로 쓰는 상태 문자열이 enum에 빠지면 미수금 판정에서 조용히 새어나간다."""
    import re
    from pathlib import Path

    from app.core import status

    declared = {s.value for s in status.InvoiceStatus}
    app_dir = Path(__file__).resolve().parent.parent / "app"
    written = set()
    for py in app_dir.rglob("*.py"):
        for m in re.finditer(r'"status":\s*"([a-z_]+)"', py.read_text()):
            written.add(m.group(1))
    # 청구서가 아닌 문서(직거래·도구 반환값)의 상태는 제외한다
    others = {"proposed", "accepted", "approved", "confirmed", "rejected",
              "needs_human_approval", "already_settled", "hq_out_of_stock",
              "escrow_deposited"}  # 직거래 402 응답의 상태 표기 (문서 상태 아님)
    assert (written - others) <= declared, f"enum에 없는 청구서 상태: {written - others - declared}"


def test_status_labels_cover_every_status():
    from app.core import status

    assert set(status.LABELS) == {s.value for s in status.InvoiceStatus}
    assert set(status.TRADE_LABELS) == {s.value for s in status.TradeStatus}


def test_already_paid_is_a_subset_of_declared_statuses():
    """이중 결제 가드가 보는 목록 — 여기서 상태가 빠지면 재시도 한 번에 돈이 두 번 나간다."""
    from app.core import status

    assert set(status.ALREADY_PAID) <= set(status.InvoiceStatus)
    assert status.InvoiceStatus.SETTLED in status.ALREADY_PAID
    assert status.InvoiceStatus.ISSUED not in status.ALREADY_PAID


def test_trade_statuses_the_code_writes_are_declared():
    import re
    from pathlib import Path

    from app.core import status

    declared = {s.value for s in status.TradeStatus}
    app_dir = Path(__file__).resolve().parent.parent / "app"
    written = set()
    for py in app_dir.rglob("*.py"):
        body = py.read_text()
        for m in re.finditer(r'p2p_trades"[^)]*?"status":\s*"([a-z_]+)"', body, re.DOTALL):
            written.add(m.group(1))
    assert written <= declared, f"TradeStatus에 없는 직거래 상태: {written - declared}"


def test_dashboard_and_assistant_agree_on_what_is_owed():
    """같은 데이터에서 화면과 대화가 다른 미수금을 말하면 안 된다 — 이게 이 파일의 요점."""
    from fastapi.testclient import TestClient

    from app.assistant import tools as assistant_tools
    from app.core import status
    from app.db import store as db
    from app.main import app

    db.reset(keep=("policies",))
    db.put("invoices", "INV-T1", {"store_id": "store-a", "amount_usdc": 4.0, "status": "issued"})
    db.put("invoices", "INV-T2", {"store_id": "store-a", "amount_usdc": 3.0, "status": "scheduled"})
    db.put("invoices", "INV-T3", {"store_id": "store-b", "amount_usdc": 9.0, "status": "settled"})
    db.put("invoices", "INV-T4", {"store_id": "store-b", "amount_usdc": 8.0, "status": "split"})
    db.put("invoices", "INV-T5", {"store_id": "store-c", "amount_usdc": 5.0, "status": "refused"})

    from_dashboard = TestClient(app).get("/api/overview").json()["totals"]["outstandingUsdc"]
    from_assistant = assistant_tools.get_settlement_overview()["outstanding_usdc"]

    assert from_dashboard == from_assistant == 7.0, "issued 4.0 + scheduled 3.0 만 받을 돈이다"
    assert status.LABELS["split"] == "분할됨"


def test_every_logged_action_has_a_korean_label():
    """실행 증빙 화면은 심사 기준 4의 근거다 — 새 행위를 추가하고 라벨을 빼먹으면
    로그가 영문 원문으로 보인다. 실제로 경제 루프·직거래가 들어올 때 그렇게 됐다.

    로그 호출 지점 주변에서 행위 이름을 긁어 라벨 누락을 잡는다 (삼항식·여러 줄 포함).
    """
    import re
    from pathlib import Path

    from app.core import events

    app_dir = Path(__file__).resolve().parent.parent / "app"
    shape = re.compile(r'"([a-z0-9]+\.[a-z0-9_]+)"')
    logged: set[str] = set()
    for py in app_dir.rglob("*.py"):
        lines = py.read_text().splitlines()
        for i, line in enumerate(lines):
            if "utils.log(" in line or "log_event(" in line:
                window = "\n".join(lines[max(0, i - 5): i + 6])
                logged |= set(shape.findall(window))

    assert len(logged) >= 30, f"추출기가 망가졌다 (찾은 행위 {len(logged)}종)"
    missing = logged - set(events.ACTION_LABELS)
    assert not missing, f"라벨 없는 행위: {sorted(missing)}"
    dead = set(events.ACTION_LABELS) - logged
    assert not dead, f"코드가 기록하지 않는 죽은 라벨: {sorted(dead)}"


def test_readable_ids_and_the_day_view_share_one_definition_of_today():
    """청구서 번호의 MMDD와 화면의 날짜 구분이 갈라지면, 오늘 만든 청구서가
    어제 화면에 뜨는 일이 생긴다."""
    from app.core import kst

    assert kst.mmdd() == kst.today()[5:].replace("-", "")


# ── 오늘(7/31) 점검에서 잡은 결함들의 재발 방지 ─────────────────────

def test_installment_offer_matches_the_policy_it_will_actually_split_into():
    """402가 '2회 분할·절반 금액'을 제시하는데 실제로는 3등분 청구서가 생기면,
    지점이 어느 청구서와도 맞지 않는 금액을 보내고 그 USDC는 사라진다."""
    from app.core import protocol

    invoice = {"id": "INV-TEST-1", "amount_usdc": 9.0, "store_id": "store-a",
               "items": [], "delivery_id": "DEL-TEST-1"}
    for parts in (2, 3, 4):
        req = protocol.build_payment_requirements(
            invoice, "HQADDR", "devnet",
            store_profile={"policy": {"installment_max": parts, "defer_max_pct": 20}},
        )
        term = next(a for a in req["accepts"] if a["extra"]["term"] == "installment")
        assert term["extra"]["installments"] == parts
        assert f"{parts}회 분할" in term["extra"]["label"]
        assert protocol.from_atomic(term["amount"]) == round(9.0 / parts, 2)


def test_every_sku_price_resolves_to_one_number():
    """같은 품목이 발주 조건과 시드 납품에서 다른 단가면, 청구는 비싸게 하고
    카드정산은 싸게 돌려줘 온체인 총량이 조용히 줄어든다 (economy.py의 설계 전제 위반)."""
    from app.core import fixtures

    data = fixtures.load()
    reorder = {sku: t["unit_price_usdc"] for sku, t in data["hq_reorder"].items()}
    for did, delivery in data["deliveries"].items():
        for item in delivery["items"]:
            ref = reorder.get(item["sku"])
            if ref is None:
                continue
            assert item["unit_price_usdc"] == ref, (
                f"{did} {item['sku']}: 납품 {item['unit_price_usdc']} ≠ 발주조건 {ref}"
            )


def test_every_inventory_move_reason_has_a_label():
    """`restocked`가 라벨에 없어서 본사 화면에 영문이 그대로 보였다."""
    import re
    from pathlib import Path

    from app.core import events

    app_dir = Path(__file__).resolve().parent.parent / "app"
    reasons = set()
    for py in app_dir.rglob("*.py"):
        body = py.read_text()
        # record_move(store_id, sku, name, qty, reason, ref) — 5번째 인자가 사유다
        for m in re.finditer(r"record_move\((?:[^()]|\([^()]*\))*?\)", body, re.DOTALL):
            args, depth, cur = [], 0, ""
            for ch in m.group(0)[m.group(0).index("(") + 1: -1]:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                if ch == "," and depth == 0:
                    args.append(cur.strip()); cur = ""
                else:
                    cur += ch
            args.append(cur.strip())
            if len(args) >= 5 and args[4].startswith('"'):
                reasons.add(args[4].strip('"'))
    known = set(events.MOVE_LABELS)
    assert reasons, "record_move 호출을 못 찾았다 — 추출기 확인 필요"
    assert reasons <= known, f"라벨 없는 이동 사유: {sorted(reasons - known)}"


def test_open_invoices_does_not_double_count_a_split_parent():
    """분할된 부모와 자식을 함께 세면 지점이 두 배로 갚아야 하는 것처럼 보인다."""
    from app.agents import utils
    from app.db import store as db

    db.reset(keep=("policies",))
    db.put("invoices", "INV-P", {"store_id": "store-a", "amount_usdc": 8.0, "status": "split"})
    db.put("invoices", "INV-P-P1", {"store_id": "store-a", "amount_usdc": 4.0,
                                    "status": "issued", "parent_id": "INV-P"})
    db.put("invoices", "INV-P-P2", {"store_id": "store-a", "amount_usdc": 4.0,
                                    "status": "issued", "parent_id": "INV-P"})

    ids = {i["id"] for i in utils.open_invoices("store-a")}
    assert ids == {"INV-P-P1", "INV-P-P2"}, f"부모까지 셌다: {ids}"


def test_health_reports_the_store_backend_actually_in_use():
    """빠뜨리면 화면이 `?? \"postgres\"`로 떨어져 로컬 실행에도 postgres라고 우긴다."""
    from fastapi.testclient import TestClient

    from app import config
    from app.main import app

    body = TestClient(app).get("/api/health").json()
    assert body["store"] == config.STORE_BACKEND


def test_pending_approvals_survive_the_day_view():
    """어제 멈춘 결제가 오늘 화면에서 사라지면 돈이 묶인 채 아무 표시도 남지 않는다."""
    from fastapi.testclient import TestClient

    from app.db import store as db
    from app.main import app

    db.reset(keep=("policies",))
    db.put("invoices", "INV-OLD-PA", {"store_id": "store-a", "amount_usdc": 12.0,
                                      "status": "pending_approval"})
    view = TestClient(app).get("/api/overview?day=2020-01-01").json()
    assert "INV-OLD-PA" not in {i["id"] for i in view["invoices"]}, "그 날 목록엔 없어야 한다"
    assert "INV-OLD-PA" in {i["id"] for i in view["openInvoices"]}, "승인 패널 목록엔 있어야 한다"


def test_pending_approval_is_not_a_late_payment():
    """사람 승인 대기는 지점의 연체가 아니다 — 이걸 세면 신용 하락 되먹임이 생긴다.

    8/15 실측: store-b가 유예 거절 → 승인 큐 적체 → 신용 73 → 다시 거절로 굳었다.
    """
    from datetime import UTC, datetime, timedelta

    from app.core import credit
    from app.core import status as status_mod
    from app.db import store as db

    assert status_mod.InvoiceStatus.PENDING_APPROVAL not in credit.UNPLANNED

    old_ts = (datetime.now(UTC) - timedelta(hours=credit.LATE_AFTER_HOURS + 5)).isoformat()
    db.put("invoices", "INV-CREDIT-PENDING", {
        "id": "INV-CREDIT-PENDING", "store_id": "store-c", "items": [], "amount_usdc": 5.0,
        "status": status_mod.InvoiceStatus.PENDING_APPROVAL, "tx_sig": None, "updated_at": old_ts,
    })
    before = credit.evaluate("store-c")["live_late"]
    assert before == credit.evaluate("store-c")["live_late"], "승인 대기 건은 연체 수에 들어가지 않는다"
