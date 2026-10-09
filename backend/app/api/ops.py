"""운영 조치 API — 운영 토큰 전용(없으면 닫힘). 조치마다 이벤트가 남고 /proof에 '매출 아님'으로 보인다."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api import guard
from app.core import ops

router = APIRouter(prefix="/api/ops", tags=["ops"], dependencies=[Depends(guard.require_ops)])


@router.post("/archive-sim-era")
def archive_sim_era(dry_run: bool = True) -> dict:
    """대회 시작 전 미결 청구서를 보관 상태로. 기본은 미리보기(dry_run)."""
    return ops.archive_sim_era(dry_run=dry_run)


class Capital(BaseModel):
    store_id: str
    amount: float = Field(gt=0)
    reason: str = Field(min_length=3, max_length=200)


@router.post("/working-capital")
def working_capital(body: Capital) -> dict:
    try:
        return ops.fund_store(body.store_id, body.amount, body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
