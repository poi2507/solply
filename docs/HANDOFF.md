# 인수인계 — 다른 세션에서 이어받을 때 먼저 읽는 문서

> 마지막 갱신: **2026-07-28** · 저장소 `github.com/poi2507/solply` (private)
> 프로젝트 배경은 [README](../README.md), 작업 규칙은 [CLAUDE.md](../CLAUDE.md),
> 작업 계획은 [wbs.md](wbs.md).

## 30초 요약

**Solply** — 프랜차이즈 본사·가맹점 식자재 대금(물대)을 AI 에이전트들이 청구·검증·협상·결제·정산까지 사람 개입 없이 처리한다. GCP × Solana AI Agentic 해커톤 출품작.

**제출 마감 8/3 23:59 KST.** 파이널리스트 발표 8/7, 데모데이 8/21.

지금 상태: **데모 6종(정상·차감 협상·P2P 직거래·거부·유예→예약 실행·분할 역제안)이 x402 왕복으로 처음부터 끝까지 돌아간다.** 실제 온체인 USDC 결제가 발생하고(가맹점→본사, 가맹점→가맹점 모두), 신용점수가 이력에서 계산되어 데모 중에 오르고, ADK 어시스턴트가 대화로 조회·승인을 대신 누른다. **개발·수익모델·소개서 초안까지 전부 끝났다.** 남은 건 GCP 결제(👤) → Vertex·배포, devnet 코인(👤) → 전환 리허설, 영상·제출.

---

## 🔴 다음 세션(집 맥)에서 바로 할 일 — 2026-07-28 저녁 기준

> **7/28 밤: 데모 금액을 1/5로 낮췄다.** devnet USDC faucet이 한 번에 20씩만 주는데
> 기존 규모(청구 35 USDC)로는 한 바퀴도 못 돈다. 청구서는 7 USDC, 자동결제 상한 10,
> 최소 잔액 2로 스케일했다. 심사에서 보는 건 금액이 아니라 플로우라 손해가 없다.
> **devnet 전환 완료 (7/28 밤).** 지갑 4개에 SOL·USDC 수령, 토큰 계정 사전 생성,
> **6종 데모가 devnet에서 완주하고 explorer 링크가 살아난다.** 심사 기준 4번 충족.
>
> 네트워크 전환은 `make devnet` / `make localnet`. **devnet 상태에서 `make dev`를 돌리면
> 로컬넷으로 되돌아간다** — 시연 중에는 `make pay`로 결제 서비스만 재시작할 것.

### 0. 동기화 ⏱️2분

```bash
cd ~/workspace/gcp-solana-agentic-hackathon && git pull

# 개발·리허설 (로컬넷)
make localnet && make db && make dev
make demo-mock     # 6종(A→B→E→D→C→F) 완주 + 정산 리포트가 나오면 정상

# 시연·촬영 (devnet — explorer 링크가 살아난다)
make devnet && make pay        # validator 없이 결제 서비스만
make demo-mock                 # 또는 make demo (Gemini)
```

7/28 회사 맥에서 커밋 13개가 올라갔다(개발 마무리 + 어시스턴트 + 문서). **의존성 추가 없음**
— pull이면 되고, 혹시 import 에러가 나면 `cd backend && uv sync` 한 번. 집 맥의 `.env`·지갑은
그대로 유효하다. 특정 장면만 보려면 `--only f`(분할 역제안), `--only e`(P2P) 식으로.

### 1. 사용자 — 오늘 밤에 걸어둘 것 (크리티컬 패스, 전부 사람 손)

1. **Discord devnet SOL 요청** ⏱️10분 — 유일하게 "대기 시간"이 있는 항목이라 최우선.
   discord.gg/bYrJCUAsj → 운영 채널에 devnet SOL 추가 수령 요청.
2. **devnet USDC** ⏱️5분 — https://faucet.circle.com — **store-a·b만, store-c는 제외**
   (잔액 부족이 유예 시나리오). 주소는 §1 아래 "집 맥 지갑" 참고.
