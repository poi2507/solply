"""본사 에이전트 그래프.

    load_context ─┬─(invoice.issue)───────► issue_invoice ───────────┐
                  ├─(proposal.adjustment)─► review_adjustment ─┬─────┤
                  │                              (수락)─► apply_adjustment
                  ├─(proposal.deferral)───► review_deferral ─────────┤
                  ├─(payment.verify)──────► verify_settlement ───────┤
                  └─(그 외)───────────────────────────────► END      │
                                                                     ▼
                                                                  report ► END

intent로 갈래를 정한다 — 본사는 가맹점처럼 한 줄기 절차가 아니라
"무슨 요청이 왔는가"에 따라 다른 판단을 하기 때문이다.
"""

from functools import lru_cache

from langgraph.graph import END, StateGraph

from app.agents.hq import node
from app.agents.hq.state import HQState


@lru_cache(maxsize=1)
def build():
    g = StateGraph(HQState)

    g.add_node("load_context", node.load_context)
    g.add_node("issue", node.issue_invoice)
    g.add_node("review_adjustment", node.review_adjustment)
    g.add_node("apply", node.apply_adjustment)
    g.add_node("review_deferral", node.review_deferral)
    g.add_node("settle", node.settle_negotiation)  # 협상 종결 — 합의 집행 또는 결렬 정리
    g.add_node("verify", node.verify_settlement)
    g.add_node("review_p2p", node.review_p2p)
    g.add_node("record_p2p", node.record_p2p)
    g.add_node("review_order", node.review_order)  # 발주 수량 심사 — 시계열 판단
    g.add_node("broker", node.broker_match)        # 부분 잉여 직거래 중개
    g.add_node("report", node.report)

    g.set_entry_point("load_context")
    g.add_conditional_edges(
        "load_context",
        node.route_intent,
        {
            "issue": "issue",
            "review_adjustment": "review_adjustment",
            "review_deferral": "review_deferral",
            "settle": "settle",
            "verify": "verify",
            "review_p2p": "review_p2p",
            "record_p2p": "record_p2p",
            "review_order": "review_order",
            "broker": "broker",
            "end": END,
        },
    )
    g.add_conditional_edges(
        "review_adjustment", node.route_after_adjustment, {"apply": "apply", "report": "report"}
    )
    for terminal in ("issue", "apply", "review_deferral", "settle", "verify", "review_p2p", "record_p2p", "broker"):
        g.add_edge(terminal, "report")
    # 발주 심사는 매 발주마다 돌아 요약(narrate) 호출을 아낀다 — 근거는 협상 기록에 남는다
    g.add_edge("review_order", END)
    g.add_edge("report", END)

    return g.compile()
