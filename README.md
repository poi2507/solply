# Solply — Settle On Ledger, for supply

> **프랜차이즈 본사–가맹점 식자재 대금(물대) 정산 에이전트.**
> 납품 이벤트 하나로 AI 에이전트들이 청구 → 검수 검증 → 협상 → 결제 → 정산을 사람 개입 없이 Solana 온체인에서 완결합니다.
> Google Cloud AI(Gemini + ADK)가 두뇌, Solana(USDC)가 결제 레이어.

- 🚀 **[인수인계 — 이어서 작업할 때 먼저 읽기](docs/HANDOFF.md)** · 📋 [WBS (D-7 작업계획)](docs/wbs.md)
- 📐 [프로덕트 설계](docs/product-design.md) · 🧭 [의사결정 로그](docs/decision-log.md) · 🏗️ [아키텍처 시각화](docs/architecture.html) · ✅ [제출 체크리스트](docs/checklist.md)

---

## 참가 공모전: GCP × Solana AI Agentic 해커톤 2026

> AI 에이전트가 사람 승인 없이, 정해진 한도 내에서 스스로 결제를 처리하는 프로덕트를 만드는 해커톤.
> 공식 사이트: https://www.gcp-solana-ai-agentic-hacks-kr.xyz
> 문의: gcp-solana-ai-agentic-hacks-kr@superteamkr.com

## 핵심 일정

| 날짜 | 내용 |
|---|---|
| 7/21 (화) 19:00–21:00 | Kick-off & Tech Session (완료, 녹화 공개 예정) |
| ~8월 중순 | 집중 빌드 기간 — MVP/PoC, 데모 자료, **온체인 실행 증빙** 제출 |
| 제출 후 | 1차 심사 → 파이널리스트 약 10팀 발표, 멘토링 |
| **8/21 (금)** | **Demo Day @ Google Startup Campus** (오프라인 최종 발표·심사·시상) |

## 트랙 (단일 트랙: Solana 기반 Agentic Commerce)

- **A. Agent-Initiated Commerce** — 에이전트가 결제 요청 생성·입금·정산까지 직접 처리
- **B. Autonomous On-chain Settlement** — 정책·예산 한도 내 에이전트가 직접 지갑 서명·결제
- **C. Multi-Agent Commerce** — 에이전트 간 A2A/A2B 협상·주문·결제
- **D. Verifiable Distribution at Scale** — 자격 판정 → 온체인 증명 → 대규모 지급·정산

## 심사 기준

1. **사용자 경험 / 문제 해결** — 직관적이고 새로운 UX, 기존 문제 해결 방식
2. **AI 활용도** — Gemini / Google Cloud AI 스택(에이전트 프레임워크 포함) 구성의 짜임새
3. **기술 완성도 및 블록체인·인프라 연동** — Solana 결제(USDC, Solana Pay, pay.sh), 차세대 결제 프로토콜(AP2, A2A, x402) 연동 구조
4. **실제 구동 여부** — 시연 중 AI 에이전트가 **실제 트랜잭션을 발생시키고 결제를 완료**하는지 (로컬넷/테스트넷/데브넷 라이브, 실행 로그 기반 확인)

## 제출물

- 프로덕트 소개서 (필수)
- GitHub Repo (필수)
- 데모 영상 (필수)
- 라이브 배포 엔드포인트 (권장)

## 상금

총 $5,000 — 1st $3,000 / 2nd $1,500 / 3rd $500 (Solana Foundation Grants Program 지급, 절반은 솔라나 글로벌 해커톤 참여 시 지급)

## 권장 아키텍처 (주최측 가이드)

- **Cloud Run 강력 권장** (GKE는 5주 일정 대비 과함)
- 비동기 이벤트 파이프라인: **Pub/Sub + Eventarc + Workflows**
- 예시 플로우: 결제 완료 이벤트 수신 → Eventarc로 Workflows 트리거 → 결제 확인 → Firestore 상태 갱신 → 영수증 발행·BigQuery 저장 → 에이전트 응답 전송
- Secret Manager로 키 관리 (IAM 설정)
- GCP 무료 $300 크레딧 활용 가능

## 프로젝트 구조

