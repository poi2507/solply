"""A2A 경량판 — 명함이 사실을 말하고, message/send가 그래프 실행으로 번역되는지.

지키는 것:
  - 명함의 skills = 그래프 라우팅 테이블 (명함에 없는 스킬은 부를 수 없고,
    그래프에 없는 스킬을 명함에 적으면 거짓말이다)
  - 수신 한 통 = 그래프 한 판 + a2a.message 실행 증빙
  - 발신 클라이언트가 네트워크 왕복 그대로 동작한다 (ASGI 직결로 검증)
"""

import asyncio

import httpx
from fastapi.testclient import TestClient

from app.a2a import card
from app.a2a import client as a2a_client
from app.db import store as db
from app.main import app

client = TestClient(app)


def test_agent_cards_state_real_skills():
    r = client.get("/a2a/hq/.well-known/agent-card.json")
    assert r.status_code == 200
    hq = r.json()
    assert {s["id"] for s in hq["skills"]} == set(card.HQ_SKILLS)
    assert hq["url"].endswith("/a2a/hq")

    rb = client.get("/a2a/store-b/.well-known/agent-card.json")
    assert rb.status_code == 200
    assert {s["id"] for s in rb.json()["skills"]} == set(card.STORE_SKILLS)


def test_card_skills_match_graph_routes():
    """명함과 그래프 라우팅 테이블이 갈라지면 명함이 거짓말이 된다."""
    from app.agents.hq import node as hq_node
    from app.agents.store import node as store_node

    assert set(card.HQ_SKILLS) == set(hq_node._INTENT_ROUTE)
    pay_intents = {"invoice.pay_adjusted", "invoice.pay_scheduled",
                   "invoice.pay_installment", "invoice.pay_approved"}
    assert set(card.STORE_SKILLS) == {"invoice.handle", *pay_intents, *store_node._P2P_ROUTE}


def test_unknown_agent_is_404():
    assert client.get("/a2a/store-z/.well-known/agent-card.json").status_code == 404
    assert client.post("/a2a/store-z", json={"jsonrpc": "2.0", "method": "message/send"}).status_code == 404


def test_message_send_runs_graph_and_leaves_evidence():
    """수신 한 통 = 그래프 한 판. store_id는 명함 주인으로 강제된다."""
    body = {
        "jsonrpc": "2.0", "id": "t-1", "method": "message/send",
        "params": {"message": {"kind": "message", "role": "user",
                               "parts": [{"kind": "data", "data": {"intent": "restock.check"}}]}},
    }
    r = client.post("/a2a/store-b", json=body)
    assert r.status_code == 200
    reply = r.json()
    assert reply["id"] == "t-1"
    data = next(p["data"] for p in reply["result"]["parts"] if p["kind"] == "data")
    assert data["outcome"] in ("noop", "negotiating"), "재고 점검은 조달 불필요 또는 직거래 제안으로 끝난다"
    evidence = [e for e in db.list_events() if e["action"] == "a2a.message"]
    assert evidence and evidence[-1]["actor"] == "store-b-agent"
    assert evidence[-1]["payload"]["skill"] == "restock.check"


def test_unsupported_method_is_jsonrpc_error():
    r = client.post("/a2a/hq", json={"jsonrpc": "2.0", "id": "x", "method": "tasks/get", "params": {}})
    assert r.json()["error"]["code"] == -32601


def test_skill_not_on_card_is_rejected():
    """지점 스킬을 hq에 보내면 명함 검증이 막는다 — 명함이 곧 권한 목록."""
    body = {
        "jsonrpc": "2.0", "id": "x", "method": "message/send",
        "params": {"message": {"parts": [{"kind": "data", "data": {"intent": "restock.check"}}]}},
    }
    assert client.post("/a2a/hq", json=body).json()["error"]["code"] == -32602


def test_client_send_round_trips(monkeypatch):
    """발신 클라이언트를 ASGI로 앱에 직결 — 네트워크 없이 실제 왕복 전체를 검증."""
    monkeypatch.setattr(a2a_client, "_TRANSPORT", httpx.ASGITransport(app=app))
    monkeypatch.setattr(a2a_client, "_base", lambda agent_id: "http://a2a.test")

    final = asyncio.run(a2a_client.send("hq", "p2p.review", trade_id="P2P-없는거래"))

    assert final["outcome"] == "noop", "없는 거래 → load_context가 noop으로 끝낸다"
    assert "직거래 건을 찾을 수 없습니다" in " ".join(final.get("messages", []))