3. **GCP 결제 카드 교체** ⏱️10분 (기한 7/30) — Mastercard 체크카드 → 신용카드.
   ₩16,000 배너는 입금해도 크레딧으로 적립된다. 풀리면 집 맥에서:
   ```bash
   gcloud auth login && gcloud auth application-default login
   gcloud config set project <PROJECT_ID>
   gcloud services enable aiplatform.googleapis.com
   make vertex-check        # 통과하면 .env에 넣을 두 줄을 알려준다
   ```

### 2. Claude — 결제가 풀리는 즉시

1. **Vertex 전환 마무리** — `.env` 두 줄 + **어시스턴트 호환 수정**: `app/assistant/agent.py`가
   `config.HQ_MODEL`을 직접 읽는다 → `factory.model_for("hq")`로 바꾸고
   `GOOGLE_GENAI_USE_VERTEXAI` 환경을 따라가게 (몇 줄, 회사 맥 세션이 남긴 숙제).
2. **Phase 3 배포** (wbs 3.2~3.7) — 결제서비스·백엔드 Cloud Run, Secret Manager, 스모크.
3. 결제가 안 풀린 동안 할 수 있는 것: **영상 대본 초안(4.5)**, README 정비(4.9).

### 3. 사용자 — 제출물 (8/1~)

- **소개서 다듬기(4.8)**: [pitch.html](pitch.html) 12장 초안 완성돼 있음 — 표지·마지막 장의
  **팀명·라이브 URL·영상 URL만 비어 있다**. `open docs/pitch.html` → Chrome 인쇄 →
  PDF 저장(여백 없음 + 배경 그래픽 체크) = 벡터 PDF.
- **영상 촬영(8/1~2)**: 장면별 `--only`로. 어시스턴트 장면은 무료 티어 한도 때문에
  데모와 **따로** 찍을 것 (Vertex 전환 후엔 무관).
- 수익모델은 ✅ 확정 — [revenue-model.md](revenue-model.md) (3층: 구독 → P2P 중개료 → 온체인 여신).
  가맹점 수 통계(약 35만)만 제출 전 재확인.

### 7/28 회사 맥에서 끝난 것 (요약)

- **Phase 1** x402 에이전트 연결 · **Phase 2** 신용 실계산·거부·예약 실행 · **Phase 2.5** P2P 직거래
  · **Phase 2.7** 이중결제 가드·사람 승인·멀티턴 분할·정산 리포트
- **대시보드 운영 3종**: 정책 변경 증빙(`policy.updated`, actor=human) · 예약 "지금 실행" 버튼
  (입금 시뮬 포함, Cloud Scheduler는 본문 없이 호출 시 실잔액 실행) · 가맹점 카드 재고 칩
- **ADK 어시스턴트**: 대시보드 채팅 — 조회·승인·예약 실행을 대화로. 역할 분담이 설계 결정:
  **LangGraph=거래 두뇌(감사 가능한 그래프), ADK=사람 창구(도구 호출)**. mock 모드에선 503.
- 촬영 전 수정 3건(미수금 이중계산·mock 중복 출력·분할 회차 402), 낡은 HTML 문서 3개 삭제,
  `make test` 임시 저장소 격리(라이브 DB 안 더럽힘), 테스트 **99개**
- **심사 Q&A 라이브 카드**: 정책 UI에서 자동결제 상한을 **5 USDC**로 낮추고 `--only a` → 에이전트 멈춤 →
  승인 패널 → 버튼 → 이어서 결제. 어시스턴트에게 "승인 대기 있어? 승인해줘"로도 같은 흐름.
- 데모는 자기 유지된다(카드정산 입금 시뮬 + db.reset이 재고도 시드로 복귀) — 리허설 무제한.
- 주의: Gemini 무료 티어에서 `make demo`와 어시스턴트를 **동시에** 쓰면 429 가능 (경로가 둘).

---

## 1. 로컬 환경 되살리기

세 개의 서버가 필요하다. 순서대로:

```bash
cd ~/workspace/gcp-solana-agentic-hackathon   # 집 맥 (메인) — 회사 맥은 ~/workplace/solply

make db      # PostgreSQL (:5432) — 데이터가 여기 있다
make dev     # 블록체인(:8899) + 결제(:3000) + API/대시보드(:8080)
```

