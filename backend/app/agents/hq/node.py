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
    """본사 정책을 DB에서 읽는다."""
    pol = policy_mod.get("hq")
    context: dict = {"policy": pol.as_prompt_values(), "_policy_raw": None}
    if state.get("invoice_id"):
        invoice = utils.get_invoice(state["invoice_id"])
        if not invoice:
            return {
                "policy": pol.as_prompt_values(),
                "outcome": "noop",
                "messages": [f"청구서를 찾을 수 없습니다: {state['invoice_id']}"],
            }
        context["invoice"] = invoice
    context.pop("_policy_raw")
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


def report(state: HQState) -> dict:
    if not state.get("messages"):
        return {}
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
    "payment.verify": "verify",
}


def route_intent(state: HQState) -> str:
    if state.get("outcome") == "noop":
        return "end"
    return _INTENT_ROUTE.get(state.get("intent", ""), "end")


def route_after_adjustment(state: HQState) -> str:
    return "apply" if state["decision"]["decision"] == "accept" else "report"
