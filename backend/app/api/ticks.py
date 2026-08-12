"""경제 루프 틱 API — Cloud Scheduler(운영) 또는 make tick(로컬)이 부른다.

한 번의 POST가 판매→카드정산→조달(발주·P2P)→재입고→예약실행을 한 바퀴 돌린다.
촬영·리허설 중에는 TICK_ENABLED=0으로 꺼서 화면 상태를 고정한다.

**동시 실행 잠금**: 수동 틱(무대 트리거·검증)이 정시 스케줄러 틱과 겹치면
두 틱이 같은 거래를 몰아 경합 오류를 만든다 (8/11·8/13 실측 — p2p.pay 500).
잠금 문서로 한 번에 하나만 돌리고, 죽은 틱의 잠금은 TTL이 자연 해제한다.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app import config
from app.core import economy
from app.db import store

router = APIRouter(prefix="/api/ticks", tags=["ticks"])

LOCK_TTL_S = 540  # 스케줄러 attempt deadline과 동일 — 이보다 오래 걸린 틱은 죽은 것


@router.post("/run")
async def run_tick() -> dict:
    if not config.TICK_ENABLED:
        raise HTTPException(409, "경제 루프가 꺼져 있습니다 (TICK_ENABLED=0)")

    lock = store.get("locks", "tick")
    if lock and lock.get("started_at"):
        age = (datetime.now(UTC) - datetime.fromisoformat(lock["started_at"])).total_seconds()
        if age < LOCK_TTL_S:
            raise HTTPException(
                409, f"틱이 이미 실행 중입니다 ({int(age)}초째) — 동시 실행은 거래 경합을 만듭니다"
            )
    store.put("locks", "tick", {"started_at": datetime.now(UTC).isoformat()})
    try:
        summary = await economy.tick()
    finally:
        store.put("locks", "tick", {"started_at": None})
    return {"ok": True, **summary}
