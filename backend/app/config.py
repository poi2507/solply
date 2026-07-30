"""환경 설정 한 곳. 다른 모듈은 os.getenv를 직접 읽지 않는다."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
load_dotenv(BASE_DIR / ".env")

# ── 경로 ──
DATA_DIR = Path(os.getenv("SOLPLY_DATA_DIR", BASE_DIR / "data"))
STATE_PATH = Path(os.getenv("SOLPLY_STATE_PATH", DATA_DIR / "state.json"))
FIXTURES_PATH = DATA_DIR / "fixtures.json"
FRONTEND_DIR = Path(os.getenv("SOLPLY_FRONTEND_DIR", BASE_DIR.parent / "frontend"))

# ── 체인 ──
NETWORK = os.getenv("SOLANA_NETWORK", "localnet")
PAYMENTS_API_URL = os.getenv("PAYMENTS_API_URL", "http://localhost:3000")
# 본사 x402 엔드포인트 (가맹점 에이전트가 정산 왕복에 사용) — 우리 API 서버 자신이다
SOLPLY_API_URL = os.getenv("SOLPLY_API_URL", "http://localhost:8080")

# ── LLM ──
# gemini(AI Studio 무료) | vertex(GCP 크레딧·한도 여유) | mock(LLM 없이 규칙)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
HQ_MODEL = os.getenv("HQ_MODEL", "gemini-3.6-flash")
STORE_MODEL = os.getenv("STORE_MODEL", "gemini-3.5-flash-lite")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
# Vertex AI 경유 시 필요 (GCP 크레딧 적용 + 한도 여유). LLM_PROVIDER=vertex 로 전환
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
# Vertex는 모델 이름 체계가 AI Studio와 다를 수 있어 따로 둔다
VERTEX_HQ_MODEL = os.getenv("VERTEX_HQ_MODEL", "gemini-2.5-flash")
VERTEX_STORE_MODEL = os.getenv("VERTEX_STORE_MODEL", "gemini-2.5-flash-lite")

# ── 에이전트 정책 ──
STORE_ID = os.getenv("STORE_ID", "store-a")
SPEND_LIMIT_USDC = float(os.getenv("AGENT_SPEND_LIMIT_USDC", "50"))

# ── 경제 루프 ──
# 라이브에서 스케줄러가 굴리는 틱. 촬영·리허설 중에는 0으로 꺼서 상태를 고정한다
TICK_ENABLED = os.getenv("TICK_ENABLED", "1").lower() not in ("0", "false")

# ── pay.sh (판단 재료 구매) ──
# 조달 판단 전에 에이전트가 시세 데이터를 x402로 사서 쓴다. 샌드박스라 실자금은 없다.
# CLI가 없거나 호출이 실패하면 조용히 건너뛴다 — 시세가 조달을 멈출 사유는 아니다.
PAYSH_ENABLED = os.getenv("PAYSH_ENABLED", "1").lower() not in ("0", "false")
PAYSH_BIN = os.getenv("PAYSH_BIN", "pay")
PAYSH_QUOTE_URL = os.getenv("PAYSH_QUOTE_URL", "https://debugger.pay.sh/mpp/quote")
PAYSH_QUOTE_TTL_S = int(os.getenv("PAYSH_QUOTE_TTL_S", "600"))

# ── 저장소 ──
# local | postgres  (Cloud SQL로 옮길 때도 DATABASE_URL만 바꾼다)
STORE_BACKEND = os.getenv("SOLPLY_STORE", "local")
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"postgresql://{os.getenv('USER', 'postgres')}@localhost:5432/solply"
)

WALLETS = ("hq", "store-a", "store-b", "store-c")
