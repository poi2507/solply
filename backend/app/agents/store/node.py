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
    """청구 품목을 검수 기록과 대조한다."""
    result = tools.verify_delivery(state["store_id"], state["invoice_id"])
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


def assess_cashflow(state: StoreState) -> dict:
    """잔액·정책 한도·예상 입금으로 지불 여력을 본다."""
    cash = tools.assess_cashflow(state["store_id"], state["invoice_id"])
    return {"cashflow": cash}


def execute_payment(state: StoreState) -> dict:
    """결제를 실행한다."""
    result = tools.execute_payment(state["store_id"], state["invoice_id"])
    if result.get("status") == "needs_human_approval":
        return {
            "outcome": "needs_human",
            "messages": [result["reason"]],
            "reasoning": ["정책 상한 초과로 자동 결제를 중단했습니다."],
        }
    if result.get("error"):
        return {"outcome": "noop", "messages": [result["error"]]}

    return {
        "outcome": "paid",
        "tx_signature": result["signature"],
        "messages": [f"{result['amount']} USDC를 결제했습니다. tx {result['signature'][:16]}…"],
    }


def propose_deferral(state: StoreState) -> dict:
    """잔액이 모자라면 예상 입금 일정을 근거로 유예를 제안한다."""
    cash = state["cashflow"]
    forecast = cash.get("pos_forecast", {})
    when = forecast.get("inflow_date", "다음 정산일")
    reason = (
        f"현재 잔액 {cash['wallet_usdc']} USDC로 청구액 {cash['invoice_amount_usdc']} USDC 부족. "
        f"{forecast.get('note', '')}"
    ).strip()
    proposal = tools.propose_deferral(state["store_id"], state["invoice_id"], when, reason)
    return {
        "proposal": proposal,
        "outcome": "negotiating",
        "messages": [f"{when}에 납부하겠다고 유예를 제안했습니다. 사유: {reason}"],
        "reasoning": [reason],
    }


def refuse(state: StoreState) -> dict:
    """이상 청구를 거부하고 사람에게 넘긴다."""
    reason = state.get("payload", {}).get("refuse_reason") or "발주 내역에 없는 청구입니다."
    tools.refuse_payment(state["store_id"], state["invoice_id"], reason)
    return {
        "outcome": "refused",
        "messages": [f"결제를 거부하고 담당자에게 전달했습니다. 사유: {reason}"],
        "reasoning": [reason],
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
    """청구서가 없으면 끝, 재발행분이면 검수를 건너뛴다."""
    if state.get("outcome") == "noop":
        return "end"
    if state.get("intent") == "invoice.pay_adjusted":
        return "cashflow"
    if state.get("payload", {}).get("suspect"):
        return "refuse"
    return "verify"


def route_after_verify(state: StoreState) -> str:
    return "pay" if state["verification"]["match"] else "propose_adjustment"


def route_after_cashflow(state: StoreState) -> str:
    """상한(자동결제 한도)과 하한(최소 보유 잔액)을 둘 다 본다."""
    cash = state["cashflow"]
    if not cash.get("sufficient") or not cash.get("keeps_reserve", True):
        return "propose_deferral"
    if not cash.get("within_auto_limit"):
        return "pay"  # 한도 초과는 execute_payment가 사람 승인으로 돌린다
    return "pay"
