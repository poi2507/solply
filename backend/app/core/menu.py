"""SFC 메뉴 — 손님은 요리를 주문하고, 레시피가 재료(SKU)로 풀려 재고에서 빠진다.

가격은 여기서 계산한다: Σ(재료 공급가 × 수량) × RETAIL_MARGIN. 메뉴에 값을 따로 두면
식자재 시세와 어긋난다 — 요리 값이 곧 물대 정산과 직결된다는 게 이 상점의 요점이다.

메뉴·레시피·브랜드는 fixtures.json(`menu`, `brand`)에 있다. 코드는 읽기만 한다.
"""

from app.agents import utils
from app.core import economy, fixtures

# 방문자 한 번의 주문 상한 — 진열대 보호. 구매 1회 3개(api/shop.py Purchase)의 연장이다.
MAX_SERVINGS_PER_ORDER = 6


class OrderError(ValueError):
    """주문을 받을 수 없는 이유 — API가 4xx로 바꾼다."""


def brand() -> dict:
    return fixtures.load().get("brand") or {"name": "Solply Store", "short": "Solply", "tagline": ""}


def items() -> dict[str, dict]:
    return fixtures.load().get("menu", {}).get("items", {})


def sold_at(item: dict, store_id: str) -> bool:
    stores = item.get("stores")
    return not stores or store_id in stores


def price_of(item: dict) -> float:
    supply = sum(economy._sku_price(sku) * n for sku, n in item["recipe"].items())
    return round(supply * economy.RETAIL_MARGIN, 2)


def servings(item: dict, inventory: dict[str, dict]) -> int:
    """지금 재고로 몇 인분 — 레시피 재료 중 가장 모자란 것이 정한다."""
    return min((inventory.get(sku, {}).get("qty", 0) // n for sku, n in item["recipe"].items()),
               default=0)


def items_for(store_id: str) -> list[dict]:
    """그 지점의 메뉴판 — 값·지금 가능한 인분·레시피(재료 이름 포함)."""
    inv = utils.effective_inventory(store_id)
    out = []
    for iid, it in items().items():
        if not sold_at(it, store_id):
            continue
        out.append({
            "id": iid,
            "name": it["name"],
            "blurb": it.get("blurb", ""),
            "price_usdc": price_of(it),
            "servings": servings(it, inv),
            "exclusive": bool(it.get("stores")),
            "recipe": [{"sku": sku, "name": inv.get(sku, {}).get("name", sku), "qty": n}
                       for sku, n in it["recipe"].items()],
        })
    return out


def expand(store_id: str, cart: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """장바구니 → (검증된 주문 줄, 재료 총량). 전부 되거나 전부 안 된다 — 반쪽 주문은 없다."""
    menu = items()
    inv = utils.effective_inventory(store_id)
    lines: list[dict] = []
    need: dict[str, int] = {}
    total_servings = 0
    for row in cart:
        iid = row.get("item_id")
        try:
            qty = int(row.get("qty", 0))
        except (TypeError, ValueError):
            raise OrderError(f"bad quantity for {iid}") from None
        it = menu.get(iid)
        if not it or not sold_at(it, store_id):
            raise OrderError(f"not on this store's menu: {iid}")
        if qty < 1:
            raise OrderError(f"quantity must be at least 1: {it['name']}")
        total_servings += qty
        for sku, n in it["recipe"].items():
            need[sku] = need.get(sku, 0) + n * qty
        unit = price_of(it)
        lines.append({"item_id": iid, "name": it["name"], "qty": qty,
                      "unit_usdc": unit, "subtotal_usdc": round(unit * qty, 2)})
    if not lines:
        raise OrderError("empty cart")
    if total_servings > MAX_SERVINGS_PER_ORDER:
        raise OrderError(f"up to {MAX_SERVINGS_PER_ORDER} servings per order")
    short = [(sku, n, inv.get(sku, {}).get("qty", 0)) for sku, n in need.items()
             if inv.get(sku, {}).get("qty", 0) < n]
    if short:
        detail = ", ".join(f"{inv.get(s, {}).get('name', s)} (have {have}, need {n})"
                           for s, n, have in short)
        raise OrderError(f"not enough stock for this order — {detail}")
    return lines, need
