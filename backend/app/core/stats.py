"""본사 수익 계기판 — 지표는 이벤트 스캔이 아니라 계수기로.

로열티·데이터 판매가 발생하는 그 자리에서 누적한다. 이벤트 로그를 매번
합산하면 로그가 자랄수록 대시보드가 느려진다 — 계수기 문서 하나가 답이다.
"""

from app.db import store as db

DOC = "hq_revenue"


def add(kind: str, amount: float) -> None:
    """수익 한 건 누적 — kind: royalty | data_sales."""
    doc = db.get("stats", DOC) or {}
    doc[f"{kind}_usdc"] = round(doc.get(f"{kind}_usdc", 0.0) + amount, 2)
    doc[f"{kind}_count"] = doc.get(f"{kind}_count", 0) + 1
    db.put("stats", DOC, doc)


def snapshot() -> dict:
    return db.get("stats", DOC) or {}
