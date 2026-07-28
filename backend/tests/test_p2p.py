"""Phase 2.5 테스트 — 가맹점 간 직거래 (시나리오 E).

핵심 가드 두 개를 지킨다: 판매해도 안전재고는 깨지지 않는다,
본사 승인 없이는 돈이 나가지 않는다.
"""

import pytest
from fastapi.testclient import TestClient

from app.agents import utils
from app.agents.store import tools as store_tools
from app.core import protocol
from app.db import store as db
from app.llm import rules
from app.main import app

client = TestClient(app)

HQ_POLICY = {"p2p_min_credit_score": 75}


def make_trade(status: str = "proposed", price: float = 10.0) -> dict:
    return db.put(
        "p2p_trades",
        db.new_id("P2P"),
        {
            "sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 4, "price_usdc": price,
            "buyer_id": "store-b", "seller_id": "store-a",
            "status": status, "tx_sig": None,
        },
    )


# ── 재고 계산 ─────────────────────────────────────────────────────────

def test_fixture_seeds_the_scenario(monkeypatch):
    """E 시나리오는 데이터로 만들어진다 — A 잉여가 B 부족을 채울 수 있어야 한다.

    라이브 거래는 배제하고 시드만 본다 (데모는 db.reset으로 시드 상태에서 시작한다).
    """
    monkeypatch.setattr("app.db.store.list_docs", lambda *a, **k: [])
    inv_a = utils.effective_inventory("store-a")
    inv_b = utils.effective_inventory("store-b")
    shortages = utils.stock_shortages(inv_b)
    assert shortages and shortages[0]["sku"] == "CHK-10"
    assert utils.sellable_surplus(inv_a, "CHK-10") >= shortages[0]["need"]


def test_confirmed_trade_moves_inventory(monkeypatch):
    """확정된 거래만 재고를 옮긴다 — 산 쪽은 늘고 판 쪽은 준다."""
    trades = [
        {"sku": "CHK-10", "qty": 4, "status": "confirmed", "buyer_id": "store-b", "seller_id": "store-a"},
        {"sku": "CHK-10", "qty": 2, "status": "proposed", "buyer_id": "store-b", "seller_id": "store-a"},
    ]
    monkeypatch.setattr(
        "app.db.store.list_docs",
        lambda collection, **k: trades if collection == "p2p_trades" else [],
    )
    assert utils.effective_inventory("store-b")["CHK-10"]["qty"] == 0 + 4
    assert utils.effective_inventory("store-a")["CHK-10"]["qty"] == 10 - 4


def test_sellable_surplus_respects_multiplier():
    inventory = {"CHK-10": {"qty": 10, "safety": 4}}
    assert utils.sellable_surplus(inventory, "CHK-10") == 6
    assert utils.sellable_surplus(inventory, "CHK-10", safety_multiplier=2.0) == 2
    assert utils.sellable_surplus(inventory, "VEG-05") == 0


# ── 본사 심사 규칙 ────────────────────────────────────────────────────

def test_review_p2p_accepts_within_all_limits():
    verdict = rules.review_p2p(
        {"qty": 4, "seller_surplus": 6, "buyer_credit_score": 88, "seller_credit_score": 90,
         "unit_price_usdc": 2.5, "hq_unit_price_usdc": 2.5},
        HQ_POLICY,
    )
    assert verdict["decision"] == "accept"


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        ({"qty": 8, "seller_surplus": 6, "buyer_credit_score": 90, "seller_credit_score": 90,
          "unit_price_usdc": 2.5, "hq_unit_price_usdc": 2.5}, "reject"),   # 안전재고 침범
        ({"qty": 4, "seller_surplus": 6, "buyer_credit_score": 70, "seller_credit_score": 90,
          "unit_price_usdc": 2.5, "hq_unit_price_usdc": 2.5}, "reject"),   # 신용 미달
        ({"qty": 4, "seller_surplus": 6, "buyer_credit_score": 90, "seller_credit_score": 90,
          "unit_price_usdc": 3.5, "hq_unit_price_usdc": 2.5}, "counter"),  # 공급가 초과
    ],
)
def test_review_p2p_blocks_bad_trades(facts, expected):
    assert rules.review_p2p(facts, HQ_POLICY)["decision"] == expected


# ── 결제 가드: 승인 없이는 돈이 나가지 않는다 ────────────────────────

