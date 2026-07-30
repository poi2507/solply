"""시세 구매(pay.sh) — CLI·네트워크 없이 가짜 출력으로 검증한다.

지키는 것: 402 응답에서 시세와 결제 영수증을 정확히 꺼내고, TTL 안에서는
같은 데이터를 두 번 사지 않으며, 어떤 실패도 조달을 멈추지 않는다.
"""

import base64
import json
import subprocess

import pytest

from app import config
from app.agents.store import node
from app.core import market
from app.db import store as db

_RECEIPT = base64.b64encode(
    json.dumps({"method": "solana", "reference": "SIG-REF-123", "status": "success"}).encode()
).decode().rstrip("=")

# 첫 실행의 지갑 생성 이벤트 줄·헤더가 섞인 실제 출력 모양 그대로
_FAKE_OUT = (
    '{"account":"default","event":"ephemeral_wallet_created","network":"localnet","pubkey":"PK"}\n'
    "HTTP/2 200 \n"
    f"payment-receipt: {_RECEIPT}\n"
    "content-type: application/json\n"
    "\n"
    '{"symbol":"CHK","price":"309.85","currency":"USD","source":"mpp-demo"}\n'
)


@pytest.fixture()
def paysh_on(monkeypatch):
    monkeypatch.setattr(config, "PAYSH_ENABLED", True)
    monkeypatch.setattr("app.core.market.shutil.which", lambda _: "/usr/local/bin/pay")


def test_quote_parses_price_receipt_and_logs(paysh_on, monkeypatch):
    monkeypatch.setattr(
        "app.core.market.subprocess.run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=_FAKE_OUT, stderr=""),
    )

    quote = market.quote("CHK-10", actor="store-a-agent")

    assert quote["price_usd"] == 309.85
    assert quote["receipt"]["reference"] == "SIG-REF-123"
    assert "기준 시세" in quote["summary"]
    event = [e for e in db.list_events() if e["action"] == "market.quote_purchased"][-1]
    assert event["payload"]["receipt_ref"] == "SIG-REF-123"
    assert "pay.sh" in event["payload"]["paid_via"]


def test_quote_reuses_within_ttl(paysh_on, monkeypatch):
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 0, stdout=_FAKE_OUT, stderr="")

    monkeypatch.setattr("app.core.market.subprocess.run", fake_run)

    market.quote("VEG-05", actor="store-a-agent")
    market.quote("VEG-05", actor="store-a-agent")

    assert calls["n"] == 1, "TTL 안에서 같은 시세를 두 번 사면 낭비다"


def test_quote_disabled_or_failing_never_blocks(paysh_on, monkeypatch):
    monkeypatch.setattr(config, "PAYSH_ENABLED", False)
    assert market.quote("CHK-10", actor="store-a-agent") is None

    monkeypatch.setattr(config, "PAYSH_ENABLED", True)

    def boom(cmd, **kw):
        raise OSError("pay CLI 없음")

    monkeypatch.setattr("app.core.market.subprocess.run", boom)
    assert market.quote("SAU-02", actor="store-a-agent") is None


def test_find_supply_buys_quote_as_judgment_input(monkeypatch):
    monkeypatch.setattr(
        "app.core.market.quote",
        lambda sku, actor: {"summary": "CHK 309.85 USD (첫 조회 — 기준 시세로 기록, 제공 mpp-demo)"},
    )
    state = {
        "store_id": "store-b",
        "shortage": {"sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 0, "safety": 4, "need": 8},
    }

    out = node.find_supply(state)

    assert any("x402로 구매" in m for m in out["messages"]), "구매한 시세가 판단 근거에 남아야 한다"
    assert out["market_quote"]["summary"].startswith("CHK"), "다음 노드가 쓰도록 상태에 실려야 한다"


def test_purchased_quote_lands_in_trade_doc_as_basis():
    state = {
        "store_id": "store-b",
        "shortage": {"sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 0, "safety": 4, "need": 2},
        "supply": {"store_id": "store-a", "name": "A지점 (강남)", "surplus": 10, "unit_price_usdc": 0.5},
        "market_quote": {"summary": "CHK 75.98 USD (직전 구매가 대비 -2.1%, 제공 mpp-demo)"},
    }

    out = node.propose_trade(state)

    trade = db.get("p2p_trades", out["trade_id"])
    assert "75.98" in trade["basis"] and "pay.sh" in trade["basis"], (
        "산 시세가 거래 문서에 남아 본사 심사와 대시보드가 읽을 수 있어야 한다"
    )
