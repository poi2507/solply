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


def receiving_log(store_id: str, delivery_id: str) -> dict[str, int]:
    """지점의 실제 입고 기록 {sku: qty}."""
    return fixtures.load()["receiving_logs"].get(store_id, {}).get(delivery_id, {})


def pos_forecast(store_id: str) -> dict:
    return fixtures.load()["pos_forecast"].get(store_id, {})


def store_orders(store_id: str) -> list[str]:
    """지점이 발주한 SKU 목록 — 이상 청구 판별의 기준."""
    return fixtures.load().get("orders", {}).get(store_id, [])


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
