"""에이전트의 판단 호출 지점.

노드가 "판단이 필요하다"고 느끼는 순간 여기를 부른다. provider(gemini/vertex/mock)와
재시도·구조화 출력은 전부 이 모듈이 흡수하므로, 노드는 결론만 받아 쓴다.

프롬프트는 `app/agents/<agent>/prompts/*.md`에서 오고, 정책 수치는 DB에서 주입된다.
"""

import re
import time

from pydantic import BaseModel, Field

from app.agents import prompts
from app.llm import factory, rules

_MIN_GAP_SEC = 4.0   # 무료 티어 분당 한도를 넘기지 않기 위한 최소 간격
_last_call_at = 0.0


class Verdict(BaseModel):
    """협상 제안에 대한 심사 결과."""

    decision: str = Field(description="accept | reject | counter 중 하나")
    reasoning: str = Field(description="판단 근거를 한국어 한두 문장으로. 수치를 포함할 것")
    # 회차 선택은 LLM, 회당 금액과 허용 범위는 코드 — 범위 밖 값은 호출부가 한도로 되돌린다.
    parts: int = Field(0, description="decision이 counter일 때 제안하는 분할 회차. 해당 없으면 0")
    # 중개 심사 전용 — 코드가 만들어 준 후보 중 고른 번호. 해당 없으면 -1.
    choice: int = Field(-1, description="후보 목록에서 고른 번호(0부터). 해당 없으면 -1")


def _retry_delay(message: str, attempt: int) -> float:
    match = re.search(r"'retryDelay':\s*'(\d+)s'", message) or re.search(r"retry in (\d+(?:\.\d+)?)s", message)
    if match:
        return float(match.group(1)) + 1.5
    return min(60.0, 8.0 * (2 ** (attempt - 1)))


def _invoke(agent: str, system_prompt: str, user_prompt: str, schema=None, attempts: int = 4):
    """LLM 호출 + 429 재시도. schema를 주면 구조화 출력으로 받는다."""
    global _last_call_at

    model = factory.chat_model(factory.model_for(agent))
    if schema is not None:
        model = model.with_structured_output(schema)

    for attempt in range(1, attempts + 1):
        gap = _MIN_GAP_SEC - (time.monotonic() - _last_call_at)
        if gap > 0:
            time.sleep(gap)
        try:
            result = model.invoke(
                [("system", system_prompt), ("human", user_prompt)]
            )
            _last_call_at = time.monotonic()
            if result is None and schema is not None:
                # 구조화 출력이 비어서 오는 일이 있다(함수 호출이 안 만들어진 응답).
                # 예외가 아니라 None으로 조용히 오므로 여기서 재시도 대상으로 취급한다
                # — 8/15 운영: flash-lite가 supply_route에서 26회 연속 None.
                print(f"[judge] 구조화 출력 없음({agent}) — 재시도 {attempt}/{attempts}")
                continue
            return result
        except Exception as exc:
            _last_call_at = time.monotonic()
            text = str(exc)
            if attempt == attempts or not ("429" in text or "RESOURCE_EXHAUSTED" in text):
                raise
            time.sleep(_retry_delay(text, attempt))
    raise RuntimeError("LLM 호출 실패")


# ── 판단 ──────────────────────────────────────────────────────────────

_REVIEW_RULES = {
    "adjustment": ("차감", lambda: rules.review_adjustment),
    "deferral": ("유예", lambda: rules.review_deferral),
    "p2p_trade": ("가맹점 간 직거래", lambda: rules.review_p2p),
    "order": ("발주 수량", lambda: rules.review_order),
    "brokerage": ("지점 간 재고 중개", lambda: rules.review_brokerage),
}

