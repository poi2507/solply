"""에이전트 공통 계산과 프롬프트 조립 테스트."""

import pytest

from app.agents import utils
from app.agents.hq import prompt as hq_prompt
from app.agents.prompt_kit import SECTIONS
from app.agents.store import prompt as store_prompt

ITEMS = [
    {"sku": "CHK-10", "name": "냉장 닭 10kg", "qty": 10, "unit_price_usdc": 2.5},
    {"sku": "VEG-05", "name": "모둠 야채 5kg", "qty": 8, "unit_price_usdc": 1.25},
]


def test_line_total():
    assert utils.line_total(ITEMS) == 35.0


def test_find_discrepancies_flags_only_mismatches():
    received = {"CHK-10": 9, "VEG-05": 8}
    found = utils.find_discrepancies(ITEMS, received)
    assert len(found) == 1
    assert found[0]["sku"] == "CHK-10"
    assert found[0]["over_billed_usdc"] == 2.5
    assert utils.total_over_billed(found) == 2.5


def test_missing_sku_counts_as_zero_received():
    """입고 기록에 아예 없는 품목은 0개 받은 것으로 본다 — 미납품 청구를 잡아낸다."""
    found = utils.find_discrepancies(ITEMS, {"CHK-10": 10})
    assert found[0]["sku"] == "VEG-05"
    assert found[0]["received_qty"] == 0


def test_correct_items_stops_the_double_negotiation():
    """차감 합의 후 재검수하면 불일치가 없어야 한다. 아니면 같은 협상이 무한 반복된다."""
    received = {"CHK-10": 9, "VEG-05": 8}
    corrected = utils.correct_items(ITEMS, received)
    assert utils.find_discrepancies(corrected, received) == []
    assert utils.line_total(corrected) == 32.5


def test_amounts_match_absorbs_float_error():
    assert utils.amounts_match(0.1 + 0.2, 0.3)
    assert not utils.amounts_match(35.0, 32.5)


@pytest.mark.parametrize(
    "text",
    [hq_prompt.system(), store_prompt.system("store-c", 50.0)],
)
def test_prompts_have_every_section(text):
    for section in SECTIONS:
        assert f"[{section}]" in text


def test_store_prompt_injects_identity_and_limit():
    text = store_prompt.system("store-c", 42.0)
    assert "store-c" in text
    assert "42.0 USDC" in text


def _tool_names_in(text: str) -> set[str]:
    """프롬프트에서 `이름(` 형태로 지시된 도구 이름을 뽑는다."""
    import re

    return set(re.findall(r"\b([a-z_]+)\(", text))


def test_prompts_only_reference_existing_tools():
    """프롬프트가 없는 도구를 부르라고 하면 모델이 헛돈다.

    조회 도구까지 모두 프롬프트에 적을 필요는 없다. 반대 방향 — 프롬프트가 지시한
    이름이 실제 도구 목록에 있는지 — 만 지키면 된다.
    """
    from app.agents.hq import agent as hq_agent
    from app.agents.store import agent as store_agent

    hq_tools = {t.__name__ for t in hq_agent.TOOLS}
    assert _tool_names_in(hq_prompt.system()) <= hq_tools

    store_tools = {t.__name__ for t in store_agent.make_tools("store-a", 50.0)}
    assert _tool_names_in(store_prompt.system("store-a", 50.0)) <= store_tools


def test_prompts_cover_the_decision_path():
    """판단이 갈리는 지점의 도구는 반드시 프롬프트에 나와야 한다."""
    store_text = store_prompt.system("store-a", 50.0)
    for name in ("verify_delivery", "assess_cashflow", "execute_payment",
                 "propose_adjustment", "propose_deferral", "refuse_payment"):
        assert name in store_text

    hq_text = hq_prompt.system()
    for name in ("create_invoices", "review_proposal", "adjust_invoice_amount", "verify_payment"):
        assert name in hq_text
