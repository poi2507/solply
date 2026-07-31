"""정산 리포트 통계 — 이번 세션에 에이전트들이 처리한 것의 집계.

숫자는 여기서 모으고, 사람 언어로 바꾸는 건 `llm/judge.weekly_report`가 한다
(Gemini 또는 mock 규칙). 대시보드 `/api/report`와 데모 마무리가 같이 쓴다.
"""

from app.core import credit, fixtures
from app.core import status as status_mod
from app.db import store as db


def collect() -> dict:
    invoices = db.list_docs("invoices")
    settled = [i for i in invoices if i["status"] == "settled"]
    negotiations = db.list_docs("negotiations")
    trades = [t for t in db.list_docs("p2p_trades")
              if t["status"] == status_mod.TradeStatus.CONFIRMED]

    decisions: dict[str, int] = {}
    for n in negotiations:
        decisions[n["decision"]] = decisions.get(n["decision"], 0) + 1

    credit_lines = {}
    for sid in fixtures.load()["stores"]:
        rating = credit.evaluate(sid)
        credit_lines[sid] = {
            "score": rating["credit_score"],
            "delta": rating["live_settled"] * credit.ON_TIME_POINTS,
        }

    return {
        "settled_count": len(settled),
        "settled_usdc": round(sum(i["amount_usdc"] for i in settled), 2),
        "refused_count": sum(1 for i in invoices if i["status"] == "refused"),
        "scheduled_count": sum(1 for i in invoices if i["status"] == "scheduled"),
        "negotiations": decisions,
        "p2p_count": len(trades),
        "p2p_usdc": round(sum(t["price_usdc"] for t in trades), 2),
        "human_actions": sum(1 for e in db.list_events() if e["actor"] == "human"),
        "credit": credit_lines,
    }
