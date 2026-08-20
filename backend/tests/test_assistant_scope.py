"""어시스턴트 조회 범위 — 점주는 자기 지점만, 승인·반려는 본사만.

8/20 발견: 도구가 owner를 몰라 점주 화면에서도 전 지점 청구서·신용점수가 조회됐다.
범위는 도구 인자가 아니라 요청 컨텍스트(scope)로 주입된다 — 인자로 두면 LLM이
임의 값을 채워 남의 지점을 열 수 있기 때문이다. 그 주입이 실제로 먹는지 검사한다.
"""

import asyncio

from app.assistant import scope, tools
from app.db import store as db


def _seed(invoice_id: str, store_id: str, status: str = "issued") -> None:
    db.put("invoices", invoice_id, {
        "id": invoice_id, "store_id": store_id, "status": status,
        "amount_usdc": 1.0, "items": [],
    })


def _as(owner: str, fn):
    token = scope.bind(owner)
    try:
        return fn()
    finally:
        scope.reset(token)


def test_store_sees_only_own_invoices():
    """본사에는 보이는 C지점 청구서가 B지점 창구에서는 사라진다."""
    _seed("INV-SCOPE-C1", "store-c")
    _seed("INV-SCOPE-B1", "store-b")

    seen_by_hq = {i["id"] for i in _as("hq", tools.get_settlement_overview)["recent_invoices"]}
    assert "INV-SCOPE-C1" in seen_by_hq, "본사는 전 지점을 본다 (검사 전제)"

    mine = _as("store-b", tools.get_settlement_overview)["recent_invoices"]
    assert "INV-SCOPE-C1" not in {i["id"] for i in mine}
    assert all(i["store_id"] == "store-b" for i in mine)


def test_store_cannot_read_other_store_credit():
    assert "error" in _as("store-b", lambda: tools.get_store_credit("store-c"))
    assert "error" not in _as("store-b", lambda: tools.get_store_credit("store-b"))
    assert "error" not in _as("hq", lambda: tools.get_store_credit("store-c"))


def test_weekly_report_is_hq_only():
    """주간 리포트에는 전 지점 신용·사람 개입 통계가 들어 있다."""
    assert "error" in _as("store-b", tools.get_weekly_report)
    assert "error" not in _as("hq", tools.get_weekly_report)


def test_approvals_are_hq_action():
    assert "error" in _as("store-b", lambda: asyncio.run(tools.approve_payment("INV-X")))
    assert "error" in _as("store-b", lambda: asyncio.run(tools.reject_payment("INV-X", "이유")))


def test_pending_and_scheduled_are_scoped():
    _seed("INV-SCOPE-C2", "store-c", "pending_approval")
    _seed("INV-SCOPE-C3", "store-c", "scheduled")

    assert "INV-SCOPE-C2" in {d["id"] for d in _as("hq", tools.list_pending_approvals)}
    assert "INV-SCOPE-C2" not in {d["id"] for d in _as("store-b", tools.list_pending_approvals)}
    assert "INV-SCOPE-C3" not in {d["id"] for d in _as("store-b", tools.list_scheduled_payments)}


def test_scheduled_run_rejects_other_store():
    _seed("INV-SCOPE-C4", "store-c", "scheduled")
    assert "error" in _as("store-b", lambda: asyncio.run(tools.run_scheduled_payment("INV-SCOPE-C4")))


def test_unbound_context_sees_nothing():
    """주입이 빠지면 본사로 열리는 게 아니라 아무것도 안 보여야 한다 (fail-closed)."""
    _seed("INV-SCOPE-C5", "store-c")
    # conftest가 본사로 묶어두므로 주입되지 않은 상태를 명시적으로 되돌린다
    token = scope.bind("unbound")
    try:
        assert not scope.is_hq(), "기본값은 본사가 아니다"
        assert tools.get_settlement_overview()["recent_invoices"] == []
        assert "error" in tools.get_weekly_report()
    finally:
        scope.reset(token)
