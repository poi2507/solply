"""Payments Service(TS) HTTP 클라이언트 — 온체인 실행은 전부 이 서비스를 통한다."""

import os

import httpx

BASE = os.getenv("PAYMENTS_API_URL", "http://localhost:3000")


def balance(wallet: str) -> dict:
    resp = httpx.get(f"{BASE}/balance/{wallet}", timeout=15)
    resp.raise_for_status()
    return resp.json()


def pay(from_wallet: str, recipient: str, amount: float, memo: str) -> dict:
    resp = httpx.post(
        f"{BASE}/pay",
        json={"from": from_wallet, "recipient": recipient, "amount": amount, "memo": memo},
        timeout=90,
    )
    resp.raise_for_status()
    return resp.json()


def verify_tx(signature: str) -> dict:
    resp = httpx.get(f"{BASE}/tx/{signature}", timeout=30)
    resp.raise_for_status()
    return resp.json()
