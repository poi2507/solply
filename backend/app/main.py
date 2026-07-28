"""Solply 백엔드 앱 조립.

한 프로세스가 대시보드 API·x402 엔드포인트·프론트엔드를 모두 서빙한다
(Cloud Run 컨테이너 하나로 배포하기 위해).

실행: uv run uvicorn app.main:app --reload --port 8080
"""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api import dashboard, policy, schedules, x402

app = FastAPI(
    title="Solply",
    description="프랜차이즈 식자재 대금 자율 정산 — Settle On Ledger, for supply",
    version="0.1.0",
)

app.include_router(dashboard.router)
app.include_router(policy.router)
app.include_router(schedules.router)
app.include_router(x402.router)

if config.FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(config.FRONTEND_DIR / "index.html")