# 심사 종류별 추가 지시 — 문턱값이 아니라 시계열·후보를 읽는 판단을 시킨다
_REVIEW_EXTRA = {
    "order": (
        "\n\naccept = 주문 수량 그대로 이행 · counter = 기본 수량(base_qty)으로 축소 제안. "
        "일별 시계열을 직접 읽어라 — 마지막 하루이틀만 튀고 전국 추이가 평평하면 일시 파동일 "
        "가능성이 높고, 며칠에 걸쳐 우상향이면 추세 전환이다. 어느 패턴으로 봤는지를 근거에 써라."
    ),
    "brokerage": (
        "\n\naccept = 후보 중 하나를 골라 중개 제안(choice에 번호) · reject = 이번에는 중개하지 않는다. "
        "부족 지점의 급함(재고/안전선)과 잉여 지점의 여유, 품목의 전국 추이를 견줘 "
        "가장 값어치 있는 한 건만 골라라. 애매하면 reject — 중개는 틱마다 강제가 아니다."
    ),
}


def review_proposal(kind: str, facts: dict, policy_values: dict) -> dict[str, str]:
    """차감·유예·직거래 제안을 심사한다. 본사 에이전트가 부른다.

    Args:
        kind: adjustment | deferral | p2p_trade
        facts: 심사 재료 (요청액, 검증된 과청구액, 신용점수, 잉여 수량 …)
        policy_values: DB에서 온 본사 정책 (min_credit_score, defer_max_pct …)
    """
    label, rule = _REVIEW_RULES[kind]
    if factory.is_mock():
        return rule()(facts, policy_values)

    system = prompts.system("hq", **policy_values)
    lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
    extra = _REVIEW_EXTRA.get(kind, "")
    if kind == "deferral":
        # 회차는 상대를 보고 고르는 값이다 — 이력이 좋으면 크게 나눌 이유가 없다.
        extra = (
            f"\n\ncounter라면 분할 회차(parts)를 2~{policy_values.get('installment_max', 2)} 사이에서 "
            "골라라 — 납부 이력이 좋을수록 적은 회차, 위험할수록 잘게. counter가 아니면 parts는 0."
        )
    user = (
        f"아래 {label} 제안을 심사하고 "
        "accept / reject / counter 중 하나로 결정해라.\n\n"
        f"{lines}\n\n"
        "정책 기준에 비추어 판단하고, 근거에 수치를 반드시 포함해라."
        f"{extra}"
    )
    verdict: Verdict = _invoke("hq", system, user, schema=Verdict)
    decision = verdict.decision.strip().lower()
    if decision not in ("accept", "reject", "counter"):
        decision = "reject"
    return {"decision": decision, "reasoning": verdict.reasoning.strip(),
            "parts": max(0, int(verdict.parts or 0)),
            "choice": int(verdict.choice if verdict.choice is not None else -1)}


_STORE_RULES = {
    "counter_response": (
        "본사의 분할 역제안", "accept / counter / reject",
        ("accept = 회당 분할액을 감당할 수 있다 · "
         "counter = 회당은 부담이나 일부 선납은 가능하다 · "
         "reject = 선납 여력조차 없다"),
        lambda: rules.respond_counter,
    ),
    "supply_route": (
        "재고 조달 경로", "p2p / hq",
        ("p2p = 이웃 잉여로 오늘 채운다(리드타임·최소 발주량을 피한다) · "
         "hq = 본사 발주가 낫다(수량이 부족하거나 단가·조건이 유리하다)"),
        lambda: rules.choose_supply_route,
    ),
    "order_adjust": (
        "본사의 발주 수량 축소 제안에 대한 응답", "accept / insist",
        ("accept = 본사의 전국 추이 근거가 타당해 축소 수량을 받아들인다 · "
         "insist = 우리 상권의 판매 시계열이 실수요를 보여줘 원 수량을 고수한다. "
         "우리 일별 판매를 직접 읽고, 본사 근거의 어느 부분에 동의/반박하는지 써라"),
        lambda: rules.respond_order_trim,
    ),
    "p2p_respond": (
        "직거래 제안에 대한 판매측 응답", "accept / counter",
        ("accept = 제안가에 판다 · counter = 우리도 이 품목이 잘 나가 여유가 적으니 "
         "가격을 올려 되제안한다(인상 폭은 코드가 계산). 자기 판매 추세를 근거로 판단해라"),
        lambda: rules.respond_p2p_price,
    ),
    "p2p_price": (
        "판매측 가격 역제안에 대한 구매측 응답", "accept / hq",
        ("accept = 올린 가격이라도 오늘 인수가 이득이라 받아들인다 · "
         "hq = 그 값이면 본사 발주가 낫다(리드타임을 감수한다)"),
        lambda: rules.decide_p2p_price,
    ),
    "p2p_consider": (
        "본사가 중개한 직거래 제안에 대한 구매측 응답", "accept / decline",
        ("accept = 부분 수량이라도 오늘 받는 게 이득이다(잔여는 본사 발주로) · "
         "decline = 중개 조건이 우리 사정에 맞지 않는다"),
        lambda: rules.consider_brokered,
    ),
}


