"""가맹점 그래프의 노드.

노드 하나 = 판단 또는 실행 한 단계. 상태를 읽고 부분 갱신본을 돌려준다.
LLM이 필요한 노드는 `llm.judge()`를 호출하고, 나머지는 도구를 그대로 부른다.

노드를 이렇게 쪼갠 이유: 어디서 무슨 판단이 일어나는지가 그래프에 그대로 드러나야
발표에서 아키텍처를 설명할 수 있고, 실패한 단계만 재실행할 수 있다.
"""

from app.agents import utils
from app.agents.store import tools
from app.agents.store.state import StoreState
from app.core import policy as policy_mod
from app.llm import judge


def load_context(state: StoreState) -> dict:
    """정책을 DB에서 읽고 청구서를 집는다. 모든 경로의 시작점."""
    store_id = state["store_id"]
    pol = policy_mod.get(store_id)
    invoice = utils.get_invoice(state["invoice_id"], store_id=store_id) if state.get("invoice_id") else None

    if not invoice:
        return {
            "policy": pol.as_prompt_values(),
            "outcome": "noop",
            "messages": [f"처리할 청구서가 없습니다: {state.get('invoice_id')}"],
        }
    return {"policy": pol.as_prompt_values(), "invoice": invoice}


def verify_delivery(state: StoreState) -> dict:
    """청구 품목을 발주 내역·검수 기록과 대조한다.

    두 가지 이상을 구분한다: 발주한 품목의 수량 불일치는 협상(차감 제안) 대상이고,
    **발주한 적 없는 품목의 청구는 거부** 대상이다 — 깎아줄 문제가 아니라 내면 안 되는 돈이다.
    """
    store_id = state["store_id"]
    result = tools.verify_delivery(store_id, state["invoice_id"])

    suspects = utils.unordered_items(utils.store_orders(store_id), state["invoice"]["items"])
    if suspects:
        names = ", ".join(f"{i['name']} ×{i['qty']}" for i in suspects)
        total = round(sum(i["qty"] * i["unit_price_usdc"] for i in suspects), 2)
        return {
            "verification": {**result, "suspect_items": suspects},
            "messages": [f"발주 내역에 없는 품목이 청구됐습니다: {names} ({total} USDC)"],
            "reasoning": [f"발주 SKU 목록 대조 — {names}는 발주 기록이 없다"],
        }

    if result.get("match"):
        return {"verification": result, "messages": ["검수 대조 결과 일치합니다."]}

    total = utils.total_over_billed(result["discrepancies"])
    detail = utils.describe_discrepancies(result["discrepancies"])
    return {
        "verification": result,
        "messages": [f"검수 불일치 발견: {detail} (과청구 {total} USDC)"],
        "reasoning": [f"자체 검수 기록 대조 — {detail}"],
    }


def propose_adjustment(state: StoreState) -> dict:
    """불일치분 차감을 제안하고 결제를 보류한다."""
    discrepancies = state["verification"]["discrepancies"]
    total = utils.total_over_billed(discrepancies)
    reason = f"검수 불일치: {utils.describe_discrepancies(discrepancies)}"
    proposal = tools.propose_adjustment(state["store_id"], state["invoice_id"], total, reason)
    return {
        "proposal": proposal,
        "outcome": "negotiating",
        "messages": [f"본사에 {total} USDC 차감을 제안했습니다. 조정 전까지 결제를 보류합니다."],
    }


def request_terms(state: StoreState) -> dict:
    """본사에 정산을 요청한다 — 402 챌린지의 accepts[]가 협상 테이블이다."""
    result = tools.request_settlement_terms(state["store_id"], state["invoice_id"])
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]]}
    if result.get("already_settled"):
        return {"outcome": "noop", "messages": ["이미 정산이 끝난 청구서입니다."]}

    accepts = result["accepts"]
    labels = " · ".join(a.get("extra", {}).get("label", "?") for a in accepts)
    return {
        "x402_terms": accepts,
        "messages": [f"본사에 정산을 요청하니 402(Payment Required)와 결제 조건 {len(accepts)}개를 받았습니다: {labels}"],
    }


def assess_cashflow(state: StoreState) -> dict:
    """잔액·정책 한도·예상 입금으로 지불 여력을 본다."""
    cash = tools.assess_cashflow(state["store_id"], state["invoice_id"])
    return {"cashflow": cash}


def execute_payment(state: StoreState) -> dict:
    """402 조건 중 즉시 납부를 선택해 결제하고, 서명 제출로 정산 확정까지 받는다."""
    term = utils.pick_term(state.get("x402_terms", []), "immediate")
    result = tools.execute_payment(state["store_id"], state["invoice_id"], term=term)
    if result.get("status") == "needs_human_approval":
        return {
            "outcome": "needs_human",
            "messages": [result["reason"]],
            "reasoning": ["정책 상한 초과로 자동 결제를 중단했습니다."],
        }
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]], "tx_signature": result.get("signature", "")}

    if result.get("settled"):
        return {
            "outcome": "paid",
            "tx_signature": result["signature"],
            "messages": [
                (
                    f"즉시 납부 조건으로 {result['amount']} USDC를 결제하고 서명을 제출했습니다. "
                    f"본사가 온체인 대조 후 정산을 확정했습니다. tx {result['signature'][:16]}…"
                )
            ],
            "reasoning": ["402 조건 중 즉시 납부 선택 — 잔액·상한·하한 모두 충족"],
        }
    return {
        "outcome": "paid",
        "tx_signature": result["signature"],
        "messages": [f"{result['amount']} USDC를 결제했습니다. tx {result['signature'][:16]}…"],
    }


