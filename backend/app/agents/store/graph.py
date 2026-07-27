"""가맹점 에이전트 그래프.

    load_context
        ├─(청구서 없음)──────────────────────────► END
        ├─(이상 징후)────────► refuse ───────────► report ► END
        ├─(조정분 재청구)────► assess_cashflow ─┐
        └─► verify_delivery                     │
              ├─(불일치)─► propose_adjustment ──┼─► report ► END
              └─(일치)───► assess_cashflow ─────┤
                              ├─(상한 초과)─► escalate ────────┤
                              ├─(여력 있음)─► execute_payment ─┤
                              └─(부족·하한)─► propose_deferral ┘

한 번의 호출이 한 단계까지만 간다(제안을 내면 거기서 끝). 상대 에이전트의 응답은
오케스트레이터가 다음 호출로 넣어준다 — 협상은 그래프 안의 루프가 아니라
에이전트 사이의 왕복이기 때문이다.
"""

from functools import lru_cache

from langgraph.graph import END, StateGraph

from app.agents.store import node
from app.agents.store.state import StoreState


@lru_cache(maxsize=1)
def build():
    """그래프를 조립해 컴파일한다. 지점별로 다른 건 상태(store_id·정책)뿐이라 재사용한다."""
    g = StateGraph(StoreState)

    g.add_node("load_context", node.load_context)
    g.add_node("verify", node.verify_delivery)
    g.add_node("propose_adjustment", node.propose_adjustment)
    g.add_node("cashflow", node.assess_cashflow)
    g.add_node("pay", node.execute_payment)
    g.add_node("escalate", node.escalate)
    g.add_node("propose_deferral", node.propose_deferral)
    g.add_node("refuse", node.refuse)
    g.add_node("report", node.report)

    g.set_entry_point("load_context")
    g.add_conditional_edges(
        "load_context",
        node.route_after_context,
        {"verify": "verify", "cashflow": "cashflow", "refuse": "refuse", "end": END},
    )
    g.add_conditional_edges(
        "verify",
        node.route_after_verify,
        {"pay": "cashflow", "propose_adjustment": "propose_adjustment"},
    )
    g.add_conditional_edges(
        "cashflow",
        node.route_after_cashflow,
        {"pay": "pay", "escalate": "escalate", "propose_deferral": "propose_deferral"},
    )
    for terminal in ("propose_adjustment", "pay", "escalate", "propose_deferral", "refuse"):
        g.add_edge(terminal, "report")
    g.add_edge("report", END)

    return g.compile()
