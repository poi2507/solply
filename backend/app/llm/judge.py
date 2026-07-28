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
    user = (
        f"아래 {label} 제안을 심사하고 "
        "accept / reject / counter 중 하나로 결정해라.\n\n"
        f"{lines}\n\n"
        "정책 기준에 비추어 판단하고, 근거에 수치를 반드시 포함해라."
    )
    verdict: Verdict = _invoke("hq", system, user, schema=Verdict)
    decision = verdict.decision.strip().lower()
    if decision not in ("accept", "reject", "counter"):
        decision = "reject"
    return {"decision": decision, "reasoning": verdict.reasoning.strip()}


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