def test_unapproved_trade_cannot_be_paid(monkeypatch):
    called = []
    monkeypatch.setattr("app.solana.payments.pay", lambda *a: called.append(a))

    for status in ("proposed", "accepted", "rejected"):
        trade = make_trade(status=status)
        result = store_tools.pay_p2p_trade("store-b", trade["id"])
        assert result.get("error"), f"{status} 상태에서 결제가 막혀야 한다"
    assert called == [], "승인 전에는 온체인 결제가 한 번도 나가면 안 된다"

    event = [e for e in db.list_events() if e["action"] == "p2p.blocked_unapproved"]
    assert event, "차단도 실행 증빙으로 남아야 한다"


def test_p2p_payment_respects_spend_limit(monkeypatch):
    monkeypatch.setattr("app.solana.payments.pay", lambda *a: pytest.fail("결제되면 안 된다"))
    trade = make_trade(status="approved", price=9999.0)
    result = store_tools.pay_p2p_trade("store-b", trade["id"])
    assert result["status"] == "needs_human_approval"


def test_seller_rejects_when_safety_stock_breaks(monkeypatch):
    """판매측 응답 — 잉여보다 큰 요청은 거절한다."""
    monkeypatch.setattr(
        "app.agents.store.tools.check_inventory",
        lambda sid: {"inventory": {"CHK-10": {"qty": 5, "safety": 4}}, "shortages": []},
    )
    from app.agents.store import node

    trade = make_trade()
    state = {"store_id": "store-a", "trade": trade}
    result = node.respond_trade(state)
    assert result["trade"]["status"] == "rejected"


# ── 직거래 x402 왕복 (판매 지점이 resource server) ───────────────────

def test_trade_challenge_offers_seller_terms(monkeypatch):
    monkeypatch.setattr(
        "app.solana.payments.balance", lambda w: {"address": f"{w.upper()}-ADDR", "usdc": 0, "sol": 1}
    )
    trade = make_trade(status="approved")
    resp = client.get(f"/x402/trades/{trade['id']}/settle")

    assert resp.status_code == 402
    accepts = resp.json()["accepts"]
    assert len(accepts) == 1
    assert accepts[0]["payTo"] == "STORE-A-ADDR"
    assert protocol.from_atomic(accepts[0]["amount"]) == pytest.approx(trade["price_usdc"])


def test_trade_settle_confirms_after_onchain_match(monkeypatch):
    trade = make_trade(status="paid")
    monkeypatch.setattr(
        "app.solana.payments.verify_tx",
        lambda sig: {"found": True, "success": True, "memo": trade["id"],
                     "transfer": {"amount": trade["price_usdc"]}, "explorer": ""},
    )
    header = protocol.encode_header(
        {"x402Version": protocol.X402_VERSION, "payload": {"signature": "SIG"}}
    )
    resp = client.post(f"/x402/trades/{trade['id']}/settle", headers={"PAYMENT-SIGNATURE": header})

    assert resp.status_code == 200
    assert db.get("p2p_trades", trade["id"])["status"] == "confirmed"
    assert [e for e in db.list_events() if e["action"] == "p2p.confirmed"]


def test_trade_settle_refuses_wrong_amount(monkeypatch):
    trade = make_trade(status="paid")
    monkeypatch.setattr(
        "app.solana.payments.verify_tx",
        lambda sig: {"found": True, "success": True, "memo": trade["id"],
                     "transfer": {"amount": 0.01}, "explorer": ""},
    )
    header = protocol.encode_header(
        {"x402Version": protocol.X402_VERSION, "payload": {"signature": "SIG"}}
    )
    resp = client.post(f"/x402/trades/{trade['id']}/settle", headers={"PAYMENT-SIGNATURE": header})

    assert resp.status_code == 402
    assert db.get("p2p_trades", trade["id"])["status"] == "paid"


# ── 그래프 배선 ───────────────────────────────────────────────────────

def test_p2p_intents_route_to_their_nodes():
    from app.agents.store import graph as store_graph
    from app.agents.store import node

    nodes = set(store_graph.build().get_graph().nodes)
    assert {"check_stock", "find_supply", "propose_trade", "respond_trade", "pay_trade"} <= nodes
    assert node.route_after_context({"intent": "restock.check"}) == "check_stock"
    assert node.route_after_context({"intent": "p2p.respond"}) == "respond_trade"
    assert node.route_after_context({"intent": "p2p.pay"}) == "pay_trade"


def test_hq_graph_reviews_and_records_p2p():
    from app.agents.hq import graph as hq_graph

    nodes = set(hq_graph.build().get_graph().nodes)
    assert {"review_p2p", "record_p2p"} <= nodes