`make dev`는 validator를 띄우고 지갑·USDC까지 세팅한 뒤 세 서버를 붙인다. 대시보드는 http://localhost:8080.

데모 실행 (다른 터미널):

```bash
make demo-mock   # 규칙 기반, 몇 초 — 개발·리허설용 (온체인 결제는 실제로 발생)
make demo        # Gemini 판단, 10분+ — 심사·영상용
make test        # 17개 테스트
make help        # 전체 명령
```

### 작업 머신 2대 (7/27부터)

**집 맥이 메인**(최종 작업·devnet 시연·제출), 회사 맥은 낮 시간 보조 개발용이다.

**① 집 맥 — macOS 13.5 Intel, Homebrew 죽음.** 레포 `~/workspace/gcp-solana-agentic-hackathon`. 전부 공식 인스톨러로 우회 설치, `~/.zshrc`의 `# gcp-solana-hackathon-paths` 블록에 PATH 등록. **여기서는 brew 쓰지 말 것** — 공식 인스톨러나 conda-forge.

| 도구 | 위치 |
|---|---|
| Node 24 | `~/.local/node/bin` |
| uv | `~/.local/bin` |
| Solana CLI 4.1 | `~/.local/share/solana/install/active_release/bin` |
| gcloud SDK | `~/.local/google-cloud-sdk` |
| gh CLI | `~/.local/bin/gh` (poi2507 로그인됨) |
| PostgreSQL | `~/.local/pg-env/bin` (conda-forge), 데이터 `~/.local/pgdata` |

원본 지갑 키(`~/.config/solana/solply/`)와 `GOOGLE_API_KEY`가 든 `backend/.env`는 **집 맥에만 있다.**

**② 회사 맥 — Apple Silicon, Homebrew 정상 (7/27 환경 구축).** 레포 `~/workplace/solply`. uv·Solana CLI는 공식 인스톨러(집 맥과 같은 경로), Node·PostgreSQL 17·gh는 Homebrew. gcloud 미설치. 지갑은 **로컬넷 전용으로 새로 생성**(devnet 코인 받는 주소 아님). `GOOGLE_API_KEY`는 집 폴더 복사본(`~/workplace/gcp-solana-agentic-hackathon`)에서 가져와 설정 완료(7/27, 유효성 확인됨) — `make demo`(Gemini)도 동작한다. Docker가 8000 포트를 점유해 validator gossip을 8010으로 옮겼다(`dev.sh`·`Makefile`에 반영, 집 맥에서도 무해).

---

## 2. 지금 무엇이 되고 무엇이 안 되나

