"""거래 정책 테스트 — 사용자가 설정한 값이 판단을 바꾸는지."""

import pytest

from app.core import policy as policy_mod
from app.llm import rules


@pytest.fixture(autouse=True)
def clean_policies(tmp_path, monkeypatch):
    """정책 저장소를 임시 파일로 갈아끼운다 — 실제 DB를 건드리지 않기 위해."""
    from app.db import local_store, store

    monkeypatch.setattr(store, "_store", local_store.LocalStore(tmp_path / "state.json"))
    yield


def test_defaults_apply_before_any_setup():
    """설정 전에도 에이전트는 돌아야 한다."""
    store_policy = policy_mod.get("store-a")
    assert store_policy.auto_pay_limit_usdc > 0
    assert policy_mod.get("hq").min_credit_score == 85


def test_save_and_read_back():
    policy_mod.save("store-a", {"auto_pay_limit_usdc": 30, "min_reserve_usdc": 5})
    saved = policy_mod.get("store-a")
    assert saved.auto_pay_limit_usdc == 30
    assert saved.min_reserve_usdc == 5


def test_dashboard_shows_the_policy_the_owner_set():
    """화면이 시드값을 보여주면 '상한 초과로 보류'와 모순된다 — 실효 정책을 내려야 한다."""
    from fastapi.testclient import TestClient

    from app.main import app

    policy_mod.save("store-a", {"auto_pay_limit_usdc": 1})
    view = TestClient(app).get("/api/overview").json()
    mine = next(s for s in view["stores"] if s["id"] == "store-a")
    assert mine["autoPayLimit"] == 1


def test_unknown_field_is_rejected():
    with pytest.raises(ValueError, match="알 수 없는"):
        policy_mod.save("store-a", {"drain_the_wallet": True})


@pytest.mark.parametrize(
    ("owner", "patch", "message"),
    [
        ("store-a", {"auto_pay_limit_usdc": 0}, "0보다"),
        ("store-a", {"min_reserve_usdc": -1}, "0 이상"),
        ("hq", {"min_credit_score": 200}, "0~100"),
        ("hq", {"defer_max_pct": 150}, "0~100"),
        ("hq", {"installment_max": 0}, "1 이상"),
    ],
)
def test_out_of_range_values_are_rejected(owner, patch, message):
    with pytest.raises(ValueError, match=message):
        policy_mod.save(owner, patch)


def test_prompt_values_have_no_float_residue():
    """25.0이 아니라 25로 나가야 프롬프트가 자연스럽다."""
    policy_mod.save("store-a", {"auto_pay_limit_usdc": 25.0})
    assert policy_mod.get("store-a").as_prompt_values()["auto_pay_limit_usdc"] == "25"


def test_describe_gives_the_frontend_everything_it_needs():
    fields = policy_mod.describe("store-a")
    assert fields
    for field in fields:
        assert {"key", "label", "help", "unit", "min", "max", "value"} <= set(field)


# ── 정책이 판단을 바꾸는가 ────────────────────────────────────────────

def test_deferral_rides_on_credit_limit_not_invoice_amount():
    """전액 유예 요청은 청구액 대비 항상 100%다. 기준은 외상 한도여야 한다."""
    facts = {"credit_score": 92, "amount_usdc": 35, "credit_limit_usdc": 250}
    assert rules.review_deferral(facts, {"min_credit_score": 85, "defer_max_pct": 20})["decision"] == "accept"

    tight = {**facts, "credit_limit_usdc": 100}  # 35/100 = 35% > 20%
    assert rules.review_deferral(tight, {"min_credit_score": 85, "defer_max_pct": 20})["decision"] == "counter"


def test_deferral_rejected_below_credit_threshold():
    facts = {"credit_score": 70, "amount_usdc": 10, "credit_limit_usdc": 250}
    verdict = rules.review_deferral(facts, {"min_credit_score": 85, "defer_max_pct": 20})
    assert verdict["decision"] == "reject" and "70" in verdict["reasoning"]


def test_adjustment_rejected_when_amount_does_not_match_evidence():
    """근거보다 많이 요구하면 거절한다."""
    facts = {"deduction_usdc": 10.0, "verified_over_billed": 2.5, "detail": "닭 10→9"}
    assert rules.review_adjustment(facts, {"auto_adjust_limit_usdc": 20})["decision"] == "reject"


def test_adjustment_escalates_above_auto_limit():
    facts = {"deduction_usdc": 50.0, "verified_over_billed": 50.0, "detail": "대량 미입고"}
    assert rules.review_adjustment(facts, {"auto_adjust_limit_usdc": 20})["decision"] == "counter"


def test_adjustment_accepted_when_evidence_matches():
    facts = {"deduction_usdc": 2.5, "verified_over_billed": 2.5, "detail": "닭 10→9"}
    verdict = rules.review_adjustment(facts, {"auto_adjust_limit_usdc": 20})
    assert verdict["decision"] == "accept" and "2.5" in verdict["reasoning"]
