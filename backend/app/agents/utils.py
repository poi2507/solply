"""에이전트 공통 헬퍼.

두 에이전트가 반복하던 조회·계산·기록을 모았다. 도구 함수는 여기 있는 것들을
조합해 부수효과만 남기도록 유지한다 — 순수 계산은 테스트하기 쉽게 분리해둔다.
"""

from typing import Any

from app.core import fixtures
from app.db import store

# ── 조회 ──────────────────────────────────────────────────────────────

OPEN_STATUSES = ("issued", "disputed", "scheduled")
CLOSED_STATUSES = ("paid", "settled", "refused")


def actor_name(store_id: str | None = None) -> str:
    """실행 로그에 남길 주체 이름. 본사는 store_id 없이 호출한다."""
    return f"{store_id}-agent" if store_id else "hq-agent"


def get_invoice(invoice_id: str, *, store_id: str | None = None) -> dict | None:
    """청구서를 가져온다. store_id를 주면 그 지점 소유인지까지 확인한다."""
    invoice = store.get("invoices", invoice_id)
    if not invoice:
        return None
    if store_id and invoice["store_id"] != store_id:
        return None
    return invoice


def open_invoices(store_id: str | None = None) -> list[dict]:
    """미결 청구서 목록. store_id를 주면 해당 지점 것만."""
    docs = store.list_docs("invoices", store_id=store_id) if store_id else store.list_docs("invoices")
    return [d for d in docs if d["status"] not in CLOSED_STATUSES]


def store_profile(store_id: str) -> dict | None:
    return fixtures.load()["stores"].get(store_id)


def get_delivery(delivery_id: str) -> dict | None:
    """납품 건 — 시드(fixtures)와 동적 생성분(db `deliveries`)을 한 얼굴로."""
    seeded = fixtures.load()["deliveries"].get(delivery_id)
    if seeded:
        return {**seeded, "id": delivery_id}
    return store.get("deliveries", delivery_id)


def receiving_log(store_id: str, delivery_id: str) -> dict[str, int]:
    """지점의 실제 입고 기록 {sku: qty}.

    시드 납품은 fixtures의 검수 기록을, 경제 루프가 만든 동적 납품은
    납품 문서에 실린 `received`를 본다 (루프 납품은 검수 일치가 기본).
    """
    seeded = fixtures.load()["receiving_logs"].get(store_id, {}).get(delivery_id)
    if seeded is not None:
        return seeded
    doc = store.get("deliveries", delivery_id)
    if doc and doc.get("store_id") == store_id:
        return doc.get("received", {item["sku"]: item["qty"] for item in doc["items"]})
    return {}


def pos_forecast(store_id: str) -> dict:
    return fixtures.load()["pos_forecast"].get(store_id, {})


def store_orders(store_id: str) -> list[str]:
    """지점이 발주한 SKU 목록 — 이상 청구 판별의 기준."""
    return fixtures.load().get("orders", {}).get(store_id, [])


def get_trade(trade_id: str) -> dict | None:
    return store.get("p2p_trades", trade_id)


def record_move(store_id: str, sku: str, name: str, qty: int, reason: str, ref: str) -> dict:
    """재고 이동을 원장에 기록한다 — 입고(received)·판매(sold)·직거래(p2p_in/p2p_out).

    현재고는 항상 '시드 + 이동의 합'으로 계산되므로, 재고를 바꾸는 모든 사건은
    반드시 여기를 지나야 한다. ERP의 재고 원장에 해당한다.
    """
    seq = len(store.list_docs("inventory_moves")) + 1
    while store.get("inventory_moves", f"MOV-{seq:03d}"):
        seq += 1
    return store.put(
        "inventory_moves",
        f"MOV-{seq:03d}",
        {"store_id": store_id, "sku": sku, "name": name, "qty": qty,
         "reason": reason, "ref": ref},
    )


