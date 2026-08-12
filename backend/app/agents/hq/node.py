"""본사 그래프의 노드.

가맹점 그래프와 대칭이다. 가맹점이 "내가 낼까 말까"를 판단한다면,
본사는 "받아줄까 말까"를 판단한다. 판단이 필요한 두 노드(review_*)만 LLM을 부른다.
"""

from app.agents import utils
from app.agents.hq import tools
from app.agents.hq.state import HQState
from app.core import policy as policy_mod
from app.llm import judge


def load_context(state: HQState) -> dict:
    """본사 정책을 DB에서 읽고 처리 대상(청구서 또는 직거래 건)을 집는다."""
    pol = policy_mod.get("hq")
    context: dict = {"policy": pol.as_prompt_values()}
    if state.get("invoice_id"):
        invoice = utils.get_invoice(state["invoice_id"])
        if not invoice:
            return {
                **context,
                "outcome": "noop",
                "messages": [f"청구서를 찾을 수 없습니다: {state['invoice_id']}"],
            }
        context["invoice"] = invoice
    if state.get("trade_id"):
        trade = utils.get_trade(state["trade_id"])
        if not trade:
            return {
                **context,
                "outcome": "noop",
                "messages": [f"직거래 건을 찾을 수 없습니다: {state['trade_id']}"],
            }
        context["trade"] = trade
    return context


def issue_invoice(state: HQState) -> dict:
    """납품 완료 → 청구서 발행."""
    invoice = tools.create_invoice(state["delivery_id"])
    if invoice.get("error"):
        return {"outcome": "noop", "messages": [invoice["error"]]}
    return {
        "invoice": invoice,
        "invoice_id": invoice["id"],
        "outcome": "negotiating",
        "messages": [
            (
                f"{invoice['store_id']} 앞으로 청구서 {invoice['id']}를 "
                f"{invoice['amount_usdc']} USDC로 발행했습니다."
            )
        ],
    }


def review_adjustment(state: HQState) -> dict:
    """차감 제안 심사 — 납품 로그와 대조해 근거를 검증한 뒤 LLM이 결정한다."""
    invoice = state["invoice"]
    proposal = state.get("payload", {})
    requested = float(proposal.get("deduction_usdc", 0))

    # 제안이 사실인지는 코드가 확인한다. LLM은 그 사실 위에서 판단만 한다.
    received = utils.receiving_log(invoice["store_id"], invoice["delivery_id"])
    discrepancies = utils.find_discrepancies(invoice["items"], received)
    verified = utils.total_over_billed(discrepancies)

    verdict = judge.review_proposal(
        "adjustment",
        facts={
            "invoice_id": invoice["id"],
            "amount_usdc": invoice["amount_usdc"],
            "deduction_usdc": requested,
            "verified_over_billed": verified,
            "detail": utils.describe_discrepancies(discrepancies) or "불일치 없음",
            "store_id": invoice["store_id"],
        },
        policy_values=policy_mod.get("hq").as_prompt_values()
        | {"auto_adjust_limit_usdc": policy_mod.get("hq").auto_adjust_limit_usdc},
    )
    tools.record_decision(
        invoice["id"], "adjustment", f"검수 불일치분 {requested} USDC 차감 요청",
        verdict["decision"], verdict["reasoning"],
    )
    return {
        "decision": {**verdict, "kind": "adjustment", "verified_over_billed": verified},
        "reasoning": [verdict["reasoning"]],
    }


def apply_adjustment(state: HQState) -> dict:
    """차감 수락 시 청구서를 정정해 재발행한다."""
    invoice = state["invoice"]
    deduction = state["decision"]["verified_over_billed"]
    new_amount = round(invoice["amount_usdc"] - deduction, 2)
    updated = tools.adjust_invoice(invoice["id"], new_amount, "검수 불일치 차감 합의")
    return {
        "invoice": updated,
        "outcome": "negotiating",
        "messages": [f"차감을 수락하고 청구서를 {new_amount} USDC로 재발행했습니다."],
    }


