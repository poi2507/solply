"""결제 서비스(TypeScript/Express) HTTP 클라이언트.

온체인 실행은 전부 이 서비스를 통한다 — Solana SDK가 JS 생태계라 분리했다.
"""

import httpx

from app import config

_BASE = config.PAYMENTS_API_URL


def balance(wallet: str) -> dict:
    resp = httpx.get(f"{_BASE}/balance/{wallet}", timeout=15)
    resp.raise_for_status()
    return resp.json()


def pay(from_wallet: str, recipient: str, amount: float, memo: str) -> dict:
    resp = httpx.post(
        f"{_BASE}/pay",
        json={"from": from_wallet, "recipient": recipient, "amount": amount, "memo": memo},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def verify_tx(signature: str) -> dict:
    resp = httpx.get(f"{_BASE}/tx/{signature}", timeout=30)
    resp.raise_for_status()
    return resp.json()
