"""패스키 본인확인 — 옵션 발급·저장·정직한 미등록 응답·쓰레기 거절.

암호 검증 자체는 webauthn 라이브러리를 신뢰한다. 여기서 지키는 것:
챌린지가 저장되어 다른 인스턴스에서도 검증 가능하고, 미등록 역할은
정직하게 미등록이라고 답하며(프런트가 등록/데모 모드로 안내), 깨진
증명은 400으로 거절된다.
"""

from fastapi.testclient import TestClient

from app.db import store as db
from app.main import app

client = TestClient(app)


def test_register_options_issue_and_store_challenge():
    res = client.post("/api/auth/passkey/register/options", json={"role": "store-b"})
    assert res.status_code == 200
    body = res.json()
    assert body["challenge"] and body["rp"]["name"] == "Solply"
    assert db.get("passkeys", "store-b")["challenge"], "챌린지는 DB에 — 인스턴스가 2개라도 검증된다"


def test_login_options_honest_when_unregistered():
    res = client.post("/api/auth/passkey/login/options", json={"role": "store-c"})
    assert res.status_code == 200
    assert res.json() == {"registered": False}


def test_register_verify_rejects_garbage():
    client.post("/api/auth/passkey/register/options", json={"role": "store-a"})
    res = client.post(
        "/api/auth/passkey/register/verify",
        json={"role": "store-a", "credential": {"id": "쓰레기"}},
    )
    assert res.status_code == 400


def test_login_verify_rejects_unknown_credential():
    db.put("passkeys", "hq", {
        "credentials": [{"credential_id": "REAL", "public_key": "cGs", "sign_count": 0}],
        "challenge": "Y2hhbGxlbmdl",
    })
    res = client.post(
        "/api/auth/passkey/login/verify",
        json={"role": "hq", "credential": {"id": "FAKE"}},
    )
    assert res.status_code == 400