| 항목 | 상태 |
|---|---|
| 로컬넷 + 지갑 4개 + 자체 USDC | ✅ |
| USDC 전송 · memo · 온체인 3중 검증 | ✅ |
| 본사/가맹점 에이전트 (도구 각 7개) | ✅ |
| A지점 정상 결제 / B지점 차감 협상 / C지점 유예 협상 | ✅ 전부 완주 |
| FastAPI 대시보드 + SSE 실시간 반영 | ✅ |
| x402 402 챌린지 + 정산 확정 | ✅ 엔드포인트는 동작 |
| PostgreSQL 저장소 | ✅ |
| mock LLM 리허설 모드 | ✅ |
| **LangGraph 전환** (graph/node/state 분리) | ✅ 2026-07-27 |
| **프롬프트 md 분리** (`<agent>/prompts/*.md`) | ✅ |
| **거래 정책 DB화 + 프론트 설정 UI** | ✅ 상한·하한을 사용자가 설정, 즉시 판단에 반영 |
| Vertex AI 전환 (크레딧·한도 해방) | ⏸ 패키지·분기·점검 스크립트는 준비됨. **gcloud 인증과 결제만 남음** → `make vertex-check` |
| **x402를 에이전트 플로우에 실제 연결** | ✅ 2026-07-27 — 402 챌린지 → 조건 선택 → 결제 → PAYMENT-SIGNATURE 제출 → 정산 확정. 유예도 402 조건 선택으로 서사 연결. `tests/test_x402_flow.py` |
| **온체인 신용점수 실계산** | ✅ 2026-07-28 — `core/credit.py`. 시드 이력 + 이번 세션 정산이 점수에 반영, 대시보드에 근거(정시납·연체·분쟁) 표시. 88/81/92는 이제 계산 결과다 |
| **이상 청구 거부 시나리오 (D)** | ✅ 2026-07-28 — 발주 목록에 없는 품목(DEL-004 랍스터) 감지 → 거부 → 사람 에스컬레이션 |
| **예약 납부 실행** | ✅ 2026-07-28 — `POST /api/schedules/{id}/run` + 데모가 시간을 당겨 실행. C지점이 `settled`까지 간다 |
| **가맹점 간 직거래 (시나리오 E)** | ✅ 2026-07-28 — B 재고 소진 → 조달 비교 → A와 협상 → **본사 승인** → B→A x402 온체인 결제 → 장부 기록. 트랙 C 커버 |
| **멀티턴 역제안 (시나리오 F)** | ✅ 2026-07-28 — 전액 유예 불가 → 본사가 분할 2회 역제안(실제 분할 청구서 발행) → 가맹점 재평가 → 1회차 x402 결제·2회차 예약 |
| **사람 승인 (human-in-the-loop)** | ✅ 2026-07-28 — 상한 초과로 멈춘 결제를 대시보드에서 승인/반려. 승인하면 에이전트가 이어서 결제(라이브 검증 완료). 사람 개입은 actor=human으로 증빙 |
| **이중 결제 방지** | ✅ 2026-07-28 — paid/settled 청구서 재결제 차단 (재시도·중복 호출 안전) |
| **정산 리포트 (Gemini)** | ✅ 2026-07-28 — `/api/report` + 대시보드 버튼 + 데모 마무리. mock은 규칙 조립, Gemini는 자연어 생성 |
| **정산 어시스턴트 (ADK)** | ✅ 2026-07-28 — 대시보드 채팅. ADK Agent가 사람 권한 도구 8개(조회·승인·반려·예약 실행)로 대화 응대. **역할 분담: LangGraph=거래 두뇌, ADK=사람 창구.** mock 모드에선 비활성(503) |
| **Cloud Run 배포** | ❌ |
| **devnet 전환** | ❌ 지금은 로컬넷 |
| **소개서 초안** | ✅ 2026-07-28 — [pitch.html](pitch.html) 12장. 남은 것: 표지·마지막 장의 팀명·URL 채우기, 사용자 다듬기(4.8) 후 PDF 내보내기 |
| **데모 영상** | ❌ 8/1~2 촬영 예정 (대본은 devnet 전환 후) |
| **수익모델** | ✅ 2026-07-28 — 3층 구조(구독·P2P 중개료·온체인 여신) 확정, [revenue-model.md](revenue-model.md) |

---

## 3. 남은 일정

> 상세 작업 분해는 [wbs.md](wbs.md) — 25개 항목, 담당·의존성·크리티컬 패스·리스크.

| 날짜 | 목표 | 담당 |
|---|---|---|
| 7/28 (월) | 에이전트가 x402로 대화 · 신용점수 실계산 착수 | 🤖 |
| 7/29 (화) | 데모 4종·예약 실행 → 오후 P2P 착수 | 🤖 |
| 7/30 (수) | **시나리오 E (가맹점 간 직거래) 완주** · **GCP 결제 해결** | 🤖 👤 |
| **7/31 (목)** | **Cloud Run 배포** — 라이브 URL(가산점) | 🤖 |
| **8/1 (금)** | **devnet 전환 + 데모 영상 3분** | 🤖 👤 |
| 8/2 (토) | 소개서 PPT (타깃·문제·**수익모델**·아키텍처) | 🤝 |
| **8/3 (일)** | README 정비, **레포 public 전환**, 23:59 전 제출 | 👤 |

### 사용자(taewoong) 작업 — 기한 순

