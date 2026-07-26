"""Mock 에이전트 — Gemini를 호출하지 않고 도구를 규칙대로 실행한다.

용도: 데모 리허설과 UI 확인. 무료 티어 rate limit(모델당 분당 5회) 때문에
실제 Gemini로는 전체 시나리오 한 번에 10분 넘게 걸린다. mock은 몇 초면 끝난다.

LLM_PROVIDER=mock 으로 켠다. 도구 자체는 진짜를 호출하므로
**온체인 트랜잭션은 실제로 발생한다** — 판단 주체만 규칙으로 대체된다.
"""

from typing import Any, Callable


class MockAgent:
    """ADK Agent와 같은 자리에 끼워 넣는 대역.

    plan(prompt) 이 반환한 (도구이름, 인자) 순서대로 실행한다.
    """

    def __init__(self, name: str, tools: list[Callable], planner: Callable[[str, dict], list]):
        self.name = name
        self.tools = {fn.__name__: fn for fn in tools}
        self._planner = planner

    def plan(self, prompt: str) -> list[tuple[str, dict]]:
        return self._planner(prompt, self.tools)


def _find_invoice_id(prompt: str) -> str | None:
    import re

    match = re.search(r"INV-[0-9a-f]{8}", prompt)
    return match.group(0) if match else None


def hq_planner(prompt: str, tools: dict) -> list[tuple[str, dict]]:
    """본사 에이전트의 규칙 기반 판단."""
    import re

    invoice_id = _find_invoice_id(prompt)

    delivery = re.search(r"DEL-\d+", prompt)
    if delivery and "청구서를 발행" in prompt:
        return [("create_invoices", {"delivery_id": delivery.group(0)})]

    if "차감을 제안" in prompt and invoice_id:
        amount = re.search(r"차감 요청액[:\s]*([\d.]+)", prompt)
        deduction = float(amount.group(1)) if amount else 0.0
        invoice = tools["get_invoice"](invoice_id)
        new_amount = round(invoice["amount_usdc"] - deduction, 2)
        return [
            (
                "review_proposal",
                {
                    "invoice_id": invoice_id,
                    "proposal_type": "adjustment",
                    "proposal_detail": f"검수 불일치분 {deduction} USDC 차감 요청",
                    "decision": "accept",
                    "reasoning": f"납품 로그 대조 결과 불일치 확인. {deduction} USDC 차감이 타당.",
                },
            ),
            (
                "adjust_invoice_amount",
                {
                    "invoice_id": invoice_id,
                    "new_amount_usdc": new_amount,
                    "reason": "검수 불일치 차감 합의",
                },
            ),
        ]

    if "유예를 제안" in prompt and invoice_id:
        invoice = tools["get_invoice"](invoice_id)
        profile = tools["get_store_profile"](invoice["store_id"])
        score = profile.get("credit_score", 0)
        accept = score >= 85
        when = re.search(r"납부 예정[:\s]*([^/]+)", prompt)
        return [
            (
                "review_proposal",
                {
                    "invoice_id": invoice_id,
                    "proposal_type": "deferral",
                    "proposal_detail": f"납부 유예 요청 ({(when.group(1).strip() if when else '기한 내')})",
                    "decision": "accept" if accept else "reject",
                    "reasoning": (
                        f"신용점수 {score}점으로 기준(85) 충족, 납부기한 내 제안이므로 수락."
                        if accept
                        else f"신용점수 {score}점으로 기준(85) 미달하여 거절."
                    ),
                },
            )
        ]

    if "검증하고 정산" in prompt and invoice_id:
        sig = re.search(r"트랜잭션 ([1-9A-HJ-NP-Za-km-z]{60,})", prompt)
        if sig:
            return [("verify_payment", {"invoice_id": invoice_id, "tx_signature": sig.group(1)})]

    return []


def store_planner(prompt: str, tools: dict) -> list[tuple[str, dict]]:
    """가맹점 에이전트의 규칙 기반 판단 — 실제 에이전트의 지시문과 같은 순서."""
    invoice_id = _find_invoice_id(prompt)
    if not invoice_id:
        return []

    if "조정했습니다" in prompt:
        return [("execute_payment", {"invoice_id": invoice_id})]

    plan: list[tuple[str, dict]] = [("verify_delivery", {"invoice_id": invoice_id})]
    verification = tools["verify_delivery"](invoice_id)

    if not verification.get("match"):
        total = round(sum(d["over_billed_usdc"] for d in verification["discrepancies"]), 2)
        names = ", ".join(f"{d['name']} {d['invoiced_qty']}→{d['received_qty']}" for d in verification["discrepancies"])
        plan.append(
            (
                "propose_adjustment",
                {"invoice_id": invoice_id, "deduction_usdc": total, "reason": f"검수 불일치: {names}"},
            )
        )
        return plan

    cash = tools["assess_cashflow"](invoice_id)
    plan.append(("assess_cashflow", {"invoice_id": invoice_id}))
    if cash.get("sufficient") and cash.get("within_auto_limit"):
        plan.append(("execute_payment", {"invoice_id": invoice_id}))
    else:
        forecast = cash.get("pos_forecast", {})
        plan.append(
            (
                "propose_deferral",
                {
                    "invoice_id": invoice_id,
                    "pay_when": forecast.get("inflow_date", "다음 정산일"),
                    "reason": (
                        f"현재 잔액 {cash['wallet_usdc']} USDC로 청구액 {cash['invoice_amount_usdc']} USDC 부족. "
                        f"{forecast.get('note', '')}"
                    ).strip(),
                },
            )
        )
    return plan
