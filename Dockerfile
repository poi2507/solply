# 백엔드 + 대시보드 — 심사자가 여는 라이브 URL.
# 빌드 컨텍스트는 레포 루트다: 대시보드(frontend/)가 이 앱의 /assets로 서빙되기 때문.
#   gcloud run deploy ... --source .  (루트에서)  또는
#   docker build -f backend/Dockerfile .
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app/backend

# 의존성 레이어 (lock 그대로 — 로컬과 동일한 버전)
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# 앱 코드 + 대시보드 (config.FRONTEND_DIR 기본값이 backend/../frontend)
COPY backend/app ./app
COPY backend/data ./data
COPY backend/demo.py ./demo.py
COPY frontend /app/frontend

ENV PATH="/app/backend/.venv/bin:$PATH"

# PORT는 Cloud Run이 주입한다
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
