"""정산 어시스턴트(ADK) 테스트 — LLM 호출 없이 도구·가드·조립만 본다.

실제 대화 품질은 라이브에서 확인한다. 여기서 지키는 것: 어시스턴트의 권한이
대시보드 버튼과 정확히 같고(같은 코드), 존재하지 않는 대상에 흔들리지 않는다.
"""

import asyncio

from fastapi.testclient import TestClient

from app.assistant import tools
from app.db import store as db
from app.main import app

client = TestClient(app)


def test_chat_is_disabled_in_mock_mode(monkeypatch):
    monkeypatch.setattr("app.config.LLM_PROVIDER", "mock")
    resp = client.post("/api/assistant/chat", json={"message": "승인 대기 있어?"})
    assert resp.status_code == 503


def test_agent_assembles_with_all_tools():
    """도구 시그니처·독스트링이 ADK 함수 선언으로 변환 가능한지 — 조립 시점에 터진다."""
    from app.assistant.agent import _runner

    runner = _runner()
    assert runner.agent.name == "solply_assistant"
    assert len(tools.ALL) == 8


def test_action_tools_survive_bad_targets():
    """없는 청구서를 승인·실행하라고 해도 예외가 아니라 오류 설명을 돌려준다."""
    assert asyncio.run(tools.approve_payment("INV-ghost"))["error"]
    assert asyncio.run(tools.reject_payment("INV-ghost", "test"))["error"]
    assert asyncio.run(tools.run_scheduled_payment("INV-ghost"))["error"]

    issued = db.put(
        "invoices", db.new_id("INV"),
        {"delivery_id": "DEL-001", "store_id": "store-a", "items": [],
         "amount_usdc": 5.0, "status": "issued", "tx_sig": None},
    )
    assert asyncio.run(tools.approve_payment(issued["id"]))["error"], "대기 상태가 아니면 승인 불가"
    assert asyncio.run(tools.run_scheduled_payment(issued["id"]))["error"], "예약 상태가 아니면 실행 불가"


def test_readonly_tools_return_compact_shapes():
    overview = tools.get_settlement_overview()
    assert {"invoices_by_status", "outstanding_usdc", "recent_invoices"} <= set(overview)

    pending = tools.list_pending_approvals()
    assert all({"id", "store_id", "amount_usdc"} <= set(p) for p in pending)

    credit = tools.get_store_credit("store-c")
    assert credit["credit_score"] >= 85 and "on_time" in credit


def test_provider_errors_never_reach_the_chat_window(monkeypatch):
    """대화창에 공급자 오류 원문(문서 링크·스택)이 뜨면 안 된다 — 짧은 우리말 안내만."""
    from fastapi.testclient import TestClient

    from app import config
    from app.main import app

    monkeypatch.setattr(config, "LLM_PROVIDER", "vertex")

    async def boom(*a, **kw):
        raise RuntimeError("429 RESOURCE_EXHAUSTED ... refer to https://google.github.io/adk-docs/")

    monkeypatch.setattr("app.assistant.agent.chat", boom)
    res = TestClient(app, raise_server_exceptions=False).post(
        "/api/assistant/chat", json={"message": "승인 대기 있어?"}
    )

    assert res.status_code == 502
    detail = res.json()["detail"]
    assert "http" not in detail and "429" not in detail
    assert "다시 물어봐" in detail


def test_transient_model_failure_is_retried(monkeypatch):
    """한 번 흔들렸다고 사용자에게 실패를 보여주지 않는다."""
    import asyncio

    from app.assistant import agent

    calls = {"n": 0}

    async def flaky(session_id, message, user_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("503 UNAVAILABLE")
        return "승인 기다리는 건 하나 있어요."

    real_sleep = asyncio.sleep  # 교체 전에 붙잡아 둔다 (안 그러면 자기 자신을 부른다)
    monkeypatch.setattr(agent, "_turn", flaky)
    monkeypatch.setattr(asyncio, "sleep", lambda _s: real_sleep(0))

    reply = asyncio.run(agent.chat("s", "승인 대기 있어?"))
    assert calls["n"] == 2 and reply.startswith("승인 기다리는")