def escalate(state: StoreState) -> dict:
    """자동결제 상한을 넘는 청구 — 능력이 아니라 권한의 문제라 사람에게 넘긴다."""
    cash = state["cashflow"]
    reason = (
        f"청구액 {cash['invoice_amount_usdc']} USDC가 자동결제 상한 "
        f"{cash['auto_pay_limit_usdc']} USDC를 초과합니다."
    )
    tools.request_approval(state["store_id"], state["invoice_id"], reason)
    return {
        "outcome": "needs_human",
        "messages": [f"{reason} 결제를 보류하고 담당자 승인을 요청했습니다."],
        "reasoning": ["점주가 정한 상한을 넘는 금액이라 에이전트가 단독으로 결정하지 않았습니다."],
    }


def propose_deferral(state: StoreState) -> dict:
    """잔액이 모자라면 402 조건 중 유예를 선택하고, 예상 입금 일정을 근거로 제안한다."""
    cash = state["cashflow"]
    forecast = cash.get("pos_forecast", {})
    when = forecast.get("inflow_date", "다음 정산일")
    reason = (
        f"현재 잔액 {cash['wallet_usdc']} USDC로 청구액 {cash['invoice_amount_usdc']} USDC 부족. "
        f"{forecast.get('note', '')}"
    ).strip()
    proposal = tools.propose_deferral(state["store_id"], state["invoice_id"], when, reason)

    deferred = utils.pick_term(state.get("x402_terms", []), "deferred")
    picked = "402 조건 중 '납부 유예(본사 심사 필요)'를 선택했습니다. " if deferred else ""
    return {
        "proposal": proposal,
        "outcome": "negotiating",
        "messages": [f"{picked}{when}에 납부하겠다고 유예를 제안했습니다. 사유: {reason}"],
        "reasoning": [reason],
    }


def refuse(state: StoreState) -> dict:
    """이상 청구를 거부하고 사람에게 넘긴다."""
    suspects = state.get("verification", {}).get("suspect_items", [])
    if suspects:
        names = ", ".join(f"{i['name']} ×{i['qty']}" for i in suspects)
        reason = f"발주 내역에 없는 품목 청구: {names}"
    else:
        reason = state.get("payload", {}).get("refuse_reason") or "발주 내역에 없는 청구입니다."
    tools.refuse_payment(state["store_id"], state["invoice_id"], reason)
    return {
        "outcome": "refused",
        "messages": [f"결제를 거부하고 담당자에게 넘겼습니다. 사유: {reason}"],
        "reasoning": ["에이전트는 근거 없는 돈을 쓰지 않는다 — 거부 후 사람 확인"],
    }


def report(state: StoreState) -> dict:
    """지금까지의 판단을 사람이 읽는 한 문단으로 정리한다 (LLM)."""
    if not state.get("messages"):
        return {}
    summary = judge.narrate(
        agent="store",
        prompt_values=state.get("policy", {}),
        facts=state["messages"],
        reasoning=state.get("reasoning", []),
    )
    return {"messages": [summary] if summary else []}


# ── 분기 조건 ────────────────────────────────────────────────────────

def route_after_context(state: StoreState) -> str:
    """청구서가 없으면 끝, 재발행분·예약 실행분이면 검수를 건너뛰고 바로 정산 요청."""
    if state.get("outcome") == "noop":
        return "end"
    if state.get("intent") in ("invoice.pay_adjusted", "invoice.pay_scheduled"):
        return "request_terms"
    if state.get("payload", {}).get("suspect"):
        return "refuse"
    return "verify"


def route_after_verify(state: StoreState) -> str:
    """미발주 품목이면 거부, 수량 불일치면 협상, 일치할 때만 정산 테이블에 앉는다."""
    if state["verification"].get("suspect_items"):
        return "refuse"
    return "request_terms" if state["verification"]["match"] else "propose_adjustment"


def route_after_terms(state: StoreState) -> str:
    return "report" if state.get("outcome") == "noop" else "cashflow"


def route_after_cashflow(state: StoreState) -> str:
    """상한(권한)을 먼저 보고, 그 다음 잔액과 하한(능력)을 본다.

    순서가 중요하다. 상한 초과는 "이 금액은 애초에 에이전트가 정할 문제가 아니다"라는
    권한의 문제라, 잔액이 넉넉하든 아니든 사람에게 간다.
    """
    cash = state["cashflow"]
    if not cash.get("within_auto_limit", True):
        return "escalate"
    if not cash.get("sufficient") or not cash.get("keeps_reserve", True):
        return "propose_deferral"
    return "pay"
