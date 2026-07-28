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


def review_p2p(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """가맹점 간 직거래 심사 — 판매측 안전재고, 양쪽 신용, 가격 상한(본사 공급가)을 본다.

    신용 기준은 유예(`min_credit_score`)가 아니라 직거래 전용 값이다 —
    직거래는 즉시 온체인 결제라 여신이 없고, 기준은 참가 자격 수준이면 충분하다.
    """
    qty = int(facts.get("qty", 0))
    surplus = int(facts.get("seller_surplus", 0))
    buyer_score = int(facts.get("buyer_credit_score", 0))
    seller_score = int(facts.get("seller_credit_score", 0))
    min_score = int(policy.get("p2p_min_credit_score", 75))
    unit = float(facts.get("unit_price_usdc", 0))
    hq_unit = float(facts.get("hq_unit_price_usdc", unit))

    if surplus < qty:
        return {
            "decision": "reject",
            "reasoning": f"판매 지점 잉여가 {surplus}개로 요청 수량 {qty}개에 못 미쳐 안전재고를 침범합니다.",
        }
    if min(buyer_score, seller_score) < min_score:
        return {
            "decision": "reject",
            "reasoning": (
                f"신용점수 기준({min_score}점) 미달 — 구매측 {buyer_score}점 / 판매측 {seller_score}점."
            ),
        }
    if unit > hq_unit:
        return {
            "decision": "counter",
            "reasoning": f"거래 단가 {unit} USDC가 본사 공급가 {hq_unit} USDC를 넘어 조정이 필요합니다.",
        }
    return {
        "decision": "accept",
        "reasoning": (
            f"판매측 잉여 {surplus}개 ≥ 요청 {qty}개로 안전재고가 지켜지고, "
            f"양측 신용 {buyer_score}/{seller_score}점이 기준({min_score}점)을 충족하며, "
            f"단가 {unit} USDC는 본사 공급가 이내입니다. 승인합니다."
        ),
    }


def narrate(facts: list[str], reasoning: list[str]) -> str:
    """보고문 — mock에서는 사실을 그대로 이어 붙인다."""
    return " ".join(facts[-2:]) if facts else ""


def weekly_report(stats: dict[str, Any]) -> str:
    """정산 리포트 — mock에서는 통계를 정형 문장으로 조립한다."""
    if not stats.get("settled_count") and not stats.get("p2p_count"):
        return ""
    neg = stats.get("negotiations", {})
    credit_line = " · ".join(
        f"{sid} {c['score']}점" + (f"(+{c['delta']})" if c.get("delta") else "")
        for sid, c in stats.get("credit", {}).items()
    )
    parts = [
        f"이번 주기 정산 {stats['settled_count']}건, {stats['settled_usdc']} USDC를 온체인으로 완결했습니다.",
        (
            f"협상은 수락 {neg.get('accept', 0)}건 · 역제안 {neg.get('counter', 0)}건 · "
            f"거절 {neg.get('reject', 0)}건이었고, 이상 청구 {stats['refused_count']}건을 거부해 "
            "사람에게 넘겼습니다."
        ),
    ]
    if stats.get("p2p_count"):
        parts.append(
            f"지점 간 직거래 {stats['p2p_count']}건({stats['p2p_usdc']} USDC)이 본사 승인 아래 체결됐습니다."
        )
    if stats.get("scheduled_count"):
        parts.append(f"예약 대기 {stats['scheduled_count']}건은 예약 실행기가 처리합니다.")
    parts.append(f"납부 이력 반영 신용점수: {credit_line}. 사람 개입은 {stats['human_actions']}회였습니다.")
    return " ".join(parts)
