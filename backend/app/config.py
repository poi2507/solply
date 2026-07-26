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

# ── LLM ──
# LLM_PROVIDER=mock 이면 Gemini를 호출하지 않고 규칙 기반으로 동작한다.
# 무료 티어 rate limit 없이 데모 리허설을 반복할 때 쓴다.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
HQ_MODEL = os.getenv("HQ_MODEL", "gemini-3.6-flash")
STORE_MODEL = os.getenv("STORE_MODEL", "gemini-3.5-flash-lite")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ── 에이전트 정책 ──
STORE_ID = os.getenv("STORE_ID", "store-a")
SPEND_LIMIT_USDC = float(os.getenv("AGENT_SPEND_LIMIT_USDC", "50"))

# ── 저장소 ──
# local | postgres  (Cloud SQL로 옮길 때도 DATABASE_URL만 바꾼다)
STORE_BACKEND = os.getenv("SOLPLY_STORE", "local")
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"postgresql://{os.getenv('USER', 'postgres')}@localhost:5432/solply"
)

WALLETS = ("hq", "store-a", "store-b", "store-c")