def store_decide(kind: str, facts: dict, policy_values: dict) -> dict[str, str]:
    """지점 에이전트의 판단 — 역제안 응답, 조달 경로.

    **선택만 맡기고 금액·수량은 코드가 계산한다** — 환각이 잔액을 넘는 선납을
    제안하면 그대로 돈이 나간다. 판단이 흔들려도(429·형식 오류) 규칙으로
    떨어져 협상이 멈추지 않는다.
    """
    label, options, guide, rule = _STORE_RULES[kind]
    fallback = rule()
    if factory.is_mock():
        return fallback(facts, policy_values)

    allowed = {o.strip() for o in options.split("/")}
    try:
        system = prompts.system("store", **policy_values)
        lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
        user = (
            f"아래 상황에서 {label}을 결정해라. {options} 중 하나를 고른다.\n"
            f"{guide}\n\n"
            f"{lines}\n\n"
            "우리 지점의 지불 여력과 재고 사정을 기준으로 판단하고, 근거에 수치를 포함해라."
        )
        verdict: Verdict = _invoke("store", system, user, schema=Verdict)
        decision = verdict.decision.strip().lower()
        if decision not in allowed:
            return fallback(facts, policy_values)
        return {"decision": decision, "reasoning": verdict.reasoning.strip()}
    except Exception as exc:  # noqa: BLE001 — 판단이 막혀도 규칙으로 계속 간다
        print(f"[judge] 지점 판단 실패({kind}) — 규칙으로 진행: {str(exc)[:120]}")
        return fallback(facts, policy_values)


def weekly_report(stats: dict, prompt_values: dict) -> str:
    """정산 통계를 경영진 보고용 한 문단으로 쓴다 (대시보드·데모 마무리용)."""
    if factory.is_mock():
        return rules.weekly_report(stats)

    import json

    system = prompts.system("hq", **prompt_values)
    user = (
        "아래 정산 통계로 경영진 보고용 정산 리포트를 한국어 3~4문장 한 문단으로 써라. "
        "수치를 반드시 포함하고, 에이전트가 자율 처리한 범위와 사람 개입 횟수를 대비시켜라.\n\n"
        + json.dumps(stats, ensure_ascii=False)
    )
    try:
        response = _invoke("hq", system, user)
        return getattr(response, "content", str(response)).strip()
    except Exception:  # noqa: BLE001 — 리포트 실패가 대시보드를 막아서는 안 된다
        return rules.weekly_report(stats)


def narrate(agent: str, prompt_values: dict, facts: list[str], reasoning: list[str]) -> str:
    """진행 상황을 사람이 읽는 한 문단으로 정리한다."""
    if not facts:
        return ""
    if factory.is_mock():
        return rules.narrate(facts, reasoning)

    system = prompts.system(agent, **prompt_values)
    body = "\n".join(f"- {f}" for f in facts)
    why = "\n".join(f"- {r}" for r in reasoning)
    user = f"아래 처리 결과를 보고해라.\n\n[사실]\n{body}\n\n[판단 근거]\n{why or '- 없음'}"
    try:
        response = _invoke(agent, system, user)
        return getattr(response, "content", str(response)).strip()
    except Exception:  # noqa: BLE001 — 보고문 실패가 정산을 막아서는 안 된다
        return rules.narrate(facts, reasoning)
