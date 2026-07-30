# 킥오프 & 테크 세션 정리 (2026-07-21)

> 영상: https://www.youtube.com/watch?v=-DLXn0DtzHg · 발표자료: https://blog.superteamkr.com/p/gcp-solana-session
> 발표자료 PDF 4종 원문을 분석해 정리. **Solply 설계에 반영할 항목은 ⭐ 표시.**

## 0. 가장 중요한 것 — 일정과 하드 요건

- ⭐ **최종 제출 마감: 8/3 (일) 23:59 KST** — 사이트에는 없던 정보. 파이널리스트 발표 8/7, 멘토링 8/10~20, 데모데이 8/21.
- ⭐ **"목업(Mock-up)은 심사 대상에서 제외 — 데모데이 당일 결제가 실제로 동작해야 합니다"** (인트로 덱 p5 경고 배너)
- 제출물: ① 프로덕트 소개서 PPT (**타깃·문제·수익모델·아키텍처** 4요소) ② GitHub (재현 가능한 코드 + README) ③ **데모 영상 3분 이내** (실제 온체인 결제 전 과정) + **보너스: 라이브 배포 URL**
- 심사 4대 기준: 혁신성·UX / AI 활용도(Gemini·GC AI 스택) / 인프라 연동(USDC·Solana Pay·pay.sh) / 실제 구동(실행 로그·트랜잭션) — **배점 비공개, 동등 나열**
- 상금 $5,000 (1위 $3,000). Solana Foundation Grants로 지급, **절반은 글로벌 해커톤(콜로세움) 참여 시 지급**
- 문의: gcp-solana-ai-agentic-hacks-kr@superteamkr.com · Discord: discord.gg/bYrJCUAsj

### 크레딧 / 지원 (질문 많았던 부분)
- ⭐ **GCP $300 크레딧은 Gemini API에 사용 불가** — 별도 시스템. Gemini는 **AI Studio 무료 티어** 사용 (인트로 덱 p10 명시)
- ⭐ **개인 Gmail 계정 필수** — 학교·회사 Workspace 계정은 크레딧 정책상 제한
- ⭐ **devnet SOL은 Discord에서 추가 수령 가능** — "Devnet SOL이 더 필요하면 Discord에서 추가 수령 희망자에 한해 송부 예정" (솔라나 덱 p17). 공식 faucet 외 유일한 경로
- **pay.sh 개발자 직통**: Discord `#pay-sh-질문` 채널에서 Solana Foundation의 **Ludo**가 한/영 직접 답변
- 파이널리스트 진출 시: **금융권 5사 멘토링** (신한카드·DAZN·KG이니시스·KG파이낸셜·KSNET)

---

## 1. 솔라나 세션 — Why Solana for Agentic Commerce
발표: Chaerin Kim (APAC Tech, Solana Foundation) · chaerin.kim@solana.org

### ⭐ 개발 환경 권고 (p17) — 우리가 즉시 채택한 것
| 단계 | 네트워크 | 용도 |
|---|---|---|
| **START HERE** | **Localnet** | 무료·무제한, 즉시 리셋, 가장 빠른 반복 루프 |
| 건너뛰기 | Testnet | 앱 개발 타깃으로 부적합 |
| **시연 직전** | **Devnet** | 무료 에어드랍(제한), 실제와 유사 |
| 배포 시에만 | Mainnet | 되돌릴 수 없음 |

→ Solply는 `scripts/setup-localnet.sh`로 로컬넷 개발, devnet은 시연 직전 전환.

### 피칭에 쓸 공식 수치 (주최측 제공이라 인용 안전)
- Solana: 블록타임 **~400ms**, 건당 수수료 **~$0.00x**, 24/7 단일 글로벌 상태
- **SWIFT vs Solana**: 1~5영업일 → **1초 이내**, $15~50 → **$0.001 미만**, 대리은행 1~3곳 → **없음**
- 기관 실적: **Visa** USDC 정산 연환산 $3.5B+, **Western Union** USDPT 발행(2026.5), **PayPal** PYUSD 네이티브
- 네트워크: 월 스테이블코인 거래 200M+, 월 정산 규모 **$650B+**

### 심사위원이 보고 싶은 것 4가지 (p16)
1. 시연 중 **실제 트랜잭션 발생 + 정산 완료**
2. **정책·예산 한도 안에서** 사람 승인 없이 에이전트가 직접 서명·결제
3. Solana Pay · pay.sh · x402 · USDC를 실제 유스케이스에 녹여낸 구현
4. **"왜 이게 온체인이어야 하는가"에 스스로 답하는** 경험

