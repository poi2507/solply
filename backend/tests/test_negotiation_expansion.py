"""발주량 협상·P2P 가격 흥정·본사 중개 (8/18) — 숫자 가드를 지킨다.

원칙 그대로: 단어(이행/축소, 수락/역제안, 중개/보류)는 LLM이 고르지만
수량과 가격의 경계는 코드가 강제한다. 여기서는 그 경계를 검증한다.
"""

from app.agents import utils
from app.llm import rules


# ── 가격 밴드 — 역제안 단가는 본사 공급가를 절대 못 넘는다 ──────────

def test_price_counter_capped_at_hq_unit():
    assert utils.price_counter_unit(0.5, hq_unit=0.5) is None      # 여지 없음 → 흥정 불가
    assert utils.price_counter_unit(0.45, hq_unit=0.5) == 0.495    # +10% 밴드 안
    assert utils.price_counter_unit(0.48, hq_unit=0.5) == 0.5      # 밴드보다 공급가 상한이 먼저
    assert utils.price_counter_unit(0, hq_unit=0.5) is None


def test_price_counter_without_hq_price_still_banded():
    # 공급가 정보가 없어도 +10%를 넘지 않는다
    assert utils.price_counter_unit(1.0, hq_unit=0) == 1.1


# ── 중개 후보 — 부분 잉여만, 전량 잉여는 지점의 몫 ─────────────────

def test_broker_candidates_partial_surplus_only(monkeypatch):
    from app.agents.hq import tools as hq_tools

    # 라이브 거래를 배제하고 시드만 본다 (test_p2p와 같은 수법)
    monkeypatch.setattr("app.db.store.list_docs", lambda *a, **k: [])
    candidates = hq_tools.broker_candidates()
    for c in candidates:
        assert 0 < c["qty"] < c["need"], "중개는 부분 잉여만 — 전량이면 지점이 스스로 찾는다"
        assert c["buyer_id"] != c["seller_id"]


# ── 규칙 폴백 — LLM이 죽으면 기존 동작으로 (조달·거래가 멈추지 않는다) ──

def test_fallbacks_preserve_previous_behavior():
    assert rules.review_order({}, {})["decision"] == "accept"          # 심사 없음 = 원 수량
    assert rules.review_brokerage({}, {})["decision"] == "reject"      # 중개 없음
    assert rules.respond_order_trim({}, {})["decision"] == "insist"    # 원 수량 유지
    assert rules.respond_p2p_price({}, {})["decision"] == "accept"     # 제안가 수락


def test_buyer_price_fallback_rejects_above_hq():
    over = rules.decide_p2p_price({"counter_unit_usdc": 0.6, "hq_unit_price_usdc": 0.5}, {})
    assert over["decision"] == "hq"
    ok = rules.decide_p2p_price({"counter_unit_usdc": 0.5, "hq_unit_price_usdc": 0.5}, {})
    assert ok["decision"] == "accept"


# ── A2A 응답 계약 — 그래프 상태 스키마에 없는 키는 조용히 사라진다 ────

def test_reply_keys_declared_in_state_schemas():
    """REPLY_KEYS의 키가 상태 스키마에 없으면 LangGraph가 버려서 응답이 빈다.

    8/18 라이브 실측: StoreState에 decision이 없어 중개 '수락'이 응답에서
    사라졌고, 오케스트레이터가 거절로 오판해 거래가 proposed에 멈췄다.
    """
    from app.a2a.server import REPLY_KEYS
    from app.agents.hq.state import HQState
    from app.agents.store.state import StoreState

    for schema in (HQState, StoreState):
        missing = set(REPLY_KEYS) - set(schema.__annotations__)
        assert not missing, f"{schema.__name__}에 없는 REPLY_KEYS: {missing}"
