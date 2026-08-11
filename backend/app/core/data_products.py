"""데이터 상품 — 실거래가 남긴 흔적을 팔 수 있는 지수로 집계한다.

우리가 pay.sh에서 시세를 사듯(core/market.py), 우리 생태계의 체결 데이터를
같은 x402 규약으로 판다. 사는 것과 파는 것이 같은 상품 카테고리(시세)라
서사가 닫힌다 — "에이전트가 시세를 사서 흥정하고, 흥정이 남긴 체결가가
다시 시세가 되어 팔린다."

상품 두 종:
  market  체결가 지수 — 정산 완료 청구서 + 확정 직거래의 품목 단가.
          온체인 정산이 확인된 체결만 집계한다 (제3자 검증 가능한 실거래가).
  demand  수요 지수 — 재고 원장의 판매 이동량 (일평균·추세).

비식별 집계다 — 지점 식별자 없이 표본수·평균·추세만 나간다. 신용정보가
아니라 거래 통계라 판매에 별도 허가가 필요 없다 (신용 리포트를 상품에서
뺀 이유 — 그쪽은 신용정보법상 허가 산업이라 발표에서 비전으로만 다룬다).
"""

from datetime import UTC, datetime, timedelta

from app.db import store as db

WINDOW_DAYS = 7
PRODUCTS = ("market", "demand")


def _cutoff(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def market_index(sku: str) -> dict:
    """품목의 체결가 지수 — 최근 창(7일)의 가중 평균 단가와 직전 창 대비 추세."""

    def collect(since: str, until: str | None = None) -> tuple[float, float, int, int]:
        qty_sum, value, hq_n, p2p_n = 0.0, 0.0, 0, 0
        for inv in db.list_docs("invoices", status="settled"):
            ts = inv.get("updated_at", "")
            if ts < since or (until and ts >= until):
                continue
            for item in inv.get("items", []):
                if item.get("sku") == sku and item.get("qty"):
                    qty_sum += item["qty"]
                    value += item["qty"] * float(item.get("unit_price_usdc", 0))
                    hq_n += 1
        for trade in db.list_docs("p2p_trades", status="confirmed"):
            ts = trade.get("updated_at", "")
            if ts < since or (until and ts >= until):
                continue
            if trade.get("sku") == sku and trade.get("qty"):
                qty_sum += trade["qty"]
                value += float(trade.get("price_usdc", 0))
                p2p_n += 1
        return qty_sum, value, hq_n, p2p_n

    now_cut, prev_cut = _cutoff(WINDOW_DAYS), _cutoff(WINDOW_DAYS * 2)
    qty, value, hq_n, p2p_n = collect(now_cut)
    prev_qty, prev_value, _, _ = collect(prev_cut, now_cut)

    unit = round(value / qty, 4) if qty else None
    prev_unit = round(prev_value / prev_qty, 4) if prev_qty else None
    trend = round((unit - prev_unit) / prev_unit * 100, 1) if unit and prev_unit else None
    return {
        "product": "market",
        "sku": sku,
        "window_days": WINDOW_DAYS,
        "unit_price_usdc": unit,
        "samples": hq_n + p2p_n,
        "sources": {"hq_orders": hq_n, "p2p_trades": p2p_n},
        "trend_pct": trend,
        "basis": "온체인 정산이 확인된 체결만 집계 — 비식별 통계",
    }


def demand_index(sku: str) -> dict:
    """품목의 수요 지수 — 최근 창(7일)의 판매량과 직전 창 대비 추세."""

    def collect(since: str, until: str | None = None) -> tuple[int, set]:
        total, stores = 0, set()
        for move in db.list_docs("inventory_moves", reason="sold"):
            ts = move.get("updated_at", "")
            if ts < since or (until and ts >= until):
                continue
            if move.get("sku") == sku and move.get("store_id") != "hq":
                total += abs(int(move.get("qty", 0)))
                stores.add(move.get("store_id"))
        return total, stores

    now_cut, prev_cut = _cutoff(WINDOW_DAYS), _cutoff(WINDOW_DAYS * 2)
    total, stores = collect(now_cut)
    prev_total, _ = collect(prev_cut, now_cut)
    trend = round((total - prev_total) / prev_total * 100, 1) if prev_total else None
    return {
        "product": "demand",
        "sku": sku,
        "window_days": WINDOW_DAYS,
        "units_sold": total,
        "daily_avg": round(total / WINDOW_DAYS, 2),
        "reporting_stores": len(stores),
        "trend_pct": trend,
        "basis": "지점 POS 판매 이동량의 비식별 합산",
    }


def build(product: str, sku: str) -> dict | None:
    """상품 이름으로 지수를 만든다. 모르는 상품이면 None."""
    if product == "market":
        return market_index(sku)
    if product == "demand":
        return demand_index(sku)
    return None
