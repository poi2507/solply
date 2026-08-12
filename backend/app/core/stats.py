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


def add_card_flow(store_id: str, net: float, royalty: float) -> None:
    """카드정산 흐름의 하루 계수기 — 다이어그램이 이벤트를 스캔하지 않게 한다."""
    from app.core import kst

    key = f"flows-{kst.today()}"
    doc = db.get("stats", key) or {}
    card = doc.get("card", {})
    card[store_id] = round(card.get(store_id, 0.0) + net, 2)
    # 문서 전체를 새로 만들면 다른 흐름(손님 유입)이 지워진다 — 제자리 갱신만 (8/12 실측)
    doc["card"] = card
    doc["royalty_usdc"] = round(doc.get("royalty_usdc", 0.0) + royalty, 2)
    db.put("stats", key, doc)


def card_flows(day: str) -> dict:
    """그 날의 카드정산 흐름. 계수기가 없던 날은 이벤트를 한 번만 훑고 결과를 굳힌다."""
    key = f"flows-{day}"
    doc = db.get("stats", key)
    if doc is None:
        card: dict[str, float] = {}
        royalty = 0.0
        for e in db.recent_events(2000, day=day, action="card.settled"):
            payload = e["payload"]
            sid = payload.get("store_id")
            card[sid] = round(card.get(sid, 0.0) + float(payload.get("amount_usdc") or 0), 2)
            royalty = round(royalty + float(payload.get("royalty_usdc") or 0), 2)
        doc = db.put("stats", key, {"card": card, "royalty_usdc": royalty})
    return doc


def add_guest_flow(store_id: str, amount: float) -> None:
    """손님 매출의 하루 계수기 — 전체와 지점별을 함께 센다 (지점 화면의 흐름도용)."""
    from app.core import kst

    key = f"flows-{kst.today()}"
    doc = db.get("stats", key) or {}
    doc["guest_usdc"] = round(doc.get("guest_usdc", 0.0) + amount, 2)
    guest = doc.get("guest", {})
    guest[store_id] = round(guest.get(store_id, 0.0) + amount, 2)
    doc["guest"] = guest
    db.put("stats", key, doc)