| 기한 | 할 일 | 왜 |
|---|---|---|
| **7/28** | Discord 가입 + devnet SOL 요청 | 답변 지연 리스크. 없으면 explorer 링크 없는 데모가 된다 |
| **7/28** | devnet USDC 수령 (faucet.circle.com) | 즉시 가능. store-a·b만, **c는 제외** |
| **7/30** | GCP 결제 카드 교체 | 라이브 URL(가산점). 안 되면 포기 가능 |
| **8/1** | 수익모델 확정 | 소개서 필수 항목 |
| **8/2** | 데모 영상 촬영 (대본은 Claude가 준비) | 3분 이내 |
| **8/3** | 최종 제출 | 마감 23:59 |

**참고**: GCP $300 크레딧은 **Gemini API에 못 쓴다**(주최측 명시, 별도 시스템). Gemini는 AI Studio 무료 티어로 이미 동작 중이므로, 크레딧은 Cloud Run 배포에만 필요하다.
Discord `#pay-sh-질문` 채널에 Solana Foundation 개발자(Ludo)가 한/영으로 직접 답변한다.

---

## 4. 아키텍처 요약

```
backend/app/
├── main.py        FastAPI 조립 (API + x402 + 프론트 서빙, 컨테이너 1개)
├── config.py      환경변수는 여기서만 읽는다
├── api/           dashboard.py(+SSE) · policy.py(정책 설정) · x402.py
├── agents/        state.py(BaseState) · runner.py(실행기) · prompts.py(md 로더) · utils.py
│   ├── hq/        graph.py · node.py · state.py · tools.py · prompts/{role,task,policy,output}.md
│   └── store/     (동일 구조)
├── core/          protocol.py(x402) · policy.py(거래 정책) · fixtures.py
├── db/            store.py(파사드) → local_store.py | postgres_store.py
├── llm/           factory.py(gemini|vertex|mock) · judge.py(판단) · rules.py(mock 규칙)
└── solana/        payments.py (TS 결제 서비스 HTTP 클라이언트)

frontend/          빌드 없는 정적 대시보드 (FastAPI가 /assets로 서빙)
payments/          TypeScript — Solana USDC 전송·검증 (Solana SDK가 JS라서 분리)
```

### 지켜야 할 규칙

- 환경변수는 `config.py`에서만. 다른 모듈에서 `os.getenv` 직접 호출 금지.
- 저장소 접근은 `app.db.store` 파사드로만. local/postgres를 갈아끼운다.
- 프롬프트는 `<agent>/prompts/*.md`에만. role·task·policy·output 네 파일.
  프롬프트에 적는 도구 이름은 실제 함수명과 일치해야 한다 (테스트가 검사).
- 한도·기준 같은 개인별 수치는 md가 아니라 **DB의 정책**에서 주입된다 (`core/policy.py`).
- 에이전트 도구는 부수효과만. 순수 계산은 `utils.py`, 판단은 `llm/judge.py`, 흐름은 `node.py`.
- 결제는 로컬넷/devnet 전용. **메인넷 금지.**

---

## 5. 알려진 함정 (같은 데서 두 번 막히지 않도록)

**Gemini 무료 티어는 모델당 분당 5회.** 에이전트 4대가 도구를 여러 번 부르면 금방 소진된다. 본사는 `gemini-3.6-flash`, 가맹점은 `gemini-3.5-flash-lite`로 나눠서 한도를 분산해뒀고(한도가 모델별로 따로 걸린다), `runner.py`가 429를 잡아 재시도한다. 그래도 `make demo`는 10분 이상 걸리니 **개발 중에는 `make demo-mock`을 쓸 것.**

**`gemini-2.5-flash`는 신규 사용자에게 제공되지 않는다.** 3.x 계열을 써야 한다.

**Memo 프로그램 주소는 `MemoSq4gqABAXKb96qnH8Tys...`** — `Tys`의 s가 소문자다. 대문자로 적으면 "계정 없음"으로 실패한다. 로컬넷에는 이 프로그램이 없어서 메인넷에서 `--clone`으로 가져와야 하고, `make chain`과 `scripts/dev.sh`에 반영돼 있다.

