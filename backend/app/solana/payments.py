"""결제 서비스(TypeScript/Express) HTTP 클라이언트.

온체인 실행은 전부 이 서비스를 통한다 — Solana SDK가 JS 생태계라 분리했다.

결제 서비스는 지갑 키를 쥔 유일한 프로세스라 Cloud Run에서 비공개로 돈다.
그 경우 호출마다 ID 토큰이 필요하다 — 메타데이터 서버에서 받아 붙인다
(로컬 개발에는 메타데이터 서버가 없으므로 그냥 무인증 호출이 된다).
"""

import time

import httpx

from app import config

_BASE = config.PAYMENTS_API_URL

# GCP 메타데이터 서버 — Cloud Run/GCE 안에서만 응답한다
_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/identity"
)

_token_cache: dict = {"token": None, "expires": 0.0}


def _headers() -> dict:
    """비공개 결제 서비스용 ID 토큰. 메타데이터 서버가 없으면(로컬) 빈 헤더."""
    if not _BASE.startswith("https://"):
        return {}
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires"]:
        return {"Authorization": f"Bearer {_token_cache['token']}"}
    try:
        resp = httpx.get(
            _METADATA_TOKEN_URL,
            params={"audience": _BASE},
            headers={"Metadata-Flavor": "Google"},
            timeout=3,
        )
        resp.raise_for_status()
        # ID 토큰은 1시간 유효 — 5분 여유를 두고 갱신한다
        _token_cache.update(token=resp.text, expires=now + 55 * 60)
        return {"Authorization": f"Bearer {_token_cache['token']}"}
    except httpx.HTTPError:
        return {}


def balance(wallet: str) -> dict:
    resp = httpx.get(f"{_BASE}/balance/{wallet}", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()


def pay(from_wallet: str, recipient: str, amount: float, memo: str) -> dict:
    resp = httpx.post(
        f"{_BASE}/pay",
        json={"from": from_wallet, "recipient": recipient, "amount": amount, "memo": memo},
        headers=_headers(),
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def verify_tx(signature: str) -> dict:
    resp = httpx.get(f"{_BASE}/tx/{signature}", headers=_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()
