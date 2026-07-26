# CLAUDE.md

**Solply** — 프랜차이즈 본사-가맹점 식자재 대금(물대) 정산 에이전트.
GCP × Solana AI Agentic 해커톤 출품작. **제출 마감 8/3 23:59**, 데모데이 8/21.
배경·심사기준은 README.md, 설계는 docs/product-design.md, 킥오프 정리는 docs/kickoff-notes.md.

## 구조
- `backend/app/` — FastAPI. `api/`(라우터) `agents/`(hq·store·runner) `core/`(protocol·fixtures) `db/`(store 추상화) `llm/`(mock) `chain/`(결제 클라이언트)
- `frontend/` — 빌드 없는 정적 대시보드. FastAPI가 `/assets`로 서빙한다.
- `payments/` — TypeScript. Solana SDK가 JS 생태계라 분리했다.
- 실행은 전부 `make` 경유 (`make help`).

## 원칙
- **환경변수는 `app/config.py`에서만 읽는다.** 다른 모듈에서 `os.getenv` 직접 호출 금지.
- **저장소 접근은 `app.db.store` 파사드로만.** 파이널 진출 후 Firestore로 갈아끼울 자리다.
- 결제는 로컬넷/데브넷 전용. 메인넷 금지.
- 키·API 키는 커밋하지 않는다 (`backend/.env`, `~/.config/solana/solply/`).
- 자율 결제는 `AGENT_SPEND_LIMIT_USDC` 한도 내에서만 — 이 제약 로직 자체가 심사 포인트다.
- 결제 성공 시 signature와 explorer 링크를 반드시 로그로 남긴다 (심사 기준 4: 실행 증빙).
- 데모 시나리오는 코드가 아니라 `backend/data/fixtures.json`과 지갑 잔액으로 만들어진다.
  B지점 검수 불일치, C지점 잔액 부족을 건드리면 데모가 죽는다 (tests/test_core.py가 지킨다).

## 작업 흐름
- 기능 검증은 `make demo-mock` (LLM 없이 몇 초, 온체인 결제는 실제 발생).
- Gemini 무료 티어는 모델당 분당 5회 — `make demo`는 재시도 때문에 10분 이상 걸린다.
