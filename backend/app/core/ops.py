"""운영 조치 — 사람이 한 번 내리는 장부 정리. 전부 이벤트로 남고 공개 증빙에 그대로 보인다.

9/23 시뮬 수요를 끈 뒤 지점 B·C는 매출(카드정산)이 끊겼고, 8월 시뮬이 남긴 미결 청구서에
발주가 막혔다 (10/9: B 잔액 2.58 / 미결 71.2, C 6.74 / 49.0, 탄산 0). 두 조치로 푼다:

  archive_sim_era — 대회 시작 전에 생긴 미결 청구서를 'archived'로 옮긴다. 지우지 않는다.
  fund_store      — 본사가 지점에 운영자금을 보낸다. 매출이 아니라 자금 이동으로 따로 센다.
"""

from datetime import UTC, datetime

from app import config
from app.agents import utils
from app.core import fixtures
from app.core import status as status_mod
from app.db import store as db
from app.solana import payments

CAPITAL_MEMO = "WORKING-CAPITAL"
MAX_CAPITAL_USDC = 50.0  # 한 번에 옮길 수 있는 상한 — 손가락 실수가 본사를 비우지 않게


def _born(inv: dict) -> str:
    return inv.get("created_at") or inv.get("updated_at") or ""


def archive_sim_era(*, dry_run: bool = True) -> dict:
    """대회 시작일(config.TRACTION_SINCE) 전에 생겨 아직 미결인 청구서를 보관 상태로."""
    targets = [inv for inv in db.list_docs("invoices")
               if inv.get("status") in status_mod.ACTIONABLE and _born(inv) < config.TRACTION_SINCE]
    by_store: dict[str, dict] = {}
    for inv in targets:
        b = by_store.setdefault(inv.get("store_id", "?"), {"count": 0, "usdc": 0.0})
        b["count"] += 1
        b["usdc"] = round(b["usdc"] + float(inv.get("amount_usdc") or 0), 2)
    if not dry_run:
        now = datetime.now(UTC).isoformat()
        for inv in targets:
            db.update("invoices", inv["id"], {
                "status": status_mod.InvoiceStatus.ARCHIVED, "archived_from": inv["status"],
                "archived_at": now, "archived_reason": "simulation era (before the hackathon)"})
        utils.log("human", "ops.archive_sim_era", {"before": config.TRACTION_SINCE,
                                                   "count": len(targets), "by_store": by_store})
    return {"dry_run": dry_run, "before": config.TRACTION_SINCE, "count": len(targets),
            "by_store": by_store}


def fund_store(store_id: str, amount: float, reason: str) -> dict:
    """본사 → 지점 운영자금. 온체인 이체이고, 매출·실사용 지표에는 넣지 않는다."""
    if store_id not in fixtures.load()["stores"]:
        raise ValueError(f"unknown store: {store_id}")
    if not 0 < amount <= MAX_CAPITAL_USDC:
        raise ValueError(f"amount must be within 0..{MAX_CAPITAL_USDC:g} USDC")
    address = payments.balance(store_id)["address"]
    receipt = payments.pay("hq", address, amount, CAPITAL_MEMO)
    payload = {"store_id": store_id, "amount_usdc": amount, "reason": reason,
               "tx": receipt.get("signature", "")}
    utils.log("human", "ops.working_capital", payload)
    return payload


def capital_moves() -> list[dict]:
    """대회 기간에 옮긴 운영자금 — 공개 증빙이 '매출 아님'으로 따로 보여준다."""
    return [{"ts": e["ts"], **(e.get("payload") or {})}
            for e in db.recent_events(200, action="ops.working_capital")
            if (e.get("ts") or "") >= config.TRACTION_SINCE]
