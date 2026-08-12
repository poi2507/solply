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


def test_inventory_moves_shift_stock(monkeypatch):
    """현재고 = 시드 + 재고 원장의 합 — 입고·판매·직거래가 전부 이동으로 계산된다."""
    moves = [
        {"store_id": "store-b", "sku": "CHK-10", "name": "냉장 닭", "qty": 4, "reason": "p2p_in", "ref": "P2P-01"},
        {"store_id": "store-a", "sku": "CHK-10", "name": "냉장 닭", "qty": -4, "reason": "p2p_out", "ref": "P2P-01"},
        {"store_id": "store-a", "sku": "CHK-10", "name": "냉장 닭", "qty": 10, "reason": "received", "ref": "DEL-001"},
    ]
    def fake_sum_by(collection, group_key, value_key, **k):
        sums: dict[str, float] = {}
        if collection != "inventory_moves":
            return sums
        for m in moves:
            if m["store_id"] == k.get("store_id"):
                sums[m[group_key]] = sums.get(m[group_key], 0) + m[value_key]
        return sums
    monkeypatch.setattr("app.db.store.sum_by", fake_sum_by)
    assert utils.effective_inventory("store-b")["CHK-10"]["qty"] == 0 + 4
    assert utils.effective_inventory("store-a")["CHK-10"]["qty"] == 10 - 4 + 10


def test_delivery_writes_shipment_and_receipt_pair():
    """납품 = 본사 출고(발주 수량) ↔ 지점 입고(검수 수량) — 두 수량의 차이가 곧 분쟁이다."""
    from app.agents.hq import tools as hq_tools

    before = len(db.list_docs("inventory_moves"))
    hq_tools.create_invoice("DEL-002")  # 발주 10, 검수 9
    moves = [m for m in db.list_docs("inventory_moves")[before:] if m["sku"] == "CHK-10"]

    shipped = next(m for m in moves if m["reason"] == "shipped")
    received = next(m for m in moves if m["reason"] == "received")
    assert shipped["store_id"] == "hq" and shipped["qty"] == -10
    assert received["store_id"] == "store-b" and received["qty"] == 9
    assert shipped["qty"] + received["qty"] == -1, "출고-입고 차이 1개 = 검수 분쟁 근거"


def test_sales_never_go_below_zero():
    """판매 기록은 보유 수량까지만 — 원장이 음수 재고를 만들지 않는다."""
    from app.agents.store import tools as store_tools

    current = store_tools.check_inventory("store-c")["inventory"]["CHK-10"]["qty"]
    result = store_tools.record_sales("store-c", "CHK-10", current + 999, "테스트")
    assert result["sold"] == current
    assert store_tools.check_inventory("store-c")["inventory"]["CHK-10"]["qty"] == 0
    assert store_tools.record_sales("store-c", "CHK-10", 1, "테스트")["error"]


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
