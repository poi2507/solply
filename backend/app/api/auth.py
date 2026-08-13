"""패스키(WebAuthn) 본인확인 — 점주는 비밀번호도 시드문구도 외우지 않는다.

금융·결제 서비스의 본인확인은 법적 필수인데, 전통 방식(비밀번호 보안키패드,
FIDO 검증 서버 구축)은 비용·진입장벽이 크다. 패스키는 스마트폰·PC OS가
제공하는 인증을 그대로 쓰는 W3C 표준이라 그 장벽을 낮춘다 (멘토 실무 확인).

여기서는 게이트 입장(본인확인)만 다룬다 — 지갑 서명은 본사 수탁 그대로.
심사장 기기가 지원하지 않을 수 있으므로 프런트에 "건너뛰기(데모 모드)"가
항상 남는다: 인증은 문이지 벽이 아니다.
"""

import base64

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import PublicKeyCredentialDescriptor

from app import config
from app.db import store

router = APIRouter(prefix="/api/auth/passkey", tags=["auth"])

# 브라우저가 보내는 origin — 운영(HTTPS)과 로컬 개발을 함께 허용한다
_ORIGINS = [
    f"https://{config.PASSKEY_RP_ID}",
    "http://localhost:8080",
    "http://localhost:8000",
]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class RoleBody(BaseModel):
    role: str


class CredentialBody(BaseModel):
    role: str
    credential: dict


def _doc(role: str) -> dict:
    return store.get("passkeys", role) or {"credentials": [], "challenge": None}


@router.post("/register/options")
def register_options(body: RoleBody) -> dict:
    options = generate_registration_options(
        rp_id=config.PASSKEY_RP_ID,
        rp_name="Solply",
        user_id=body.role.encode(),
        user_name=body.role,
        user_display_name=body.role,
    )
    doc = _doc(body.role)
    doc["challenge"] = _b64(options.challenge)
    store.put("passkeys", body.role, doc)
    import json

    return json.loads(options_to_json(options))


@router.post("/register/verify")
def register_verify(body: CredentialBody) -> dict:
    doc = _doc(body.role)
    if not doc.get("challenge"):
        raise HTTPException(400, "먼저 등록 옵션을 요청하세요")
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=_unb64(doc["challenge"]),
            expected_origin=_ORIGINS,
            expected_rp_id=config.PASSKEY_RP_ID,
        )
    except Exception as exc:
        raise HTTPException(400, f"패스키 등록 검증 실패: {exc}") from exc

    doc["credentials"] = [
        c for c in doc["credentials"] if c["credential_id"] != _b64(verified.credential_id)
    ] + [{
        "credential_id": _b64(verified.credential_id),
        "public_key": _b64(verified.credential_public_key),
        "sign_count": verified.sign_count,
    }]
    doc["challenge"] = None
    store.put("passkeys", body.role, doc)
    store.log_event("human", "auth.passkey_registered", {"role": body.role})
    return {"ok": True}


@router.post("/login/options")
def login_options(body: RoleBody) -> dict:
    doc = _doc(body.role)
    if not doc["credentials"]:
        # 등록된 패스키가 없다 — 프런트는 등록 또는 데모 모드로 안내한다
        return {"registered": False}
    options = generate_authentication_options(
        rp_id=config.PASSKEY_RP_ID,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=_unb64(c["credential_id"]))
            for c in doc["credentials"]
        ],
    )
    doc["challenge"] = _b64(options.challenge)
    store.put("passkeys", body.role, doc)
    import json

    return {"registered": True, "options": json.loads(options_to_json(options))}


@router.post("/login/verify")
def login_verify(body: CredentialBody) -> dict:
    doc = _doc(body.role)
    if not doc.get("challenge"):
        raise HTTPException(400, "먼저 인증 옵션을 요청하세요")
    cred_id = body.credential.get("id", "")
    match = next((c for c in doc["credentials"] if c["credential_id"] == cred_id), None)
    if not match:
        raise HTTPException(400, "이 역할에 등록되지 않은 패스키입니다")
    try:
        verified = verify_authentication_response(
            credential=body.credential,
            expected_challenge=_unb64(doc["challenge"]),
            expected_origin=_ORIGINS,
            expected_rp_id=config.PASSKEY_RP_ID,
            credential_public_key=_unb64(match["public_key"]),
            credential_current_sign_count=match["sign_count"],
        )
    except Exception as exc:
        raise HTTPException(401, f"패스키 인증 실패: {exc}") from exc

    match["sign_count"] = verified.new_sign_count
    doc["challenge"] = None
    store.put("passkeys", body.role, doc)
    store.log_event("human", "auth.passkey_login", {"role": body.role})
    return {"ok": True}
