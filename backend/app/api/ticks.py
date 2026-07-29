"""경제 루프 틱 API — Cloud Scheduler(운영) 또는 make tick(로컬)이 부른다.

한 번의 POST가 판매→카드정산→조달(발주·P2P)→재입고→예약실행을 한 바퀴 돌린다.
촬영·리허설 중에는 TICK_ENABLED=0으로 꺼서 화면 상태를 고정한다.
"""

from fastapi import APIRouter, HTTPException

from app import config
from app.core import economy

router = APIRouter(prefix="/api/ticks", tags=["ticks"])


@router.post("/run")
async def run_tick() -> dict:
    if not config.TICK_ENABLED:
        raise HTTPException(409, "경제 루프가 꺼져 있습니다 (TICK_ENABLED=0)")
    summary = await economy.tick()
    return {"ok": True, **summary}
