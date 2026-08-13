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
# P2P 직거래 예치금 금고 — 잔액이 곧 "지금 예치 중인 대금"인 온체인 감사 장부
ESCROW_WALLET = os.getenv("ESCROW_WALLET", "escrow")
# 본사 x402 엔드포인트 (가맹점 에이전트가 정산 왕복에 사용) — 우리 API 서버 자신이다
SOLPLY_API_URL = os.getenv("SOLPLY_API_URL", "http://localhost:8080")

# ── A2A (에이전트 간 표준 왕복) ──
# 경량판: 두 에이전트가 같은 배포에 살아 자기 자신을 HTTP로 부른다.
# 완전판 승격은 이 URL 교체가 전부다 — 메시지 규약·번역기·클라이언트는 그대로.
# 패스키(WebAuthn)의 도메인 신원 — 자물쇠(공개키)가 이 도메인에 묶인다
from urllib.parse import urlparse as _urlparse

PASSKEY_RP_ID = os.getenv("PASSKEY_RP_ID", _urlparse(SOLPLY_API_URL).hostname or "localhost")

A2A_HQ_URL = os.getenv("A2A_HQ_URL", SOLPLY_API_URL)
A2A_STORE_URL = os.getenv("A2A_STORE_URL", SOLPLY_API_URL)

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
# 시세 출처 — self: 우리 데이터 상점의 체결가 지수를 x402로 구매 (자급 순환, devnet 실결제)
#            paysh: 주최측 데모 디버거 (샌드박스 — 값이 무의미한 폴백)
QUOTE_SOURCE = os.getenv("QUOTE_SOURCE", "self")

# ── 저장소 ──
# local | postgres  (Cloud SQL로 옮길 때도 DATABASE_URL만 바꾼다)
STORE_BACKEND = os.getenv("SOLPLY_STORE", "local")
DATABASE_URL = os.getenv(
    "DATABASE_URL", f"postgresql://{os.getenv('USER', 'postgres')}@localhost:5432/solply"
)

WALLETS = ("hq", "store-a", "store-b", "store-c")
