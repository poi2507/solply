from app.core.policy import HQPolicy

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
    limit = float(policy.get("auto_adjust_limit_usdc", HQPolicy.auto_adjust_limit_usdc))

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
        # LLM 판단의 기준선: 이력이 넉넉히 좋으면 최소 회차, 아니면 상한까지 잘게.
        parts = 2 if score >= min_score + 10 else int(policy.get("installment_max", 2))
        return {
            "decision": "counter",
            "parts": parts,
            "reasoning": (
                f"유예액 {amount} USDC가 외상 한도 {credit_limit:g} USDC의 {exposure:.0f}%로 "
                f"허용치 {limit_pct:.0f}%를 넘어 {parts}회 분할을 제안합니다."
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


def respond_counter(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """(지점) 본사 분할 역제안에 대한 응답 — 잔액이 결정한다.

    LLM이 못 뜰 때의 폴백이자, LLM 판단의 기준선이기도 하다.
    """
    per = float(facts.get("per_usdc") or 0)
    afford = float(facts.get("affordable_usdc") or 0)
    if per and afford >= per:
        return {"decision": "accept",
                "reasoning": f"가용액 {afford} USDC로 회당 {per} USDC를 감당할 수 있습니다."}
    if per and afford >= max(round(per * 0.3, 2), 0.1):
        return {"decision": "counter",
                "reasoning": f"회당 {per} USDC는 부담이지만 {afford} USDC 선납은 가능합니다."}
    return {"decision": "reject",
            "reasoning": f"가용액 {afford} USDC로는 선납 여력이 없습니다."}


def choose_supply_route(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """(지점) 조달 경로 — 이웃 잉여가 필요 수량을 덮으면 직거래."""
    need = float(facts.get("need_qty") or 0)
    surplus = float(facts.get("peer_surplus_qty") or 0)
    min_qty = float(facts.get("hq_min_order_qty") or 0)
    if surplus >= need and need < min_qty:
        return {"decision": "p2p",
                "reasoning": f"필요 {need:g}개는 최소 발주량 {min_qty:g}개 미만이고 이웃 잉여 {surplus:g}개로 덮입니다."}
    if surplus >= need:
        return {"decision": "p2p",
                "reasoning": f"이웃 잉여 {surplus:g}개로 오늘 인수 가능 — 리드타임을 기다리지 않습니다."}
    return {"decision": "hq",
            "reasoning": f"이웃 잉여 {surplus:g}개로는 필요 {need:g}개를 채우지 못합니다."}


def review_order(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """(본사) 발주 수량 심사 — 규칙 모드는 주문 수량을 그대로 이행한다.

    시계열의 '파동 vs 추세' 구분은 부등호로 흉내 낼 수 없는 판단이라 규칙을
    만들지 않는다 — LLM이 없으면 심사 없음이 기존 동작이고 가장 안전하다.
    """
    return {"decision": "accept",
            "reasoning": "규칙 모드 — 발주 수량 심사 없이 그대로 이행합니다.", "choice": -1}


def review_brokerage(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """(본사) 재고 중개 — 규칙 모드는 중개하지 않는다 (기존 동작 보존)."""
    return {"decision": "reject",
            "reasoning": "규칙 모드 — 지점 간 중개는 제안하지 않습니다.", "choice": -1}


def respond_order_trim(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """(지점) 축소 제안 응답 — 규칙 모드는 원 수량을 고수한다 (기존 동작 보존)."""
    return {"decision": "insist",
            "reasoning": "규칙 모드 — 자기 판매 원장 기준 원 수량을 유지합니다."}


def respond_p2p_price(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """(판매 지점) 직거래 가격 — 규칙 모드는 제안가에 수락한다 (기존 동작 보존)."""
    return {"decision": "accept",
            "reasoning": "규칙 모드 — 제안가 그대로 수락합니다."}


def decide_p2p_price(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """(구매 지점) 가격 역제안 응답 — 본사 공급가 이내면 수락, 넘으면 본사로."""
    counter = float(facts.get("counter_unit_usdc") or 0)
    hq_unit = float(facts.get("hq_unit_price_usdc") or 0)
    if hq_unit and counter > hq_unit + 1e-9:
        return {"decision": "hq",
                "reasoning": f"역제안 단가 {counter}가 본사 공급가 {hq_unit}를 넘어 본사 발주로 갑니다."}
    return {"decision": "accept",
            "reasoning": f"역제안 단가 {counter}는 본사 공급가({hq_unit}) 이내라 오늘 인수가 이득입니다."}


def consider_brokered(facts: dict[str, Any], policy: dict[str, Any]) -> dict[str, str]:
    """(구매 지점) 중개 제안 — 본사 공급가 기준 부분 수량이라 손해가 없어 수락."""
    return {"decision": "accept",
            "reasoning": "본사 공급가 기준 부분 인수 — 잔여는 본사 발주로 채웁니다."}


def narrate(facts: list[str], reasoning: list[str]) -> str:
    """보고문 — mock에서는 침묵한다.

    각 단계가 이미 자기 메시지를 냈으므로, 이어 붙여 재출력하면 리허설 화면에
    같은 문장이 두 번 찍힌다. 요약다운 요약은 Gemini 모드에서만 만든다.
    """
    return ""


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
