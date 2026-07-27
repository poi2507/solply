"""에이전트 계층 테스트 — 공통 계산, 프롬프트 조립, 그래프 배선."""

import pytest

from app.agents import prompts, utils
from app.agents.hq import graph as hq_graph
from app.agents.store import graph as store_graph

ITEMS = [
    {"sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 10, "unit_price_usdc": 2.5},
    {"sku": "VEG-05", "name": "모둠 야채 5kg", "qty": 8, "unit_price_usdc": 1.25},
]

STORE_VALUES = {"store_id": "store-a", "auto_pay_limit_usdc": "50", "min_reserve_usdc": "10"}
HQ_VALUES = {"min_credit_score": 85, "defer_max_pct": "20", "installment_max": 2}


# ── 순수 계산 ─────────────────────────────────────────────────────────

def test_line_total():
    assert utils.line_total(ITEMS) == 35.0


def test_find_discrepancies_flags_only_mismatches():
    found = utils.find_discrepancies(ITEMS, {"CHK-10": 9, "VEG-05": 8})
    assert len(found) == 1
    assert found[0]["sku"] == "CHK-10"
    assert utils.total_over_billed(found) == 2.5


def test_missing_sku_counts_as_zero_received():
    """입고 기록에 없는 품목은 0개 받은 것으로 본다 — 미납품 청구를 잡아낸다."""
    found = utils.find_discrepancies(ITEMS, {"CHK-10": 10})
    assert found[0]["sku"] == "VEG-05" and found[0]["received_qty"] == 0


def test_correct_items_stops_the_double_negotiation():
    """차감 합의 후 재검수하면 불일치가 없어야 한다. 아니면 같은 협상이 반복된다."""
    received = {"CHK-10": 9, "VEG-05": 8}
    corrected = utils.correct_items(ITEMS, received)
    assert utils.find_discrepancies(corrected, received) == []
    assert utils.line_total(corrected) == 32.5


def test_amounts_match_absorbs_float_error():
    assert utils.amounts_match(0.1 + 0.2, 0.3)
    assert not utils.amounts_match(35.0, 32.5)


# ── 프롬프트 (md 파일) ────────────────────────────────────────────────

@pytest.mark.parametrize("agent", ["hq", "store"])
def test_every_section_file_exists(agent):
    for section in prompts.SECTIONS:
        assert prompts.load(agent, section, **{**STORE_VALUES, **HQ_VALUES})


def test_composed_prompt_is_tagged():
    text = prompts.system("store", **STORE_VALUES)
    for section in prompts.SECTIONS:
        assert f"[{section.upper()}]" in text


def test_store_prompt_injects_identity_and_limits():
    text = prompts.system("store", store_id="store-c", auto_pay_limit_usdc="42", min_reserve_usdc="7")
    assert "store-c" in text and "42 USDC" in text and "7 USDC" in text


def test_missing_placeholder_value_fails_loudly():
    """정책 키가 빠지면 조용히 넘어가지 않고 즉시 터져야 한다."""
    with pytest.raises(KeyError):
        prompts.system("store", store_id="store-a")


@pytest.mark.parametrize(
    ("agent", "supplied"),
    [("hq", HQ_VALUES), ("store", STORE_VALUES)],
)
def test_policy_placeholders_are_all_supplied(agent, supplied):
    """policy.md가 요구하는 자리표시자를 정책이 전부 채울 수 있어야 한다."""
    needed = prompts.placeholders(agent, "policy")
    assert needed <= set(supplied), f"{agent} 정책에 없는 자리표시자: {needed - set(supplied)}"


def test_prompts_only_name_existing_tools():
    """프롬프트가 없는 도구를 부르라고 하면 모델이 헛돈다."""
    import re

    from app.agents.hq import tools as hq_tools
    from app.agents.store import tools as store_tools

    def named(text: str) -> set[str]:
        return set(re.findall(r"\b([a-z_]{4,})\(", text))

    hq_available = {n for n in dir(hq_tools) if not n.startswith("_")}
    store_available = {n for n in dir(store_tools) if not n.startswith("_")}
    assert named(prompts.system("hq", **HQ_VALUES)) <= hq_available
    assert named(prompts.system("store", **STORE_VALUES)) <= store_available


# ── 그래프 배선 ───────────────────────────────────────────────────────

def test_store_graph_has_every_decision_path():
    nodes = set(store_graph.build().get_graph().nodes)
    assert {"verify", "cashflow", "pay", "propose_adjustment", "propose_deferral", "refuse"} <= nodes


def test_hq_graph_routes_each_intent():
    from app.agents.hq import node

    nodes = set(hq_graph.build().get_graph().nodes)
    for target in node._INTENT_ROUTE.values():
        assert target in nodes, f"intent가 가리키는 노드 {target}가 그래프에 없다"


def test_store_routes_to_deferral_when_reserve_would_break():
    """잔액은 충분해도 하한을 깨면 결제하지 않고 유예를 제안해야 한다."""
    from app.agents.store import node

    state = {"cashflow": {"sufficient": True, "keeps_reserve": False, "within_auto_limit": True}}
    assert node.route_after_cashflow(state) == "propose_deferral"


def test_store_routes_to_pay_when_all_clear():
    from app.agents.store import node

    state = {"cashflow": {"sufficient": True, "keeps_reserve": True, "within_auto_limit": True}}
    assert node.route_after_cashflow(state) == "pay"
