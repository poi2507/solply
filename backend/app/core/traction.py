"""실사용 계측 — 실제 방문자가 한 일과 시뮬 배경 수요를 나란히, 섞지 않고.

8월까지의 숫자는 스케줄러가 우리 손님으로 우리 지점에 돈을 넣은 닫힌 시뮬레이션이라
traction이 아니다. 여기서는 config.TRACTION_SINCE(대회 시작일) 이후만 센다:

  실제 방문자  — 메뉴 주문(shop.order)과 재료 1개 구매(shop.sale). 온체인 결제가 된 것만 금액에 넣는다
  에이전트 반응 — 그 방문이 일으킨 즉시 조달(shop.trigger → shop.procured / procure_failed)
  시뮬 배경 수요 — 틱이 만든 판매 이동(sold, 실판매 표식이 없는 것). 비교용으로만 보인다

같은 원장(events · inventory_moves)을 읽는다 — 화면 숫자와 기록이 다른 곳에서 오면 안 된다.
"""

import time

from app import config
from app.core import economy, kst
from app.db import store

_CACHE: dict = {"at": 0.0, "value": None}
CACHE_TTL_S = 30  # 관리자 화면이 폴링해도 DB를 매번 훑지 않게


def _days() -> list[str]:
    today = kst.today()
    since = max(config.TRACTION_SINCE, store.first_day() or config.TRACTION_SINCE)
    days, d = [], since
    while d <= today and len(days) < 60:
        days.append(d)
        d = kst.shift(d, 1)
    return days


def _events(day: str, action: str) -> list[dict]:
    return store.recent_events(2000, day=day, action=action)


def compute() -> dict:
    daily = []
    visitors: set[str] = set()
    recent_orders: list[dict] = []
    invoice_of: dict[str, str] = {}
    tot = {"orders": 0, "purchases": 0, "paid_usdc": 0.0, "triggered": 0,
           "procured": 0, "failed": 0, "sim_servings": 0, "real_servings": 0}

    for day in _days():
        orders = _events(day, "shop.order")
        sales = _events(day, "shop.sale")
        triggers = [e for e in _events(day, "shop.trigger")
                    if (e.get("payload") or {}).get("mode") == "started"]
        procured = _events(day, "shop.procured")
        failed = _events(day, "shop.procure_failed")
        sim = real = 0
        for m in store.list_docs("inventory_moves", day=day, reason="sold"):
            if m.get("store_id") == "hq":
                continue
            n = abs(int(m.get("qty", 0)))
            if str(m.get("ref", "")).startswith(economy.LIVE_NOTE):
                real += n
            else:
                sim += n

        paid = 0.0
        for e in orders + sales:
            p = e.get("payload") or {}
            if p.get("tx"):
                paid += float(p.get("amount_usdc") or 0)
            if p.get("visitor"):
                visitors.add(p["visitor"])
        for e in procured:
            p = e.get("payload") or {}
            if p.get("order_id") and p.get("invoice_id"):
                invoice_of[p["order_id"]] = p["invoice_id"]
        for e in orders:
            p = e.get("payload") or {}
            recent_orders.append({"ts": e["ts"], "order_id": p.get("order_id"),
                                  "store_id": p.get("store_id"), "items": p.get("items", []),
                                  "amount_usdc": p.get("amount_usdc"), "tx": p.get("tx"),
                                  "trigger": p.get("trigger")})

        row = {"day": day, "orders": len(orders), "purchases": len(sales),
               "paid_usdc": round(paid, 2), "triggered": len(triggers),
               "procured": len(procured), "failed": len(failed),
               "real_servings": real, "sim_servings": sim}
        daily.append(row)
        for k in tot:
            tot[k] = round(tot[k] + row[k], 2) if k == "paid_usdc" else tot[k] + row[k]

    recent_orders.sort(key=lambda o: o["ts"], reverse=True)
    for o in recent_orders:
        o["invoice_id"] = invoice_of.get(o["order_id"])
    return {
        "since": config.TRACTION_SINCE,
        "simDemand": config.SIM_DEMAND_ENABLED,
        "totals": {**tot, "visitors": len(visitors)},
        "daily": daily,
        "recentOrders": recent_orders[:6],
        "notes": [
            "Visitors are counted from a salted hash of the IP; raw IPs are not stored.",
            "Unique visitors are only counted from Sep 23, when hashing began.",
            "Includes the team's own test orders.",
            ("Visitors pay from a shared demo customer wallet that the project funds with devnet USDC — "
             "the transfers are real on-chain transactions, but the money is not the visitor's own."),
        ],
    }


def snapshot() -> dict:
    now = time.monotonic()
    if _CACHE["value"] is None or now - _CACHE["at"] > CACHE_TTL_S:
        _CACHE["value"] = compute()
        _CACHE["at"] = now
    return _CACHE["value"]
