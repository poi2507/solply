"""실사용 계측 — 실제 방문자가 한 일과 시뮬 배경 수요를 나란히, 섞지 않고.

8월까지의 숫자는 스케줄러가 우리 손님으로 우리 지점에 돈을 넣은 닫힌 시뮬레이션이라
traction이 아니다. 여기서는 config.TRACTION_SINCE(대회 시작일) 이후만 센다:

  실제 방문자  — 메뉴 주문(shop.order)과 재료 1개 구매(shop.sale). 온체인 결제가 된 것만 금액에 넣는다
  에이전트 반응 — 그 방문이 일으킨 즉시 조달(shop.trigger → shop.procured / procure_failed)
  시뮬 배경 수요 — 틱이 만든 판매 이동(sold, 실판매 표식이 없는 것). 비교용으로만 보인다

같은 원장(events · inventory_moves)을 읽는다 — 화면 숫자와 기록이 다른 곳에서 오면 안 된다.
"""

import statistics
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
           "procured": 0, "failed": 0, "sim_servings": 0, "real_servings": 0,
           "own_wallet_orders": 0, "own_wallet_usdc": 0.0}
    wallets: set[str] = set()

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

        paid = own_n = 0
        own_usdc = 0.0
        for e in orders + sales:
            p = e.get("payload") or {}
            if p.get("tx"):
                paid += float(p.get("amount_usdc") or 0)
                if p.get("payer") == "own_wallet":
                    own_n += 1
                    own_usdc += float(p.get("amount_usdc") or 0)
                    if p.get("wallet"):
                        wallets.add(p["wallet"])
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
                                  "trigger": p.get("trigger"), "payer": p.get("payer", "demo")})

        row = {"day": day, "orders": len(orders), "purchases": len(sales),
               "paid_usdc": round(paid, 2), "triggered": len(triggers),
               "procured": len(procured), "failed": len(failed),
               "real_servings": real, "sim_servings": sim,
               "own_wallet_orders": own_n, "own_wallet_usdc": round(own_usdc, 2)}
        daily.append(row)
        for k in tot:
            tot[k] = round(tot[k] + row[k], 2) if k.endswith("usdc") else tot[k] + row[k]

    recent_orders.sort(key=lambda o: o["ts"], reverse=True)
    for o in recent_orders:
        o["invoice_id"] = invoice_of.get(o["order_id"])
    return {
        "since": config.TRACTION_SINCE,
        "network": config.NETWORK,
        "simDemand": config.SIM_DEMAND_ENABLED,
        "totals": {**tot, "visitors": len(visitors), "own_wallets": len(wallets)},
        "daily": daily,
        "recentOrders": recent_orders[:6],
        "ledger": _ledger(recent_orders[:LEDGER_SIZE]),
        "decisions": decisions(),
        "notes": [
            "Visitors are counted from a salted hash of the IP; raw IPs are not stored.",
            "Unique visitors are only counted from Sep 23, when hashing began.",
            "Includes the team's own test orders.",
            ("Demo-wallet orders are paid from a shared customer wallet the project funds with devnet USDC; "
             "own-wallet orders are signed and paid by the visitor's own Phantom wallet, verified on-chain."),
        ],
    }


LEDGER_SIZE = 30


def _ledger(orders: list[dict]) -> list[dict]:
    """공개 증빙용 — 주문 결제 tx와, 그 주문이 일으킨 본사 발주 청구서의 결제 tx를 한 줄에.

    두 서명 모두 체인에서 직접 열어 볼 수 있다 — 숫자를 믿으라고 하지 않고 확인하게 한다.
    """
    rows = []
    for o in orders:
        inv = store.get("invoices", o["invoice_id"]) if o.get("invoice_id") else None
        rows.append({**o, "invoice": {
            "id": o["invoice_id"], "status": inv.get("status"), "amount_usdc": inv.get("amount_usdc"),
            "tx": inv.get("tx_sig"),
        } if inv else None})
    return rows


def _median(xs: list) -> int | None:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs)) if xs else None


def decisions() -> dict:
    """에이전트 판단을 누가 내렸나 — Jev(System One) / LLM(System Two) / 규칙.

    decision_log(judge.py가 판단마다 남김)를 그대로 센다. 'escalated'는 Jev에 먼저 물었지만
    확신도가 기준에 못 미쳐 LLM이 다시 판단한 건이다.
    """
    logs = [d for d in store.list_docs("decision_log")
            if (d.get("at") or "") >= config.TRACTION_SINCE]
    logs.sort(key=lambda d: d.get("at", ""))
    count = {"jev": 0, "llm": 0, "rules": 0}
    kinds: dict[str, dict] = {}
    escalated, jev_ms, llm_ms, conf = 0, [], [], []
    for d in logs:
        who = d.get("decider") or ("rules" if d.get("provider") == "mock" else "llm")
        count[who] = count.get(who, 0) + 1
        k = kinds.setdefault(d.get("kind", "?"), {"jev": 0, "llm": 0, "rules": 0, "escalated": 0})
        k[who] = k.get(who, 0) + 1
        fast = d.get("jev") or {}
        if fast:
            jev_ms.append(fast.get("ms"))
            conf.append(fast.get("confidence"))
            if who != "jev":
                escalated += 1
                k["escalated"] += 1
        if who == "llm" and not fast:
            llm_ms.append(d.get("latency_ms"))
    recent = [{
        "at": d.get("at"), "agent": d.get("agent"), "kind": d.get("kind"),
        "decision": d.get("decision"),
        "decider": d.get("decider") or ("rules" if d.get("provider") == "mock" else "llm"),
        "confidence": (d.get("jev") or {}).get("confidence"),
        "probabilities": (d.get("jev") or {}).get("probabilities"),
        "reasoning": (d.get("reasoning") or "")[:280],
    } for d in reversed(logs[-10:])]
    return {
        "total": len(logs), **count, "escalated": escalated,
        "jevAnswerMsMedian": _median(jev_ms),
        "llmDecisionMsMedian": _median(llm_ms),
        "confidenceMedian": (round(statistics.median([c for c in conf if c is not None]), 2)
                             if any(c is not None for c in conf) else None),
        "byKind": kinds,
        "recent": recent,
    }


def snapshot() -> dict:
    now = time.monotonic()
    if _CACHE["value"] is None or now - _CACHE["at"] > CACHE_TTL_S:
        _CACHE["value"] = compute()
        _CACHE["at"] = now
    return _CACHE["value"]
