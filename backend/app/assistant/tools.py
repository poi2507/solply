"""정산 어시스턴트의 도구 — 사람이 대시보드에서 하던 일을 그대로 감싼다.

어시스턴트는 돈을 직접 움직이지 못한다. 사람에게 있던 권한(조회·승인·반려·
예약 실행)만 도구로 갖고, 실제 결제는 여전히 LangGraph 에이전트가 정책 안에서
수행한다. 승인·반려·예약 실행은 기존 API 내부 함수를 그대로 호출한다 —
버튼과 대화가 같은 코드, 같은 증빙을 지난다.
"""

from fastapi import HTTPException

from app.core import report
from app.core import status as status_mod
from app.db import store as db


def get_settlement_overview() -> dict:
    """정산 현황 요약을 조회한다 — 청구서 상태별 건수·금액, 미수금, 지점 간 직거래."""
    invoices = db.list_docs("invoices")
    by_status: dict[str, int] = {}
    for inv in invoices:
        by_status[inv["status"]] = by_status.get(inv["status"], 0) + 1
    trades = db.list_docs("p2p_trades")
    return {
        "invoices_by_status": by_status,
        # 받을 돈의 정의는 core/status.py 하나에서만 온다 — 대시보드와 숫자가 갈라지지 않게
        "outstanding_usdc": round(
            sum(i["amount_usdc"] for i in invoices if status_mod.is_receivable(i["status"])), 2
        ),
        "settled_usdc": round(
            sum(i["amount_usdc"] for i in invoices
                if i["status"] == status_mod.InvoiceStatus.SETTLED), 2
        ),
        "recent_invoices": [
            {"id": i["id"], "store_id": i["store_id"], "amount_usdc": i["amount_usdc"],
             "status": i["status"]}
            for i in sorted(invoices, key=lambda d: d.get("updated_at", ""))[-10:]
        ],
        "p2p_trades": [
            {"id": t["id"], "buyer": t["buyer_id"], "seller": t["seller_id"],
             "amount_usdc": t["price_usdc"], "status": t["status"]}
            for t in trades
        ],
    }


def get_weekly_report() -> dict:
    """이번 주기 정산 통계를 조회한다 — 정산·협상·직거래·신용 변화·사람 개입 횟수."""
    return report.collect()


def get_store_credit(store_id: str) -> dict:
    """가맹점의 신용점수와 산출 근거(정시납·연체·분쟁, 이번 세션 온체인 가산)를 조회한다.

    Args:
        store_id: 지점 ID (store-a, store-b, store-c)
    """
    from app.agents.hq import tools as hq_tools

    return hq_tools.store_credit(store_id)


def list_pending_approvals() -> list[dict]:
    """사람 승인을 기다리는 결제 목록 — 자동결제 상한을 넘어 에이전트가 멈춘 건들."""
    return [
        {"id": d["id"], "store_id": d["store_id"], "amount_usdc": d["amount_usdc"]}
        for d in db.list_docs("invoices")
        if d["status"] == "pending_approval"
    ]


async def approve_payment(invoice_id: str) -> dict:
    """대기 중인 결제를 승인한다. 승인하면 지점 에이전트가 이어서 x402 왕복으로 결제한다.

    Args:
        invoice_id: 승인할 청구서 ID (예: INV-abc123)
    """
    from app.api.approvals import Decision, decide

    try:
        return await decide(invoice_id, Decision(decision="approve", note="어시스턴트 경유"))
    except HTTPException as exc:
        return {"error": exc.detail}


async def reject_payment(invoice_id: str, reason: str) -> dict:
    """대기 중인 결제를 반려한다. 반려하면 결제되지 않고 종결된다.

    Args:
        invoice_id: 반려할 청구서 ID
        reason: 반려 사유
    """
    from app.api.approvals import Decision, decide

    try:
        return await decide(invoice_id, Decision(decision="reject", note=f"어시스턴트 경유 — {reason}"))
    except HTTPException as exc:
        return {"error": exc.detail}


def list_scheduled_payments() -> list[dict]:
    """유예·분할 합의로 예약된 결제 목록을 조회한다."""
    return [
        {"id": d["id"], "store_id": d["store_id"], "amount_usdc": d["amount_usdc"],
         "installment": d.get("installment")}
        for d in db.list_docs("invoices")
        if d["status"] == "scheduled"
    ]


async def run_scheduled_payment(invoice_id: str) -> dict:
    """예약 납부를 지금 실행한다 (예약일 도래 시뮬레이션 — 카드정산 입금 포함).

    Args:
        invoice_id: 실행할 예약 청구서 ID
    """
    from app.api.schedules import RunOptions, run_scheduled

    try:
        return await run_scheduled(invoice_id, RunOptions(simulate_inflow=True))
    except HTTPException as exc:
        return {"error": exc.detail}


ALL = [
    get_settlement_overview,
    get_weekly_report,
    get_store_credit,
    list_pending_approvals,
    approve_payment,
    reject_payment,
    list_scheduled_payments,
    run_scheduled_payment,
]