### ⭐ pay.sh의 정체 (오해 주의)
Solana Foundation + Google Cloud가 만든 **에이전트용 API 결제 게이트웨이**. 우리가 "대금을 받는 레일"이 아니라, **에이전트가 유료 API를 쓰고 USDC로 지불하는 레일**이다 (70+ API: Google Cloud, QuickNode, Perplexity, Exa, fal.ai, Purch 등).
```bash
brew install pay && pay setup          # 설치
pay curl https://debugger.pay.sh/mpp/quote/AAPL   # 402 자동 처리
npx @solana/pay claude "buy some water with pay"
```
→ **Solply 활용안**: 에이전트가 협상에 필요한 데이터(식자재 시세, 공급사 검색)를 pay.sh로 직접 사서 쓰면 "심사 기준 3의 pay.sh 연동"을 자연스럽게 충족. `--sandbox` 모드로 실자금 없이 테스트 가능.

---

## 2. Four Pillars 세션 — The Agentic Commerce Stack: x402 & mpp
발표: 유준혁 (Researcher, Four Pillars)

### 프로토콜 지형도 (5개 레이어)
| 레이어 | 프로토콜 |
|---|---|
| 에이전트 상호운용 | **A2A** (Google) |
| 커머스·체크아웃 | ACP (OpenAI+Stripe), **UCP** (Google) |
| 신원·의도 증명 | **AP2** (Google), VI, Trusted Agent Protocol (Visa) |
| 결제·정산 레일 | **MPP** (Stripe), **x402** (Linux Foundation) |
| 검증·가드레일 | ARC (AWS) |

### ⭐ x402 메시지 흐름 (구현용)
```
① Client → Server: GET /api
② Server → Client: 402 Payment Required (accepts[] 로 복수 결제조건 제시)
③ Client: 결제 페이로드 서명
④ Client → Server: PAYMENT-SIGNATURE 헤더 첨부 재요청
⑤⑥ Server ↔ Facilitator: /verify
⑦ Server: do work (서비스 이행)
⑧⑨⑩⑪ Server → Facilitator → Chain: /settle → tx 확정
⑫ Server → Client: PAYMENT-RESPONSE
```
- v2 헤더: `PAYMENT-REQUIRED` / `PAYMENT-SIGNATURE` / `PAYMENT-RESPONSE` (v1의 `X-PAYMENT` 아님)
- `network`는 CAIP-2: Solana mainnet = `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp`
- `amount`는 atomic units 문자열 (USDC 6 decimals)
- scheme: `exact`(고정가) / `upto`(사용량) / `batch-settlement`(배치)
- 확장: **Signed Offers & Receipts** (청구서·영수증 증빙), **Payment-Identifier**(멱등성), Lifecycle Hooks
- 문서: https://docs.x402.org/introduction · **LLM용 전문: https://docs.x402.org/llms-full.txt**
- 익스플로러: x402scan.io / mppscan.io · 프로토콜 변경 추적: https://scout.nekuda.ai/

### ⭐ Solply 설계에 직접 영향을 주는 4가지

1. **`accepts[]` 배열을 협상 훅으로 사용** — 402 응답에 복수 결제조건(수량별 단가, 즉시납/유예)을 담으면 **표준 스펙 안에서 협상을 표현**할 수 있다. 우리 차감·유예 협상을 x402 위에 얹는 정석 방법.
2. **x402는 verify → 이행 → settle 순서** — 식자재는 배송·검수가 있으므로 그대로 쓰면 위험. **verify 후 에스크로 → 검수 완료 시 settle**로 뒤집는 설계가 필요하고, 이건 표준에 없으니 **우리 독자 기여로 어필 가능**.
3. **온체인 비용: x402는 요청 N건 = Tx N건, MPP 세션은 고정 2건** — 가맹점이 하루 수십 건 발주하면 선형 증가. 금융위도 "건별 결제 vs 주/월 단위 모아서 정산" 비용 차이를 지적. **주 단위 채널 후 마감 정산** 스토리가 설득력 있음.
4. **AP2의 mandate(위임장)로 권한 모델링** — "점주가 에이전트에게 준 품목·한도·기간 위임"을 mandate로 표현하면 비어 있는 "신원·의도 증명" 레일을 채우는 셈.

### 발표자의 핵심 메시지: **"당위성을 가져야 한다"**
- **왜 블록체인?** 수수료만으로는 약함 (금융위: "스테이블코인만 전제할 필요 없다", 초소액 아니면 카드가 쌀 수도). 강한 논거는 **로그인 없는 M2M 자동화 + 다자간 네팅 정산 + 24/7 즉시성**.
- **어느 시장?** 추천형·위임형이 아니라 **자율형(사람이 루프에 없는)** ← Solply가 정확히 여기.
- **비어 있는 레일**: 커머스·체크아웃 / 신원·의도 증명 / 검증·가드레일
- ⭐ **현재 x402 트래픽은 디지털 재화(데이터·API) 일색 — 실물 B2B 커머스는 사실상 공백**. Solply는 "실물 B2B 첫 사례"로 포지셔닝 가능. 단 "왜 아직 아무도 안 했나(실물 이행 리스크·분쟁)"에 답을 준비할 것.
- 리퍼럴 경제 붕괴가 x402의 존재 이유: ClaudeBot **crawl-to-refer 23,951:1**