```
.
├── Makefile              # 모든 실행 명령 (make help)
├── backend/              # Python — FastAPI + Gemini/ADK 에이전트
│   ├── app/
│   │   ├── main.py       #   앱 조립
│   │   ├── config.py     #   환경설정 한 곳
│   │   ├── api/          #   dashboard(+SSE) · x402 라우터
│   │   ├── agents/       #   hq/ · store/ (각각 agent.py + prompt.py)
│   │   │                 #   utils.py(공통 계산) · runner.py · prompt_kit.py
│   │   ├── core/         #   protocol(x402) · fixtures
│   │   ├── db/           #   store 인터페이스 → local(JSON) / postgres
│   │   ├── llm/          #   mock 플래너 (리허설용)
│   │   └── solana/       #   결제 서비스 클라이언트
│   ├── data/             #   fixtures.json (데모 시나리오가 여기 심어짐)
│   ├── tests/
│   └── demo.py           #   데모 3종 오케스트레이터
├── frontend/             # 정산 대시보드 (빌드 없는 정적 HTML/CSS/JS)
├── payments/             # TypeScript — Solana USDC 전송·검증 (Express)
├── infra/                # Cloud Run 배포
├── scripts/              # 로컬넷 셋업, 지갑, dev 스택
└── docs/                 # 설계·의사결정·킥오프 정리
```

## 개발환경 시작하기

```bash
make setup     # 의존성 설치 (backend uv + payments npm)
make db        # PostgreSQL 초기화·기동 (:5432)
make dev       # 전체 스택 기동 → http://localhost:8080

# 데모 실행 (다른 터미널에서)
make demo-mock # 규칙 기반 — 빠름, 리허설용 (온체인 결제는 실제로 발생)
make demo      # Gemini 판단 — 심사용

make test      # 백엔드 테스트
make help      # 전체 명령 목록
```

> **개발은 로컬넷, 시연은 데브넷.** 주최측 권장 흐름을 따릅니다.
> 네트워크 전환은 `payments/.env`의 RPC 주소·USDC 민트 세 줄만 바꾸면 됩니다.

### 필요한 환경 변수

`backend/.env`
- `GOOGLE_API_KEY` — [AI Studio](https://aistudio.google.com/apikey) 무료 티어
- `LLM_PROVIDER=mock` — LLM 없이 규칙 기반 리허설 (온체인 결제는 실제로 발생)
- `SOLPLY_STORE=postgres` + `DATABASE_URL` — 저장소. `local`이면 JSON 파일

`payments/.env` — RPC 주소, USDC 민트, 지갑 디렉터리.
템플릿은 [.env.example](.env.example) 참고.

### 저장소 전환

`app/db/store.py`가 인터페이스, 구현은 `local_store.py`(JSON) / `postgres_store.py`(JSONB).
호출부는 파사드만 쓰므로 백엔드를 바꿔도 다른 코드는 손대지 않는다.
Cloud SQL로 옮길 때도 `DATABASE_URL`만 교체하면 된다.

## 핵심 레퍼런스

### Google Cloud / AI
- [Agent Development Kit (ADK)](https://google.github.io/adk-docs/) — 에이전트 프레임워크 (심사기준 2번 핵심)
- [Agent Starter Pack](https://github.com/GoogleCloudPlatform/agent-starter-pack)
- [Vertex AI Docs](https://cloud.google.com/vertex-ai/docs) · [Firestore](https://cloud.google.com/firestore/docs) · [BigQuery](https://cloud.google.com/bigquery/docs)

### Solana / 결제
- [Solana Pay Docs](https://docs.solanapay.com/)
- [Solana Developer Docs](https://solana.com/docs)
- [Mobile Wallet Adapter](https://docs.solanamobile.com/get-started/mobile-wallet-adapter)

### 에이전트 결제 프로토콜
- [AP2 (Agent Payments Protocol)](https://ap2-protocol.org/)
- [A2A x402 Extension](https://github.com/google-agentic-commerce/a2a-x402)
- [ACP Spec](https://github.com/agentic-commerce-protocol/agentic-commerce-protocol)
- [UCP Samples (A2A + Gemini)](https://github.com/Universal-Commerce-Protocol/samples)
- [프로토콜 비교 (x402/ACP/AP2/UCP)](https://atxp.ai/blog/agent-payment-protocols-compared)
