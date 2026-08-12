"""무대 장치 — 틱 잠금·협상 재생 트리거·수익 계수기.

지키는 것:
  - 틱은 한 번에 하나만 돈다 (수동+스케줄러 동시 실행이 만든 경합의 재발 방지)
  - 죽은 틱의 잠금은 TTL이 풀어준다 — 잠금이 시스템을 영구 정지시키면 안 된다
  - 협상 재생은 지점 잔액이 넉넉하면 정직하게 거절한다 (조건 없는 목업 금지)
  - 수익 계수기가 로열티·데이터 판매를 그 자리에서 누적하고 overview에 실린다
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.core import stats
from app.db import store as db
from app.main import app

client = TestClient(app)


def test_tick_rejects_concurrent_run(monkeypatch):
    async def fake_tick(rng=None):
        return {"sales": []}
    monkeypatch.setattr("app.api.ticks.economy.tick", fake_tick)

    db.put("locks", "tick", {"started_at": datetime.now(UTC).isoformat()})
    assert client.post("/api/ticks/run").status_code == 409, "실행 중이면 겹치지 않는다"

    stale = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
    db.put("locks", "tick", {"started_at": stale})
    resp = client.post("/api/ticks/run")
    assert resp.status_code == 200, "죽은 틱의 잠금은 TTL이 풀어준다"
    assert db.get("locks", "tick")["started_at"] is None, "끝나면 잠금을 되돌린다"


def test_stage_negotiation_refuses_when_wallet_is_rich(monkeypatch):
    monkeypatch.setattr(
        "app.api.demo.payments.balance",
        lambda w: {"address": f"{w}-ADDR", "usdc": 500.0, "sol": 1},
    )
    resp = client.post("/api/demo/negotiate?store_id=store-b")
    assert resp.status_code == 409, "잔액이 넉넉하면 협상 조건이 없다 — 목업으로 속이지 않는다"


def test_stage_negotiation_fires_real_rounds(monkeypatch):
    monkeypatch.setattr(
        "app.api.demo.payments.balance",
        lambda w: {"address": f"{w}-ADDR", "usdc": 3.0, "sol": 1},
    )
    sent = []

    async def fake_send(agent_id, intent, **kwargs):
        sent.append((agent_id, intent))
        return {"outcome": "negotiating"}
    monkeypatch.setattr("app.api.demo.a2a.send", fake_send)

    async def fake_negotiate(store_id, invoice_id):
        sent.append(("economy", "negotiate"))
        return "installments_agreed"
    monkeypatch.setattr("app.api.demo.economy._negotiate_deferral", fake_negotiate)

    resp = client.post("/api/demo/negotiate?store_id=store-b")

    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "installments_agreed"
    assert sent[0] == ("store-b", "invoice.handle"), "무대도 실제 그래프 경로를 탄다"
    assert sent[1] == ("economy", "negotiate")
    invoice = db.get("invoices", body["invoice_id"])
    assert invoice["amount_usdc"] == 9.5, "권한(상한 10)은 통과하고 능력(잔액 3)은 시험하는 금액"


def test_revenue_counter_accumulates_and_shows_in_overview():
    before = stats.snapshot().get("data_sales_usdc", 0.0)
    stats.add("data_sales", 0.1)
    stats.add("data_sales", 0.1)
    assert stats.snapshot()["data_sales_usdc"] == round(before + 0.2, 2)

    ov = client.get("/api/overview").json()
    assert "hqRevenue" in ov and "dataStore" in ov
    assert ov["dataStore"]["priceUsdc"] > 0


def test_card_flow_counter_preserves_guest_inflow():
    """카드정산 계수가 손님 유입을 지우면 안 된다 — 문서 덮어쓰기 회귀 가드 (8/12 실측)."""
    from app.core import kst, stats

    stats.add_guest_flow("store-a", 1.0)
    stats.add_card_flow("store-a", 3.0, 1.0)

    doc = db.get("stats", f"flows-{kst.today()}")
    assert doc["guest_usdc"] >= 1.0, "카드 계수 뒤에도 손님 유입이 남아야 한다"
    assert doc["guest"]["store-a"] >= 1.0, "지점별 손님 유입도 보존"
    assert doc["card"]["store-a"] >= 3.0


def test_overview_carries_flow_aggregates():
    """자금 흐름 다이어그램의 재료 — 카드정산은 이벤트 스캔이 아니라 계수기로."""
    stats.add_card_flow("store-a", 3.0, 1.0)
    ov = client.get("/api/overview").json()
    flows = ov["flows"]
    assert flows["card"].get("store-a", 0) >= 3.0
    assert flows["royaltyUsdc"] >= 1.0
    assert {"dataUsdc", "dataCount"} <= set(flows)
