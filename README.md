# Solply — Settle On Ledger, for supply

> **프랜차이즈 본사–가맹점 식자재 대금(물대) 정산 에이전트.**
> 납품 이벤트 하나로 AI 에이전트들이 청구 → 검수 검증 → 협상 → 결제 → 정산을 사람 개입 없이 Solana 온체인에서 완결합니다.
> Google Cloud AI(Gemini + ADK)가 두뇌, Solana(USDC)가 결제 레이어.

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
├── agent/       # Python — Google ADK(Agent Development Kit) + Gemini 에이전트
├── payments/    # TypeScript — Solana 결제 서비스 (Solana Pay, USDC, devnet)
├── infra/       # GCP 배포 (Cloud Run Dockerfile, gcloud 스크립트)
├── scripts/     # 개발용 유틸 스크립트
└── docs/        # 기획/리서치 문서
```

## 개발환경 시작하기

```bash
# 1. 에이전트 (Python)
cd agent
uv sync                          # 의존성 설치 (google-adk 포함)
cp ../.env.example .env          # GEMINI_API_KEY 등 채우기
uv run adk web                   # ADK 개발 UI 실행

# 2. 결제 서비스 (TypeScript)
cd payments
npm install
npm run dev

# 3. Solana devnet 지갑
solana-keygen new --outfile ~/.config/solana/hackathon.json
solana config set --url devnet --keypair ~/.config/solana/hackathon.json
solana airdrop 2                 # devnet SOL 받기
```

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