### 참고 사례
- 콜로세움 Frontier 해커톤 수상작: AI Agent 카테고리 **3개뿐** (경쟁 얕음) — https://blog.colosseum.com/announcing-the-winners-of-the-solana-frontier-hackathon/ · 참고 프로젝트 **flovia402.com**
- **Cloudflare Monetization Gateway 패턴**: 게이트웨이가 402·검증 전담, origin은 "결제 검증된 요청"만 수신 → **결제 미들웨어를 비즈니스 로직에서 분리**하는 설계 권장

---

## 3. Google Cloud 세션 — Vibe Coding on Google Cloud
발표: Seonhwa Hwang (Solutions Architect, Google Cloud)

**주의**: 이 덱은 **Antigravity(에이전틱 IDE) 라이브 데모** 중심이라 ADK 코드·`gcloud run deploy` 명령어는 없다. ADK는 codelab 목록으로만 등장.

### 데모 워크플로우 (Next.js 이커머스 자율 빌드)
1. **Stitch**로 UI 디자인 → `DESIGN.md` 자동 생성
2. `.agents/AGENTS.md`에 페르소나·언어 규칙 고정
3. **`/grill-me`** — 코드 작성 전 에이전트가 역질문으로 아키텍처 조율 → `implementation_plan.md` 승인
4. **`/goal`** — 서브에이전트 병렬 가동 (프론트/API/pay.sh 연동 동시 진행)
5. **"CloudRun으로 배포해줘"** 한 줄로 컨테이너화+배포

### ⭐ 데모의 결제 아키텍처 (우리가 참고할 것)
- **백엔드 결제 루프백**: 백엔드가 게이트웨이(`/api/checkout`)가 되고, 에이전트가 **자식 프로세스로 `pay --sandbox curl`** 실행해 402 챌린지를 스스로 해결
- **온체인 정밀 검증**: `@solana/web3.js` + `@solana/pay` 바인딩으로 **수취인·금액·컨펌 유효성 3중 검증** ← Solply도 이미 구현 (`GET /tx/:sig`)
- **Function Calling 툴 분리**: `process_agentic_checkout`처럼 결제 의사만 인식하는 전용 툴 경계 설정
- 모델: 데모 전 구간 **Gemini 3.5 Flash** (3.1 Pro 대비 비용 1/3)
- UX 신뢰 장치: `Mining Block...` 로딩 모달, 지갑 주소 축약(`2QPS..EQ1E`), 기술 정보에 JetBrains Mono

### 볼 만한 codelab (전체 14개 중)
- **Vibecode로 ADK 에이전트용 프론트엔드 Cloud Run 배포** (46분) — **Pub/Sub로 고가치 요청을 가로채 사람 승인받는 파이프라인**. Solply의 한도 초과 에스컬레이션과 동일 패턴
- **ADK 2.0 기반 앰비언트 에이전트** (1:02) — 이벤트 기반 **그래프 워크플로우** (청구→협상→결제→정산에 직결)
- **MCP 서버로 Cloud Run 배포** (1:30) — 실제 배포 명령어는 여기
- 결제 취급 시: **TDD + STRIDE 위협 모델링으로 에이전트 보안 강화** (1:13)
- 허브: https://codelabs.developers.google.com/?product=antigravity

---

## 4. Solply 액션 아이템 (우선순위)

### 즉시 (8/3 제출 전)
- [x] 로컬넷 개발 환경 (주최측 권장 흐름) — `scripts/setup-localnet.sh`
- [x] 온체인 결제 + memo(invoice_id) + 3중 검증
- [ ] **x402 v2 메시지 포맷**으로 청구서 전송 (`accepts[]`에 즉시납/유예 조건 복수 제시 = 협상 훅)
- [ ] **수익모델** 정의 — 제출 PPT 필수 4요소인데 아직 없음
- [ ] "왜 온체인인가" 논거를 **M2M 자동화 + 다자간 네팅 + 24/7**로 재정비 (수수료 논거 탈피)
- [ ] 데모 영상 **3분 이내** 제약 반영해 시나리오 압축
- [ ] devnet 전환 + Discord에서 devnet SOL 추가 요청

### 여유 있으면
- [x] pay.sh `--sandbox`로 에이전트가 시세 데이터 구매 (심사 기준 3 강화) — 7/30 완료, `core/market.py`
- [ ] AP2 mandate 개념으로 한도 정책 재표현
- [ ] 검수 완료 시 settle하는 에스크로 구조 (x402 표준 공백 → 독자 기여 어필)
