"""운영 조치 — 시뮬 시절 미결 보관, 운영자금 이동. 지우지 않고, 매출로 세지 않는다."""

import pytest
from fastapi.testclient import TestClient

from app.core import ops, status
from app.db import store as db
from app.main import app

client = TestClient(app)


def _inv(inv_id, store_id, st, born, amount=2.0):
    db.put("invoices", inv_id, {"id": inv_id, "store_id": store_id, "status": st,
                                "amount_usdc": amount, "created_at": born})


def test_archive_moves_only_sim_era_open_invoices():
    _inv("INV-T-OLD1", "store-b", "scheduled", "2026-08-25T00:00:00+00:00")
    _inv("INV-T-OLD2", "store-c", "pending_approval", "2026-08-25T00:00:00+00:00")
    _inv("INV-T-OLDPAID", "store-b", "settled", "2026-08-25T00:00:00+00:00")
    _inv("INV-T-NEW", "store-b", "scheduled", "2026-10-01T00:00:00+00:00")

    preview = ops.archive_sim_era(dry_run=True)
    assert db.get("invoices", "INV-T-OLD1")["status"] == "scheduled", "미리보기는 바꾸지 않는다"
    assert preview["count"] >= 2

    ops.archive_sim_era(dry_run=False)
    old = db.get("invoices", "INV-T-OLD1")
    assert old["status"] == "archived" and old["archived_from"] == "scheduled"
    assert db.get("invoices", "INV-T-OLD2")["status"] == "archived"
    assert db.get("invoices", "INV-T-OLDPAID")["status"] == "settled", "끝난 청구서는 그대로"
    assert db.get("invoices", "INV-T-NEW")["status"] == "scheduled", "대회 기간 청구서는 그대로"


def test_archived_is_not_receivable_or_actionable():
    assert not status.is_receivable("archived")
    assert "archived" not in status.ACTIONABLE
    assert "archived" in status.LABELS


def test_fund_store_validates_and_logs(monkeypatch):
    monkeypatch.setattr("app.core.ops.payments.balance", lambda w: {"address": f"{w}-ADDR"})
    sent = {}
    monkeypatch.setattr("app.core.ops.payments.pay",
                        lambda frm, to, amt, memo: sent.update(frm=frm, to=to, amt=amt, memo=memo) or {"signature": "SIG"})
    with pytest.raises(ValueError):
        ops.fund_store("store-z", 5, "nope")
    with pytest.raises(ValueError):
        ops.fund_store("store-b", 500, "too much")
    out = ops.fund_store("store-b", 20, "restart restocking")
    assert sent == {"frm": "hq", "to": "store-b-ADDR", "amt": 20, "memo": ops.CAPITAL_MEMO}
    assert out["tx"] == "SIG"
    assert any(m["store_id"] == "store-b" and m["amount_usdc"] == 20 for m in ops.capital_moves())


def test_ops_endpoints_fail_closed(monkeypatch):
    """관리 토큰이 비어 있어도(라이브 설정) 돈을 옮기는 길은 열리지 않는다."""
    monkeypatch.setattr("app.config.ADMIN_TOKEN", "")
    monkeypatch.setattr("app.config.OPS_TOKEN", "")
    assert client.post("/api/ops/archive-sim-era").status_code == 403
    assert client.post("/api/ops/working-capital",
                       json={"store_id": "store-b", "amount": 5, "reason": "drain"}).status_code == 403
    monkeypatch.setattr("app.config.OPS_TOKEN", "secret")
    assert client.post("/api/ops/archive-sim-era", headers={"X-Ops-Token": "wrong"}).status_code == 401
    ok = client.post("/api/ops/archive-sim-era", headers={"X-Ops-Token": "secret"})
    assert ok.status_code == 200 and ok.json()["dry_run"] is True
