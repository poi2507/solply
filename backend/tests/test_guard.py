"""쓰기 보호 테스트 — 토큰이 켜지면 문이 잠기고, 손님 동선은 열려 있되 감속된다."""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.api import guard
from app.main import app

client = TestClient(app)


@pytest.fixture
def locked(monkeypatch):
    """운영처럼 토큰을 켠 상태."""
    monkeypatch.setattr(config, "ADMIN_TOKEN", "test-admin-token")
    yield {"X-Admin-Token": "test-admin-token"}


def test_writes_are_locked_when_token_is_set(locked):
    """토큰 없이 두드리면 401 — 상태를 바꾸는 문 전부."""
    doors = [
        ("PUT", "/api/policy/store-a", {"values": {"auto_pay_limit_usdc": 10}}),
        ("POST", "/api/approvals/INV-X/decide", {"decision": "approve"}),
        ("POST", "/api/schedules/INV-X/run", {}),
        ("POST", "/api/ticks/run", None),
        ("POST", "/api/demo/negotiate", None),
        ("POST", "/api/assistant/chat", {"message": "안녕"}),
        ("POST", "/api/auth/passkey/register/options", {"role": "store-a"}),
        ("DELETE", "/api/auth/passkey/store-a", None),
        ("POST", "/a2a/hq", {"jsonrpc": "2.0", "method": "message/send"}),
    ]
    for method, url, body in doors:
        res = client.request(method, url, json=body)
        assert res.status_code == 401, f"{method} {url} → {res.status_code} (401이어야)"


def test_correct_token_opens_the_door(locked):
    """토큰이 맞으면 정상 경로로 들어간다 (여기서는 검증 오류 = 문은 열렸다는 뜻)."""
    res = client.put("/api/policy/store-a",
                     json={"values": {"auto_pay_limit_usdc": 12}}, headers=locked)
    assert res.status_code == 200

    res = client.post("/api/approvals/INV-NOPE/decide",
                      json={"decision": "approve"}, headers=locked)
    assert res.status_code != 401  # 404(없는 청구서)면 된다 — 자물쇠는 통과


def test_reads_and_guest_purchase_stay_open(locked):
    """읽기와 손님 구매는 토큰 없이 — 심사위원의 동선."""
    assert client.get("/api/overview").status_code == 200
    assert client.get("/a2a/hq/.well-known/agent-card.json").status_code == 200
    # 구매는 404(없는 지점)로 답한다 = 401이 아니다 = 문이 열려 있다
    res = client.post("/api/shop/purchase",
                      json={"store_id": "store-x", "sku": "CHK-10", "qty": 1})
    assert res.status_code == 404


def test_empty_token_means_unlocked_for_local_dev():
    """토큰이 비어 있으면(로컬·테스트 기본) 잠그지 않는다."""
    assert config.ADMIN_TOKEN == ""
    res = client.put("/api/policy/store-a", json={"values": {"auto_pay_limit_usdc": 11}})
    assert res.status_code == 200


def test_purchase_rate_limit_slows_scripts(monkeypatch):
    """같은 IP의 연속 구매는 사람 손 속도로 감속된다 — 무거운 일 전에 끊는다."""
    guard._BUCKETS.clear()
    body = {"store_id": "store-x", "sku": "CHK-10", "qty": 1}
    for _ in range(15):
        assert client.post("/api/shop/purchase", json=body).status_code == 404
    res = client.post("/api/shop/purchase", json=body)
    assert res.status_code == 429
    guard._BUCKETS.clear()
