"""빠른 판단(Jev) — 확신도 기준 이상이면 Jev가 결정, 미만·실패·평가 밖 종류는 LLM이 판단한다."""

import pytest

from app.core import policy as policy_mod
from app.llm import judge


@pytest.fixture
def live(monkeypatch):
    """LLM 경로를 켜고, Jev·LLM 호출은 바꿔 끼운다. 반환값으로 호출 기록을 본다."""
    calls = {"jev": 0, "slow": 0, "explain": 0}
    monkeypatch.setattr("app.llm.judge.factory.is_mock", lambda: False)
    monkeypatch.setattr("app.config.TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr("app.config.DECISION_LOG", False)

    def explain(*a, **k):
        calls["explain"] += 1
        return type("R", (), {"content": "Neighbour surplus 6 covers need 4 today."})()
    monkeypatch.setattr("app.llm.judge._invoke", explain)

    def slow_store(kind, facts, pol):
        calls["slow"] += 1
        return {"decision": "hq", "reasoning": "HQ terms are better."}
    monkeypatch.setattr("app.llm.judge._store_decide", slow_store)

    def slow_hq(kind, facts, pol):
        calls["slow"] += 1
        return {"decision": "accept", "reasoning": "Candidate 0 is worth it.", "parts": 0, "choice": 0}
    monkeypatch.setattr("app.llm.judge._review_proposal", slow_hq)

    def answer(choice, confidence):
        def fake(kind, facts, pol, allowed):
            calls["jev"] += 1
            calls["allowed"] = allowed
            return {"choice": choice, "confidence": confidence, "probabilities": {}, "ms": 200}
        monkeypatch.setattr("app.llm.jev.decide", fake)
    calls["answer"] = answer
    return calls


FACTS = {"need_qty": 4, "peer_surplus_qty": 6, "hq_min_order_qty": 10}
POL = {"fast_decision_min_confidence_pct": 70.0}


def test_confident_jev_decides_and_llm_only_explains(live):
    live["answer"]("p2p", 0.93)
    v = judge.store_decide("supply_route", FACTS, policy_mod.get("store-a").as_prompt_values())
    assert v["decision"] == "p2p" and v["decider"] == "jev"
    assert live["slow"] == 0 and live["explain"] == 1
    assert "decided by Jev · confidence 93%" in v["reasoning"]
    assert live["allowed"] == {"p2p", "hq"}, "지점 판단은 그 종류의 선택지만 건넨다"


def test_low_confidence_goes_to_llm(live):
    live["answer"]("p2p", 0.43)
    v = judge.store_decide("supply_route", FACTS, POL)
    assert v["decision"] == "hq", "기준 미만이면 LLM 판단을 쓴다"
    assert live["slow"] == 1
    assert "43% < 70%" in v["reasoning"]


def test_jev_failure_falls_back_to_llm(live, monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("jev down")
    monkeypatch.setattr("app.llm.jev.decide", boom)
    v = judge.store_decide("supply_route", FACTS, POL)
    assert v["decision"] == "hq" and live["slow"] == 1
    assert "Jev" not in v["reasoning"]


def test_unevaluated_kind_never_asks_jev(live):
    live["answer"]("accept", 0.99)
    judge.store_decide("counter_response", {"per_usdc": 4.0, "affordable_usdc": 5.0}, POL)
    assert live["jev"] == 0, "평가 표본이 없는 종류는 LLM만 판단한다"


def test_threshold_100_turns_jev_off(live):
    live["answer"]("p2p", 0.99)
    judge.store_decide("supply_route", FACTS, {"fast_decision_min_confidence_pct": 100})
    assert live["jev"] == 0 and live["slow"] == 1


def test_missing_threshold_means_off(live):
    """정책 값이 안 실려 온 호출은 빠른 판단을 쓰지 않는다 (안전한 쪽)."""
    live["answer"]("p2p", 0.99)
    judge.store_decide("supply_route", FACTS, {})
    assert live["jev"] == 0


def test_brokerage_reject_is_fast_but_accept_needs_llm(live):
    live["answer"]("reject", 0.9)
    v = judge.review_proposal("brokerage", {"후보 목록": "0) a → b"}, POL)
    assert v["decision"] == "reject" and live["slow"] == 0
    assert live["allowed"] == {"accept", "reject", "counter"}

    live["answer"]("accept", 0.95)
    v = judge.review_proposal("brokerage", {"후보 목록": "0) a → b"}, POL)
    assert v["choice"] == 0 and live["slow"] == 1, "어느 후보인지는 LLM이 고른다"


def test_policy_exposes_threshold_and_bounds_it():
    for owner in ("hq", "store-a"):
        keys = {f["key"] for f in policy_mod.describe(owner)}
        assert "fast_decision_min_confidence_pct" in keys
        assert policy_mod.get(owner).as_prompt_values()["fast_decision_min_confidence_pct"] == 70.0
    with pytest.raises(ValueError):
        policy_mod.save("hq", {"fast_decision_min_confidence_pct": 120})


def test_explanation_failure_keeps_jev_decision(live, monkeypatch):
    """근거문이 실패해도 결정은 그대로 — 선택지 기준 문장으로 대신한다."""
    def boom(*a, **k):
        raise RuntimeError("429")
    monkeypatch.setattr("app.llm.judge._invoke", boom)
    live["answer"]("p2p", 0.93)
    v = judge.store_decide("supply_route", FACTS, POL)
    assert v["decision"] == "p2p" and live["slow"] == 0
    assert v["reasoning"].startswith("A neighbour's surplus covers it today")


def test_order_adjust_stays_with_llm(live):
    """평가에서 불일치가 나온 종류는 확신도와 상관없이 LLM이 판단한다."""
    live["answer"]("insist", 0.95)
    judge.store_decide("order_adjust", {"order_qty": 5}, POL)
    assert live["jev"] == 0