**가맹점 USDC가 떨어지면 결제가 조용히 실패한다.** 데모를 여러 번 돌리면 소진되니 보충:
```bash
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"
MINT=$(grep '^USDC_MINT=' payments/.env | cut -d= -f2)
HQ=~/.config/solana/solply/hq.json
spl-token mint "$MINT" 100 --recipient-owner "$(solana-keygen pubkey ~/.config/solana/solply/store-a.json)" \
  --url localhost --fee-payer $HQ --mint-authority $HQ
```
**단 store-c는 보충하지 말 것** — 잔액이 부족해야 유예 협상 시나리오가 발동한다.

**데모 시나리오는 코드가 아니라 데이터로 만들어진다.** `backend/data/fixtures.json`의 B지점 검수 불일치(닭 10 청구 / 9 입고)와 C지점 신용점수 92, 그리고 지갑 잔액(A·B 넉넉, C 5 USDC)이 시나리오의 전부다. 건드리면 데모가 죽고, `tests/test_core.py`가 이를 지킨다.

**conda Postgres에는 zoneinfo가 없다.** 시스템 타임존(KST-9)을 못 읽어서 UTC로 고정해뒀다.

**Solana validator가 8000번 포트를 쓴다.** FastAPI는 8080을 쓰는 이유. 회사 맥에서는 Docker가 8000을 점유하고 있어 validator gossip 포트를 **8010**으로 옮겼다 (`dev.sh`·`Makefile`에 반영, 집 맥에서도 무해).

**API 키가 `.env.example`에 들어간 적이 있다.** 이 파일은 git에 올라가므로 실제 값은 `backend/.env`에만. **제출 시 레포를 public으로 바꾸므로** 그 전에 한 번 더 확인할 것.

---

## 6. 심사 대응 요약 (발표 준비할 때)

**4대 기준**: 혁신성·UX / AI 활용도(Gemini·GC 스택) / 인프라 연동(USDC·Solana Pay·pay.sh) / **실제 구동**(실행 로그·트랜잭션). 배점 비공개.

**"목업은 심사 대상에서 제외"** — 주최측이 경고 배너로 명시. 데모데이 당일 실제 결제가 동작해야 한다.

**"왜 온체인인가"에 대한 우리 답** (수수료 논거는 약하다 — 금융위가 "초소액 아니면 카드가 쌀 수 있다"고 반론):
1. 에이전트는 은행 계좌를 못 만든다. 카드망은 사람 승인 전제.
2. B2B 외상 30~60일 → 0.4초.
3. 납부 이력이 조작 불가능한 신용이 된다 (여신 자동화로 확장).
4. 본사·가맹점이 같은 장부를 본다 (정산 불신 해소).

**차별화 포인트는 협상.** 다른 팀은 "자동 결제"까지 만들 것이다. 실패 상황에서 에이전트끼리 대안을 제시하고 합의하는 게 우리만의 훅이다.

**시장 정보**: 현재 x402 트래픽은 디지털 재화(데이터·API) 일색이고 **실물 B2B는 공백**이다. "실물 B2B 첫 사례"로 포지셔닝 가능. 단 "왜 아직 아무도 안 했나(실물 이행 리스크·분쟁)"에 답을 준비할 것.

**약점**: 사용자가 프랜차이즈 도메인 경험이 없다. 실제 물대 정산 주기·검수 분쟁 사례를 리서치해서 Q&A를 방어해야 한다.

---

## 7. 문서 지도

| 문서 | 내용 |
|---|---|
| [README.md](../README.md) | 프로젝트 개요, 구조, 실행법 |
| [CLAUDE.md](../CLAUDE.md) | 작업 규칙 (AI가 읽는 것) |
| [product-design.md](product-design.md) | 프로덕트 설계, 에이전트 구성, 데모 시나리오 |
| [decision-log.md](decision-log.md) | 아이디어가 여기까지 온 과정, 기각된 후보들 |
| [kickoff-notes.md](kickoff-notes.md) | 킥오프 발표자료 4종 분석 (일정·x402 스펙·pay.sh) |
| [wbs.md](wbs.md) | 남은 기간 작업 분해, 담당·의존성·리스크 |
| [store-to-store-design.md](store-to-store-design.md) | 시나리오 E(가맹점 간 P2P 직거래) 구현 설계 |
| [checklist.md](checklist.md) | 제출 전 체크리스트 |