def effective_inventory(store_id: str) -> dict[str, dict]:
    """현재 재고 = 시드 재고(fixtures) + 재고 원장(inventory_moves)의 합.

    입고·판매·직거래가 전부 이동으로 기록되고, 데모 초기화(db.reset)가 이동을
    지우면 재고도 시드값으로 돌아온다 — 반복 리허설에 안전하다.
    """
    inventory = {
        sku: dict(entry)
        for sku, entry in fixtures.load().get("inventory", {}).get(store_id, {}).items()
    }
    for move in store.list_docs("inventory_moves", store_id=store_id):
        entry = inventory.setdefault(
            move["sku"], {"name": move.get("name", move["sku"]), "qty": 0, "safety": 0}
        )
        entry["qty"] += move["qty"]
    return inventory


def stock_shortages(inventory: dict[str, dict]) -> list[dict]:
    """안전재고 아래로 내려간 품목과 복구에 필요한 수량."""
    return [
        {"sku": sku, "name": e.get("name", sku), "qty": e["qty"], "safety": e["safety"],
         "need": e["safety"] - e["qty"]}
        for sku, e in inventory.items()
        if e["qty"] < e["safety"]
    ]


def sellable_surplus(inventory: dict[str, dict], sku: str, safety_multiplier: float = 1.0) -> int:
    """안전재고(×점주가 정한 배수)를 지키고 팔 수 있는 수량."""
    entry = inventory.get(sku)
    if not entry:
        return 0
    return max(0, int(entry["qty"] - entry["safety"] * safety_multiplier))


def hq_reorder_terms(sku: str) -> dict:
    """본사 발주 조건 — 직거래와 비교할 기준."""
    return fixtures.load().get("hq_reorder", {}).get(sku, {})


# ── 계산 (순수 함수) ──────────────────────────────────────────────────

def line_total(items: list[dict]) -> float:
    """품목 목록의 청구 합계."""
    return round(sum(i["qty"] * i["unit_price_usdc"] for i in items), 2)


def find_discrepancies(items: list[dict], received: dict[str, int]) -> list[dict]:
    """청구 품목과 실입고를 대조해 불일치 목록을 만든다."""
    return [
        {
            "sku": item["sku"],
            "name": item["name"],
            "invoiced_qty": item["qty"],
            "received_qty": received.get(item["sku"], 0),
            "over_billed_usdc": round(
                (item["qty"] - received.get(item["sku"], 0)) * item["unit_price_usdc"], 2
            ),
        }
        for item in items
        if received.get(item["sku"], 0) != item["qty"]
    ]


def correct_items(items: list[dict], received: dict[str, int]) -> list[dict]:
    """청구 품목 수량을 실입고분으로 정정한다.

    금액만 고치면 가맹점이 재검수할 때 같은 불일치를 또 발견한다.
    차감 합의란 곧 "청구서를 실입고분으로 바로잡는 것"이다.
    """
    return [{**item, "qty": received.get(item["sku"], item["qty"])} for item in items]


def total_over_billed(discrepancies: list[dict]) -> float:
    return round(sum(d["over_billed_usdc"] for d in discrepancies), 2)


def unordered_items(ordered_skus: list[str], items: list[dict]) -> list[dict]:
    """발주 내역에 없는 청구 품목 — 수량 불일치(협상감)와 달리 거부·에스컬레이션 대상이다."""
    allowed = set(ordered_skus)
    return [item for item in items if item["sku"] not in allowed]


def describe_discrepancies(discrepancies: list[dict]) -> str:
    """협상 제안문에 넣을 사람이 읽는 요약."""
    return ", ".join(
        f"{d['name']} {d['invoiced_qty']}→{d['received_qty']}" for d in discrepancies
    )


def amounts_match(actual: float, expected: float) -> bool:
    """USDC는 소수점 6자리 — 부동소수 오차를 흡수해 비교한다."""
    return abs(actual - expected) < 1e-6


def pick_term(accepts: list[dict], term: str) -> dict | None:
    """402 응답의 accepts[]에서 원하는 결제 조건(immediate/deferred/installment)을 고른다."""
    for option in accepts or []:
        if option.get("extra", {}).get("term") == term:
            return option
    return None


# ── 기록 ──────────────────────────────────────────────────────────────

def log(actor: str, action: str, payload: dict[str, Any]) -> None:
    """실행 증빙 로그 — 심사 기준 4번의 근거."""
    store.log_event(actor, action, payload)


def error(message: str) -> dict:
    """도구가 실패를 알릴 때 쓰는 공통 형태. 모델이 이 키를 보고 판단한다."""
    return {"error": message}