def review_deferral(state: HQState) -> dict:
    """유예 제안 심사 — 신용 이력과 정책 한도를 근거로 LLM이 결정한다."""
    invoice = state["invoice"]
    proposal = state.get("payload", {})
    credit = tools.store_credit(invoice["store_id"])
    pol = policy_mod.get("hq")

    verdict = judge.review_proposal(
        "deferral",
        facts={
            "invoice_id": invoice["id"],
            "store_id": invoice["store_id"],
            "amount_usdc": invoice["amount_usdc"],
            "credit_score": credit["credit_score"],
            "credit_limit_usdc": credit["credit_limit_usdc"],
            "history": (
                f"납부 이력 정시납 {credit['on_time']}건 · 연체 {credit['late']}건 · "
                f"분쟁 {credit['disputed']}건"
            ),
            "pay_when": proposal.get("pay_when", "미지정"),
            "reason": proposal.get("reason", ""),
        },
        policy_values=pol.as_prompt_values(),
    )
    negotiation = tools.record_decision(
        invoice["id"], "deferral",
        f"납부 유예 요청 ({proposal.get('pay_when', '시점 미지정')})",
        verdict["decision"], verdict["reasoning"],
    )

    if verdict["decision"] == "counter":
        # 역제안은 즉시 집행하지 않는다 — 조건을 되돌려 지점의 재응수를 받는다.
        # 집행(분할 발행)은 라운드 3의 settle_negotiation 몫이다 (협상 다회 왕복).
        per = round(invoice["amount_usdc"] / pol.installment_max, 2)
        counter_terms = {"kind": "installment", "parts": pol.installment_max, "per_usdc": per}
        return {
            "decision": {**verdict, "kind": "deferral", "counter_terms": counter_terms},
            "outcome": "negotiating",
            "messages": [
                (
                    f"전액 유예 대신 {pol.installment_max}회 분할(회당 {per} USDC)을 "
                    f"역제안했습니다 — 지점의 응답을 기다립니다. "
                )
                + verdict["reasoning"]
            ],
            "reasoning": [verdict["reasoning"]],
            "proposal": negotiation,
        }

    accepted = verdict["decision"] == "accept"
    return {
        "decision": {**verdict, "kind": "deferral"},
        "outcome": "scheduled" if accepted else "negotiating",
        "messages": [
            ("유예를 수락하고 예약으로 전환했습니다. " if accepted else "유예를 거절했습니다. ")
            + verdict["reasoning"]
        ],
        "reasoning": [verdict["reasoning"]],
        "proposal": negotiation,
    }


def settle_negotiation(state: HQState) -> dict:
    """(협상 종결) 합의를 집행하거나, 결렬을 사람 승인 큐로 넘긴다.

    합의 집행 = 분할 청구서 발행. 지점 수정안(선납)이 오면 코드가 잔여 노출을
    계산하고 정책 한도로 판정한다 — 사실은 코드, 집행은 문서, 결렬 정리는 사람.
    """
    invoice = state["invoice"]
    payload = state.get("payload", {})

    if payload.get("failed"):
        reason = payload.get("reason", "협상 결렬")
        # 결렬도 협상 기록으로 남긴다 — 안 남기면 스레드가 "응답 대기"로 영원히 멈춰 보인다
        tools.record_decision(invoice["id"], "counter_settle", "협상 결렬", "reject", reason)
        tools.escalate_negotiation(invoice["id"], reason)
        return {
            "outcome": "needs_human",
            "messages": [f"협상이 결렬됐습니다 — 사람 결정으로 넘깁니다. 사유: {payload.get('reason', '')}"],
            "reasoning": ["자율 협상의 경계 — 합의 실패는 에이전트가 아니라 사람이 정리한다"],
        }

    pol = policy_mod.get("hq")
    agreement = payload.get("agreement", {})
    parts = int(agreement.get("parts") or pol.installment_max)
    first = agreement.get("first_usdc")

    if first is not None:
        # 수정안 판정 — 선납 후 잔여가 외상 한도의 defer_max_pct 안이어야 한다
        credit = tools.store_credit(invoice["store_id"])
        remaining = round(invoice["amount_usdc"] - float(first), 2)
        exposure = remaining / max(credit["credit_limit_usdc"], 0.01) * 100
        if exposure > pol.defer_max_pct:
            reason = (
                f"선납 {first} USDC 후 잔여 {remaining} USDC가 외상 한도의 {exposure:.0f}% — "
                f"허용 {pol.defer_max_pct:g}%를 넘습니다"
            )
            tools.record_decision(invoice["id"], "counter_settle", "지점 수정안(선납 분할)", "reject", reason)
            tools.escalate_negotiation(invoice["id"], reason)
            return {
                "outcome": "needs_human",
                "messages": [f"수정안을 수용할 수 없습니다 — {reason}. 사람 결정으로 넘깁니다."],
                "reasoning": [reason],
            }
        tools.record_decision(
            invoice["id"], "counter_settle", "지점 수정안(선납 분할)", "accept",
            f"선납 후 잔여 노출 {exposure:.0f}% ≤ 허용 {pol.defer_max_pct:g}% — 수정안 수용",
        )

    split = tools.split_invoice(invoice["id"], parts=parts, first_usdc=first)
    if split.get("error"):
        return {"outcome": "noop", "messages": [split["error"]]}
    return {
        "outcome": "scheduled",
        "decision": {"kind": "deferral", "settled": True, "split": split},
        "messages": [
            f"협상 타결 — {parts}회 분할로 집행했습니다 (1회차 {split['per_usdc']} USDC 즉시, 나머지 예약)."
        ],
        "reasoning": ["합의 조건을 분할 청구서로 즉시 집행 — 협상의 결과는 말이 아니라 문서다"],
    }


