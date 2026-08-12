"""협상 깊이 — 다회 왕복이 입력(신용·시세·잔액)에 따라 갈리는지.

지키는 것:
  - 시세→가격 인과: fair_price가 추세를 밴드 안에서만 반영한다 (소음 차단)
  - 라운드 2(지점 재응수)가 지갑 사정으로 수락/수정안/결렬로 갈린다
  - 라운드 3(종결)이 합의를 문서(분할 청구서)로 집행하고, 수정안은 한도로 판정한다
  - 결렬은 사람 승인 큐에 도달한다 — "사람에게 넘긴다"는 말이 아니라 상태다
  - 오케스트레이터가 라운드를 순서대로 밟고, 수락이면 한 왕복으로 끝낸다
"""

import asyncio

import pytest

from app.agents import utils
from app.agents.hq import node as hq_node
from app.agents.hq import tools as hq_tools
from app.agents.store import node as store_node
from app.core import economy
from app.db import store as db


def make_invoice(invoice_id: str, amount: float, store_id: str = "store-b", status: str = "issued") -> dict:
    return db.put("invoices", invoice_id, {
        "delivery_id": "DEL-TEST", "store_id": store_id,
        "items": [{"sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 1, "unit_price_usdc": amount}],
        "amount_usdc": amount, "status": status, "tx_sig": None,
    })


# ── 시세 → 가격 인과 ──────────────────────────────────────────────────

def test_fair_price_band():
    quote = {"price_usd": 94.0, "prev_price_usd": 100.0}   # −6% — 밴드 안
    price, note = utils.fair_price(0.5, quote)
    assert price == pytest.approx(0.47)
    assert "−" in note or "-6.0%" in note

    crash = {"price_usd": 70.0, "prev_price_usd": 100.0}   # −30% — 밴드가 자른다
    price, _ = utils.fair_price(0.5, crash)
    assert price == pytest.approx(0.45), "데모 시세의 소음이 가격을 지배하면 안 된다"

    spike = {"price_usd": 125.0, "prev_price_usd": 100.0}  # +25% — 상방도 같은 밴드
    price, _ = utils.fair_price(0.5, spike)
    assert price == pytest.approx(0.55)


def test_fair_price_without_trend_keeps_supply_price():
    assert utils.fair_price(0.5, None) == (0.5, None)
    assert utils.fair_price(0.5, {"price_usd": 100.0}) == (0.5, None), "첫 조회엔 추세가 없다"


def test_propose_trade_price_reflects_quote():
    state = {
        "store_id": "store-b",
        "shortage": {"sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 0, "safety": 4, "need": 6},
        "supply": {"store_id": "store-a", "name": "A지점 (강남)", "surplus": 10, "unit_price_usdc": 0.5},
        "market_quote": {"summary": "CHK 94 USD (직전 대비 -6.0%)", "price_usd": 94.0, "prev_price_usd": 100.0},
    }
    out = store_node.propose_trade(state)
    trade = db.get("p2p_trades", out["trade_id"])
    assert trade["price_usdc"] == pytest.approx(round(6 * 0.47, 2)), "산 시세가 제안가를 실제로 바꾼다"
    assert any("반영" in r for r in out["reasoning"])


# ── 라운드 2 — 지점 재응수가 지갑 사정으로 갈린다 ─────────────────────

def _with_wallet(monkeypatch, wallet: float, reserve: float = 2.0):
    monkeypatch.setattr(
        "app.agents.store.node.tools.assess_cashflow",
        lambda store_id, invoice_id: {
            "wallet_usdc": wallet, "min_reserve_usdc": reserve, "pos_forecast": {"note": ""},
        },
    )


def test_counter_accepted_when_wallet_affords_installment(monkeypatch):
    make_invoice("INV-NEG-1", 8.0)
    _with_wallet(monkeypatch, wallet=10.0)
    out = store_node.respond_counter(
        {"store_id": "store-b", "invoice_id": "INV-NEG-1",
         "payload": {"terms": {"parts": 2, "per_usdc": 4.0}}}
    )
    assert out["proposal"]["decision"] == "accept"
    assert out["outcome"] == "negotiating"


def test_counter_gets_modified_offer_when_wallet_is_tight(monkeypatch):
    make_invoice("INV-NEG-2", 8.0)
    _with_wallet(monkeypatch, wallet=4.5)   # 가용 2.5 — 회당 4.0의 30% 이상, 100% 미만
    out = store_node.respond_counter(
        {"store_id": "store-b", "invoice_id": "INV-NEG-2",
         "payload": {"terms": {"parts": 2, "per_usdc": 4.0}}}
    )
    assert out["proposal"]["decision"] == "counter"
    assert out["proposal"]["terms"]["first_usdc"] == pytest.approx(2.5), "지금 낼 수 있는 만큼을 선납으로 제시"
    assert [e for e in db.list_events() if e["action"] == "proposal.counter_response"]


def test_counter_rejected_when_wallet_is_empty(monkeypatch):
    make_invoice("INV-NEG-3", 8.0)
    _with_wallet(monkeypatch, wallet=2.2)   # 가용 0.2 — 회당 4.0의 30% 미만
    out = store_node.respond_counter(
        {"store_id": "store-b", "invoice_id": "INV-NEG-3",
         "payload": {"terms": {"parts": 2, "per_usdc": 4.0}}}
    )
    assert out["proposal"]["decision"] == "reject"
    assert out["outcome"] == "refused"


# ── 라운드 3 — 종결: 집행은 문서, 결렬은 사람 ─────────────────────────

def test_settle_executes_agreed_split():
    invoice = make_invoice("INV-NEG-4", 8.0)
    out = hq_node.settle_negotiation(
        {"invoice": invoice, "payload": {"agreement": {"parts": 2, "per_usdc": 4.0}}}
    )
    assert out["outcome"] == "scheduled"
    assert db.get("invoices", "INV-NEG-4-P1")["status"] == "issued"
    assert db.get("invoices", "INV-NEG-4-P2")["status"] == "scheduled"


def test_settle_accepts_modified_offer_within_exposure_limit():
    invoice = make_invoice("INV-NEG-5", 5.0)   # store-b 한도 30 — 잔여 2.0은 6.7%
    out = hq_node.settle_negotiation(
        {"invoice": invoice,
         "payload": {"agreement": {"parts": 2, "per_usdc": 2.5, "first_usdc": 3.0}}}
    )
    assert out["outcome"] == "scheduled"
    p1, p2 = db.get("invoices", "INV-NEG-5-P1"), db.get("invoices", "INV-NEG-5-P2")
    assert p1["amount_usdc"] == pytest.approx(3.0), "선납 수정안이 1회차 금액이 된다"
    assert p1["amount_usdc"] + p2["amount_usdc"] == pytest.approx(5.0), "1센트도 새지 않는다"


def test_settle_rejects_modified_offer_over_exposure_and_escalates():
    invoice = make_invoice("INV-NEG-6", 30.0)  # 선납 2.0 후 잔여 28 — 한도 30의 93% > 20%
    out = hq_node.settle_negotiation(
        {"invoice": invoice,
         "payload": {"agreement": {"parts": 2, "per_usdc": 15.0, "first_usdc": 2.0}}}
    )
    assert out["outcome"] == "needs_human"
    assert db.get("invoices", "INV-NEG-6")["status"] == "pending_approval", "결렬은 사람 승인 큐로"
    assert [e for e in db.list_events() if e["action"] == "negotiation.failed"]


def test_settle_failure_reaches_human_queue():
    invoice = make_invoice("INV-NEG-7", 8.0)
    out = hq_node.settle_negotiation(
        {"invoice": invoice, "payload": {"failed": True, "reason": "지점 잔액 전무"}}
    )
    assert out["outcome"] == "needs_human"
    assert db.get("invoices", "INV-NEG-7")["status"] == "pending_approval"
    ends = [n for n in db.list_docs("negotiations")
            if n["invoice_id"] == "INV-NEG-7" and n["type"] == "counter_settle"]
    assert ends and ends[-1]["decision"] == "reject", \
        "결렬도 협상 기록으로 남는다 — 안 남기면 스레드가 '응답 대기'로 멈춰 보인다"


def test_split_with_first_amount_preserves_total():
    make_invoice("INV-NEG-8", 7.01)
    result = hq_tools.split_invoice("INV-NEG-8", parts=3, first_usdc=3.5)
    amounts = [c["amount_usdc"] for c in result["children"]]
    assert amounts[0] == pytest.approx(3.5)
    assert sum(amounts) == pytest.approx(7.01), "반올림 잔액은 마지막 회차가 흡수"


# ── 오케스트레이터 — 라운드를 순서대로 밟는다 ─────────────────────────

def _scripted_a2a(monkeypatch, replies: list[dict], calls: list):
    async def fake_send(agent_id, intent, **kwargs):
        calls.append((agent_id, intent, kwargs))
        return replies[len(calls) - 1]
    monkeypatch.setattr("app.core.economy.a2a.send", fake_send)


def test_negotiation_settles_in_one_round_on_accept(monkeypatch):
    make_invoice("INV-NEG-9", 3.0)
    utils.log("store-b-agent", "proposal.deferral", {"invoice_id": "INV-NEG-9", "pay_when": "금요일"})
    calls = []
    _scripted_a2a(monkeypatch, [{"outcome": "scheduled"}], calls)

    outcome = asyncio.run(economy._negotiate_deferral("store-b", "INV-NEG-9"))

    assert outcome == "deferred"
    assert [c[1] for c in calls] == ["proposal.deferral"], "수락이면 한 왕복으로 끝난다"


def test_negotiation_runs_three_rounds_to_agreement(monkeypatch):
    make_invoice("INV-NEG-10", 8.0)
    utils.log("store-b-agent", "proposal.deferral", {"invoice_id": "INV-NEG-10", "pay_when": "금요일"})
    calls = []
    _scripted_a2a(monkeypatch, [
        {"outcome": "negotiating",
         "decision": {"counter_terms": {"parts": 2, "per_usdc": 4.0}}},          # 라운드 1: 역제안
        {"outcome": "negotiating",
         "proposal": {"decision": "counter", "terms": {"first_usdc": 2.5}}},      # 라운드 2: 수정안
        {"outcome": "scheduled"},                                                  # 라운드 3: 집행
    ], calls)

    outcome = asyncio.run(economy._negotiate_deferral("store-b", "INV-NEG-10"))

    assert outcome == "installments_agreed"
    assert [c[1] for c in calls] == ["proposal.deferral", "proposal.counter", "proposal.settle"]
    assert calls[2][2]["payload"]["agreement"]["first_usdc"] == 2.5, "수정안이 합의 조건에 합쳐진다"


def test_negotiation_rejection_escalates_to_human(monkeypatch):
    make_invoice("INV-NEG-11", 8.0)
    utils.log("store-b-agent", "proposal.deferral", {"invoice_id": "INV-NEG-11", "pay_when": "금요일"})
    calls = []
    _scripted_a2a(monkeypatch, [
        {"outcome": "negotiating", "decision": {}, "reasoning": ["신용점수 미달"]},  # 거절 (counter 없음)
        {"outcome": "needs_human"},                                                  # settle(failed)
    ], calls)

    outcome = asyncio.run(economy._negotiate_deferral("store-b", "INV-NEG-11"))

    assert outcome == "negotiation_failed"
    assert calls[1][1] == "proposal.settle" and calls[1][2]["payload"]["failed"] is True
