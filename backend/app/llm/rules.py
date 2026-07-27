"""mock 모드의 규칙 기반 판단.

LLM을 부르지 않고 정책만으로 같은 결론을 낸다. 판단 기준은 프롬프트의 POLICY 섹션과
같은 값(DB에서 온 정책)을 쓰므로, mock과 실제 Gemini의 결론이 대체로 일치한다.

용도: 데모 리허설과 테스트. **도구는 진짜를 호출하므로 온체인 결제는 실제로 발생한다.**
"""

from typing import Any


def review_adjustment(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """차감 제안 심사 — 검수 근거가 있고 금액이 맞으면 수락."""
    requested = float(facts.get("deduction_usdc", 0))
    verified = float(facts.get("verified_over_billed", 0))
    limit = float(policy.get("auto_adjust_limit_usdc", 20))

    if requested <= 0:
        return {"decision": "reject", "reasoning": "차감 요청액이 없습니다."}
    if requested > limit:
        return {
            "decision": "counter",
            "reasoning": f"차감 요청 {requested} USDC가 자동 승인 한도 {limit} USDC를 넘어 담당자 확인이 필요합니다.",
        }
    if abs(requested - verified) > 1e-6:
        return {
            "decision": "reject",
            "reasoning": f"납품 로그상 과청구는 {verified} USDC인데 {requested} USDC를 요청해 근거가 맞지 않습니다.",
        }
    return {
        "decision": "accept",
        "reasoning": f"납품 로그 대조 결과 {facts.get('detail', '불일치')} 확인. {requested} USDC 차감이 타당합니다.",
    }


def review_deferral(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """유예 제안 심사 — 신용점수와 외상 한도 대비 노출도를 본다.

    `defer_max_pct`는 "이 가맹점 외상 한도의 몇 %까지 유예를 떠안을 것인가"다.
    청구액 대비가 아니다 — 전액 유예 요청은 언제나 100%라 기준이 되지 못한다.
    """
    score = int(facts.get("credit_score", 0))
    min_score = int(policy.get("min_credit_score", 85))
    amount = float(facts.get("amount_usdc", 0))
    limit_pct = float(policy.get("defer_max_pct", 20))
    credit_limit = float(facts.get("credit_limit_usdc", 0))
    exposure = (amount / credit_limit * 100) if credit_limit else 0

    if score < min_score:
        return {
            "decision": "reject",
            "reasoning": f"신용점수 {score}점으로 기준({min_score}점)에 미달해 유예를 수락할 수 없습니다.",
        }
    if credit_limit and exposure > limit_pct:
        return {
            "decision": "counter",
            "reasoning": (
                f"유예액 {amount} USDC가 외상 한도 {credit_limit:g} USDC의 {exposure:.0f}%로 "
                f"허용치 {limit_pct:.0f}%를 넘어 분할을 제안합니다."
            ),
        }
    return {
        "decision": "accept",
        "reasoning": (
            f"신용점수 {score}점으로 기준({min_score}점)을 충족하고 {facts.get('history', '납부 이력')}이 양호합니다. "
            f"유예액은 외상 한도의 {exposure:.0f}%로 허용치({limit_pct:.0f}%) 안이므로 "
            f"{facts.get('pay_when', '제시 시점')} 납부를 수락합니다."
        ),
    }


def narrate(facts: list[str], reasoning: list[str]) -> str:
    """보고문 — mock에서는 사실을 그대로 이어 붙인다."""
    return " ".join(facts[-2:]) if facts else ""