def verify_settlement(state: HQState) -> dict:
    """결제 트랜잭션을 온체인에서 대조하고 정산을 확정한다."""
    signature = state.get("payload", {}).get("tx_signature") or state.get("tx_signature", "")
    if not signature:
        return {"outcome": "noop", "messages": ["검증할 트랜잭션 서명이 없습니다."]}

    result = tools.verify_payment(state["invoice_id"], signature)
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]]}

    if result["verified"]:
        return {
            "outcome": "settled",
            "tx_signature": signature,
            "messages": [f"온체인 대조 완료 — 정산을 확정했습니다. tx {signature[:16]}…"],
            "reasoning": ["금액·수취인·청구서번호 3중 대조 일치"],
        }
    return {
        "outcome": "noop",
        "messages": [
            (
                "온체인 검증에 실패해 정산을 확정하지 않았습니다 "
                f"(금액 일치 {result['amount_ok']}, 메모 일치 {result['memo_ok']})."
            )
        ],
    }


def review_p2p(state: HQState) -> dict:
    """가맹점 간 직거래 심사 — 안전재고·양측 신용·가격을 근거로 LLM이 결정한다.

    본사가 완전히 빠지지 않는 이유: 프랜차이즈의 위생·품질 책임은 본사에 있다.
    자율성(지점끼리 협상)과 통제(본사 승인)의 경계가 여기다.
    """
    trade = state["trade"]
    from app.agents.store import tools as store_tools  # 잉여 재검증용 조회

    seller_inventory = store_tools.check_inventory(trade["seller_id"])["inventory"]
    buyer_credit = tools.store_credit(trade["buyer_id"])
    seller_credit = tools.store_credit(trade["seller_id"])
    hq_terms = utils.hq_reorder_terms(trade["sku"])

    verdict = judge.review_proposal(
        "p2p_trade",
        facts={
            "trade_id": trade["id"],
            "sku": trade["sku"],
            "qty": trade["qty"],
            "unit_price_usdc": round(trade["price_usdc"] / trade["qty"], 4),
            "hq_unit_price_usdc": hq_terms.get("unit_price_usdc", 0),
            "seller_surplus": utils.sellable_surplus(seller_inventory, trade["sku"]),
            "buyer_credit_score": buyer_credit["credit_score"],
            "seller_credit_score": seller_credit["credit_score"],
            "buyer_basis": trade.get("basis") or "제공 안 됨",  # 구매측이 산 시세 근거
        },
        policy_values=policy_mod.get("hq").as_prompt_values()
        | {"p2p_min_credit_score": policy_mod.get("hq").p2p_min_credit_score},
    )
    updated = tools.review_p2p_trade(trade["id"], verdict["decision"], verdict["reasoning"])
    approved = verdict["decision"] == "accept"
    return {
        "trade": updated,
        "decision": {**verdict, "kind": "p2p_trade"},
        "outcome": "negotiating" if approved else "refused",
        "messages": [("직거래를 승인했습니다. " if approved else "직거래를 승인하지 않았습니다. ") + verdict["reasoning"]],
        "reasoning": [verdict["reasoning"]],
    }


def record_p2p(state: HQState) -> dict:
    """확정된 직거래를 본사 장부에 기록한다."""
    result = tools.record_p2p_settlement(state["trade_id"])
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]]}
    return {
        "outcome": "settled",
        "messages": [
            (
                f"직거래 {result['id']}({result['buyer_id']} → {result['seller_id']}, "
                f"{result['price_usdc']} USDC)를 본사 장부에 기록했습니다. "
                "본사를 거치지 않은 거래도 같은 장부에서 투명하게 보입니다."
            )
        ],
    }


def report(state: HQState) -> dict:
    if not state.get("messages") or state.get("outcome") == "noop":
        return {}  # noop 판엔 LLM 요약을 쓰지 않는다 — 협상 왕복의 호출 예산
    summary = judge.narrate(
        agent="hq",
        prompt_values=state.get("policy", {}),
        facts=state["messages"],
        reasoning=state.get("reasoning", []),
    )
    return {"messages": [summary] if summary else []}


# ── 분기 조건 ────────────────────────────────────────────────────────

_INTENT_ROUTE = {
    "invoice.issue": "issue",
    "proposal.adjustment": "review_adjustment",
    "proposal.deferral": "review_deferral",
    "proposal.settle": "settle",
    "payment.verify": "verify",
    "p2p.review": "review_p2p",
    "p2p.record": "record_p2p",
}


def route_intent(state: HQState) -> str:
    if state.get("outcome") == "noop":
        return "end"
    return _INTENT_ROUTE.get(state.get("intent", ""), "end")


def route_after_adjustment(state: HQState) -> str:
    return "apply" if state["decision"]["decision"] == "accept" else "report"
